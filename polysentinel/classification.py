import json
import time

from .clients import UpstreamError
from .provenance import API_URL, HASH_RE
from .receipts import parse_receipt, classify, verified_transfers


def pending_count(conn):
    pending_transfers = conn.execute(
        "SELECT COUNT(*) FROM funding_reports WHERE status IN ('queued','running')"
    ).fetchone()[0]
    pending_classifications = conn.execute(
        "SELECT COUNT(*) FROM classification_jobs WHERE status IN ('queued','running')"
    ).fetchone()[0]
    return pending_transfers + pending_classifications


def queue_classification(store, address, now=None):
    now = int(time.time()) if now is None else now
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute(
            "SELECT 1 FROM funding_edges WHERE root=? LIMIT 1", (address,)
        ).fetchone():
            return "no_evidence", False
        row = conn.execute(
            "SELECT * FROM classification_jobs WHERE address=?", (address,)
        ).fetchone()
        if row and row["status"] in ("queued", "running"):
            return row["status"], False
        if row and row["requested_at"] > now - 600:
            return "cooldown", False
        if (
            conn.execute(
                "SELECT COUNT(*) FROM funding_requests WHERE requested_at>?",
                (now - 86400,),
            ).fetchone()[0]
            >= 30
        ):
            return "daily_limit", False
        if pending_count(conn) >= 10:
            return "busy", False
        conn.execute(
            """INSERT INTO classification_jobs(address,status,requested_at) VALUES(?,'queued',?)
            ON CONFLICT(address) DO UPDATE SET status='queued',requested_at=excluded.requested_at,
            started_at=NULL,generation=generation+1""",
            (address, now),
        )
        conn.execute(
            "INSERT INTO funding_requests(address,requested_at) VALUES(?,?)",
            (address, now),
        )
    return "queued", True


def process_classification(store, client, now=None, max_requests=25, max_seconds=90):
    now = int(time.time()) if now is None else now
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE classification_jobs SET status='queued',started_at=NULL,generation=generation+1 WHERE status='running' AND started_at<?",
            (now - 600,),
        )
        row = conn.execute(
            "SELECT * FROM classification_jobs WHERE status='queued' ORDER BY requested_at,address LIMIT 1"
        ).fetchone()
        if not row:
            return False
        address, generation = row["address"], row["generation"]
        conn.execute(
            "UPDATE classification_jobs SET status='running',started_at=? WHERE address=?",
            (now, address),
        )
        hashes = [
            item[0]
            for item in conn.execute(
                """SELECT tx_hash FROM funding_edges WHERE root=? AND kind LIKE 'erc20%'
            GROUP BY tx_hash ORDER BY MIN(depth),MAX(timestamp) DESC,tx_hash LIMIT 501""",
                (address,),
            )
        ]
        cached = {
            item["tx_hash"]: dict(item)
            for item in conn.execute(
                """SELECT * FROM receipt_cache
            WHERE tx_hash IN (SELECT tx_hash FROM funding_edges WHERE root=?)""",
                (address,),
            )
        }
    requested, verified, failed, skipped, execution_failures = 0, 0, 0, 0, 0
    deadline = time.monotonic() + max_seconds
    cache_updates = []
    for tx_hash in hashes[:500]:
        if not HASH_RE.fullmatch(tx_hash):
            failed += 1
            continue
        prior = cached.get(tx_hash)
        if (
            prior
            and prior["status"] == "verified"
            and prior["checked_at"] >= now - 3600
        ):
            verified += 1
            continue
        if requested >= max_requests or time.monotonic() >= deadline:
            skipped += 1
            continue
        requested += 1
        try:
            payload = client.get(
                API_URL,
                {
                    "chainid": 137,
                    "module": "proxy",
                    "action": "eth_getTransactionReceipt",
                    "txhash": tx_hash,
                    "apikey": client.settings.etherscan_key,
                },
            )
            parsed = parse_receipt(payload, tx_hash)
        except (UpstreamError, ValueError, TypeError, KeyError):
            parsed = {
                "status": "unknown",
                "receipt": None,
                "reason": "Receipt lookup unavailable",
            }
        if parsed["status"] == "verified":
            verified += 1
            cache_updates.append(
                (tx_hash, int(time.time()), "verified", json.dumps(parsed))
            )
        else:
            if parsed["status"] == "failed":
                execution_failures += 1
            else:
                failed += 1
            if (
                parsed["status"] == "failed"
                or not prior
                or prior["status"] != "verified"
            ):
                cache_updates.append(
                    (tx_hash, int(time.time()), parsed["status"], json.dumps(parsed))
                )
    result = {
        "requests": requested,
        "verified_receipts": verified,
        "unavailable_receipts": failed,
        "failed_execution_receipts": execution_failures,
        "skipped_receipts": skipped,
        "transactions_in_sample": min(500, len(hashes)),
        "transactions_truncated": len(hashes) > 500,
        "max_requests": max_requests,
        "warnings": [
            "Receipt classification is not funding provenance, proof of intent, or a finalized-chain audit."
        ],
    }
    status = "partial" if failed or skipped or len(hashes) > 500 else "complete"
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT generation,status FROM classification_jobs WHERE address=?",
            (address,),
        ).fetchone()
        if current["generation"] != generation or current["status"] != "running":
            return True
        conn.executemany(
            "INSERT OR REPLACE INTO receipt_cache VALUES(?,?,?,?)", cache_updates
        )
        conn.execute(
            "UPDATE classification_jobs SET status=?,checked_at=?,result=? WHERE address=?",
            (status, int(time.time()), json.dumps(result), address),
        )
    return True


