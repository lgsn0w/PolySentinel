import hashlib
import json
import logging
import math
import re
import threading
import time

from .clients import Client
from .config import Settings
from .detection import flag_window
from .storage import Store

log = logging.getLogger(__name__)
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


def normalize(raw, market):
    wallet = str(raw["proxyWallet"]).lower()
    if not ADDRESS.fullmatch(wallet):
        raise ValueError("Invalid wallet")
    size, price = float(raw["size"]), float(raw["price"])
    if not math.isfinite(size) or not math.isfinite(price) or size <= 0 or not 0 <= price <= 1:
        raise ValueError("Invalid trade value")
    ts = int(raw["timestamp"])
    if ts <= 0 or ts > time.time() + 300:
        raise ValueError("Invalid trade time")
    side = str(raw["side"]).upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("Invalid side")
    for field in ("conditionId", "transactionHash", "asset"):
        if raw.get(field) is None or not str(raw[field]).strip():
            raise ValueError("Missing trade identity")
    outcome = raw.get("outcome")
    unlabeled = outcome == "" and raw.get("outcome_index") == 999
    if not unlabeled and (outcome is None or not str(outcome).strip()):
        raise ValueError("Missing trade identity")
    outcome = f"UNLABELED:{raw['asset']}" if unlabeled else str(outcome)
    cid = str(raw["conditionId"])
    tx_hash, asset = str(raw["transactionHash"]), str(raw["asset"])
    if not tx_hash or not asset or not cid or not outcome:
        raise ValueError("Missing trade identity")
    identity = [tx_hash.lower(), wallet, asset, cid, side, outcome, ts, size, price]
    return {"trade_id": hashlib.sha256(json.dumps(identity).encode()).hexdigest(),
            "whale_address": wallet, "timestamp": ts, "condition_id": cid,
            "market_question": market["question"], "category": market["category"],
            "side": side, "outcome": outcome, "position": f"{side} {'Unlabeled outcome' if unlabeled else outcome}",
            "size_usd": size * price, "bet_link": market["link"], "tx_hash": tx_hash}