def classify_saved(conn, address, edges, now=None):
    now = int(time.time()) if now is None else now
    cached = {
        item["tx_hash"]: dict(item)
        for item in conn.execute(
            """SELECT * FROM receipt_cache
        WHERE tx_hash IN (SELECT tx_hash FROM funding_edges WHERE root=?)""",
            (address,),
        )
    }
    job = conn.execute(
        "SELECT * FROM classification_jobs WHERE address=?", (address,)
    ).fetchone()
    info = json.loads(job["result"]) if job and job["result"] else {}
    info.update(
        status=job["status"] if job else "not_requested",
        checked_at=job["checked_at"] if job else None,
    )
    canonical = {}
    parsed_cache = {
        tx_hash: json.loads(item["payload"]) for tx_hash, item in cached.items()
    }
    for edge in sorted(
        edges, key=lambda item: (item["depth"], -item["timestamp"], item["id"])
    ):
        edge = {**edge, "root": address}
        subject = address
        if edge["depth"] > 0:
            subject = edge["receiver"] if edge.get("ancestry") else edge["sender"]
        edge["classification_subject"] = subject
        cached_row = cached.get(edge["hash"])
        parsed = parsed_cache.get(
            edge["hash"],
            {"status": "unknown", "receipt": None, "reason": "Receipt not fetched"},
        )
        matches = verified_transfers(edge, parsed)
        if matches:
            for match in matches:
                verified_edge = {
                    **edge,
                    "id": match["event_id"],
                    "event_id": match["event_id"],
                    "log_index": match["log_index"],
                    "identity_ambiguous": False,
                    "raw_value": match["raw_value"],
                }
                verified_edge["classification"] = classify(
                    {**verified_edge, "root": subject}, parsed
                )
                verified_edge["receipt_checked_at"] = cached_row["checked_at"]
                verified_edge["receipt_stale"] = cached_row["checked_at"] < now - 3600
                canonical.setdefault(match["event_id"], verified_edge)
        else:
            edge["classification"] = classify({**edge, "root": subject}, parsed)
            if cached_row:
                edge["receipt_checked_at"] = cached_row["checked_at"]
                edge["receipt_stale"] = cached_row["checked_at"] < now - 3600
            canonical.setdefault(edge["id"], edge)
    result = sorted(
        canonical.values(),
        key=lambda item: (-item["timestamp"], item["depth"], item["id"]),
    )
    counts = {}
    direct = []
    for edge in result:
        category = edge["classification"]["category"]
        counts[category] = counts.get(category, 0) + 1
        if edge["depth"] == 0 and category in (
            "direct_transfer_in",
            "direct_transfer_out",
            "direct_transfer",
        ):
            direct.append(edge)
    info.update(counts=counts, direct_transfers=direct, edges_in_display=len(result))
    return result, info