class WhaleSentinel:
    def __init__(self, settings=None, client=None, store=None):
        self.settings = settings or Settings()
        self.store = store or Store(self.settings.database)
        self.client = client or Client(self.settings)
        self.market_cache = {}
        self.market_refresh = 0
        self.classification_offset = 0
        self.stop = threading.Event()

    def map_markets(self):
        mapped = self.client.markets()
        if not any(mapped.values()):
            raise ValueError("Cannot ingest without a market map")
        self.market_cache.update(mapped)
        self.market_refresh = time.time()
        log.info("Monitoring %d political markets", sum(value is not None for value in mapped.values()))

    def ingest(self, raw_trades, now=None):
        now = int(time.time()) if now is None else now
        prepared, pending, resolved = [], [], []
        raw_trades = list(raw_trades)
        with self.store.connection() as conn:
            ids = list(self.market_cache)
            for start in range(0, len(ids), 400):
                chunk = ids[start:start + 400]
                marks = ",".join("?" for _ in chunk)
                deferred = conn.execute(f"SELECT payload FROM pending_trades WHERE condition_id IN ({marks})", chunk).fetchall()
                raw_trades.extend(json.loads(row["payload"]) for row in deferred)
        cursor = self.store.state()["cursor"]
        for raw in raw_trades:
            ts = int(raw["timestamp"])
            if ts <= 0 or ts > now + 300:
                raise ValueError("Invalid trade time")
            cursor = max(cursor, ts)
            cid = raw.get("conditionId")
            if cid in self.market_cache and self.market_cache[cid] is None:
                resolved.append(cid)
                continue
            market = self.market_cache.get(cid)
            if market is None:
                identity = normalize(raw, {"question": "Pending classification", "category": "Unknown", "link": "#"})
                if identity["size_usd"] >= self.settings.minimum_usd:
                    pending.append((identity["trade_id"], identity["condition_id"], json.dumps(raw)))
                continue
            trade = normalize(raw, market)
            resolved.append(cid)
            if trade["size_usd"] >= self.settings.minimum_usd:
                prepared.append(trade)
        inserted = 0
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany("INSERT OR IGNORE INTO pending_trades VALUES(?,?,?)", pending)
            for trade in sorted(prepared, key=lambda t: (t["timestamp"], t["trade_id"])):
                conn.execute("INSERT OR IGNORE INTO wallets(address) VALUES(?)", (trade["whale_address"],))
                columns, values = ",".join(trade), ",".join("?" for _ in trade)
                result = conn.execute(f"INSERT OR IGNORE INTO trades({columns}) VALUES({values})", tuple(trade.values()))
                if result.rowcount:
                    inserted += 1
                    ends = conn.execute("""SELECT * FROM trades WHERE whale_address=? AND condition_id=?
                        AND side=? AND outcome=? AND timestamp BETWEEN ? AND ?""",
                        (trade["whale_address"], trade["condition_id"], trade["side"], trade["outcome"],
                         trade["timestamp"], trade["timestamp"] + self.settings.window_seconds)).fetchall()
                    for end in ends:
                        flag_window(conn, end, self.settings)
            conn.executemany("DELETE FROM pending_trades WHERE condition_id=?", ((cid,) for cid in set(resolved)))
            conn.execute("""UPDATE scanner_state SET cursor=MAX(cursor,?),last_success=?,
                last_trade=(SELECT MAX(timestamp) FROM trades),status='ok' WHERE id=1""", (cursor, now))
        return inserted

    def poll_once(self):
        if not self.market_cache or time.time() - self.market_refresh >= 3600:
            self.map_markets()
        cursor = self.store.state()["cursor"]
        since = cursor - self.settings.overlap_seconds if cursor else int(time.time()) - self.settings.lookback_seconds
        trades = self.client.trades_since(since)
        with self.store.connection() as conn:
            unresolved = {row[0] for row in conn.execute("SELECT DISTINCT condition_id FROM pending_trades")}
        unresolved.update(raw.get("conditionId") for raw in trades)
        unknown = sorted(cid for cid in unresolved if cid and cid not in self.market_cache)
        if unknown:
            start = self.classification_offset % len(unknown)
            batch = (unknown[start:] + unknown[:start])[:100]
            try:
                self.market_cache.update(self.client.conditions(batch))
            except Exception:
                log.warning("Condition lookup unavailable; unknown trades will remain durable")
            self.classification_offset += len(batch)
        return self.ingest(trades)

    def enrich_once(self, client=None):
        now = int(time.time())
        with self.store.connection() as conn:
            wallet = conn.execute("""SELECT address FROM wallets w WHERE enriched_at<? AND EXISTS
                (SELECT 1 FROM trades t WHERE t.whale_address=w.address AND flagged=1)
                ORDER BY enriched_at LIMIT 1""", (now - 3600,)).fetchone()
        if not wallet:
            return False
        intel = (client or self.client).wallet_intel(wallet["address"])
        with self.store.connection() as conn:
            fields = {k: v for k, v in intel.items() if k in
                      {"funding_source", "account_created_ts", "portfolio_value"}}
            fields["enriched_at"] = now
            assignments = ",".join(f"{key}=?" for key in fields)
            conn.execute(f"UPDATE wallets SET {assignments} WHERE address=?", (*fields.values(), wallet["address"]))
        return True

    def _enrich_loop(self):
        client = Client(self.settings)
        while not self.stop.is_set():
            try:
                self.enrich_once(client)
            except Exception:
                log.exception("Enrichment failed")
            self.stop.wait(5)
        client.session.close()

    def watch(self):
        worker = threading.Thread(target=self._enrich_loop, daemon=True)
        worker.start()
        try:
            while not self.stop.is_set():
                try:
                    log.info("Saved %d new trades", self.poll_once())
                except Exception:
                    self.store.set_status("error")
                    log.exception("Ingestion failed; durable progress retained")
                self.stop.wait(self.settings.poll_seconds)
        except KeyboardInterrupt:
            log.info("Stopping scanner")
        finally:
            self.stop.set()
            self.store.set_status("stopped")
            worker.join(timeout=2)


def main():
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    WhaleSentinel().watch()
