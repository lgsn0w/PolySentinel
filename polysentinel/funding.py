import hashlib
import json
import time
from decimal import Decimal, localcontext

from .provenance import investigation, INFRASTRUCTURE
from .classification import pending_count, queue_classification, classify_saved

CAUTION = "Transfers prove movement of assets, not common ownership, identity, insider knowledge, or the source of a specific bet."


def queue(store, address, now=None):
    now = int(time.time()) if now is None else now
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM funding_reports WHERE address=?", (address,)
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
            """INSERT INTO funding_reports(address,requested_at) VALUES(?,?)
            ON CONFLICT(address) DO UPDATE SET status='queued',requested_at=excluded.requested_at,
            started_at=NULL,generation=generation+1""",
            (address, now),
        )
        conn.execute(
            "INSERT INTO funding_requests(address,requested_at) VALUES(?,?)",
            (address, now),
        )
    return "queued", True


def process_one(store, client, now=None):
    now = int(time.time()) if now is None else now
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE funding_reports SET status='queued',started_at=NULL,generation=generation+1 WHERE status='running' AND started_at<?",
            (now - 600,),
        )
        row = conn.execute(
            "SELECT * FROM funding_reports WHERE status='queued' ORDER BY requested_at,address LIMIT 1"
        ).fetchone()
        if not row:
            return False
        address, generation = row["address"], row["generation"]
        conn.execute(
            "UPDATE funding_reports SET status='running',started_at=? WHERE address=?",
            (now, address),
        )
    try:
        report = investigation(client, address)
    except Exception:
        report = {
            "address": address,
            "status": "error",
            "edges": [],
            "nodes": [],
            "warnings": ["Investigation failed; retry after the cooldown."],
            "coverage": [],
        }
    finished = int(time.time())
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT generation,status FROM funding_reports WHERE address=?", (address,)
        ).fetchone()
        if current["generation"] != generation or current["status"] != "running":
            return True
        previous = conn.execute(
            "SELECT report,checked_at FROM funding_reports WHERE address=?", (address,)
        ).fetchone()
        if previous["report"] and report["status"] != "complete":
            report["previous_evidence_retained"] = True
            report["previous_evidence_checked_at"] = previous["checked_at"]
        else:
            conn.execute("DELETE FROM funding_edges WHERE root=?", (address,))
        for edge in report.get("edges", []):
            edge = {
                **edge,
                "observed_at": finished,
                "observation_generation": generation,
            }
            encoded = json.dumps(edge, sort_keys=True, separators=(",", ":"))
            identity = edge.get("id") or hashlib.sha256(encoded.encode()).hexdigest()
            conn.execute(
                """INSERT OR REPLACE INTO funding_edges VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    address,
                    identity,
                    edge["sender"],
                    edge["receiver"],
                    edge.get("contract") or "native",
                    edge["amount"],
                    edge["timestamp"],
                    edge["hash"],
                    edge["kind"],
                    edge["depth"],
                    encoded,
                ),
            )
        conn.execute(
            "UPDATE funding_reports SET status=?,checked_at=?,report=? WHERE address=?",
            (report["status"], finished, json.dumps(report), address),
        )
    if getattr(getattr(client, "settings", None), "etherscan_key", "") and report.get(
        "edges"
    ):
        queue_classification(store, address)
    return True


def relationships(conn, address):
    rows = conn.execute(
        """SELECT DISTINCT e.root AS peer,e.sender AS counterparty,e.contract,e.tx_hash,
        own.tx_hash AS root_hash,'shared_funder' AS type FROM funding_edges own JOIN funding_edges e
        ON e.sender=own.sender AND e.contract=own.contract
        WHERE own.root=? AND own.receiver=own.root AND e.receiver=e.root AND e.root!=own.root
        AND own.depth=0 AND e.depth=0 AND own.contract!='native'
        UNION ALL
        SELECT DISTINCT e.root AS peer,e.receiver AS counterparty,e.contract,e.tx_hash,
        own.tx_hash AS root_hash,'shared_destination' AS type FROM funding_edges own JOIN funding_edges e
        ON e.receiver=own.receiver AND e.contract=own.contract
        WHERE own.root=? AND own.sender=own.root AND e.sender=e.root AND e.root!=own.root
        AND own.depth=0 AND e.depth=0 AND own.contract!='native'
        ORDER BY 1,2,3,6,4,5 LIMIT 501""",
        (address, address),
    ).fetchall()
    grouped = {}
    for row in rows[:500]:
        counterparty, peer = row["counterparty"], row["peer"]
        if (
            counterparty in (peer, address)
            or counterparty in INFRASTRUCTURE
            or counterparty == "0x" + "0" * 40
        ):
            continue
        key = (peer, counterparty, row["contract"], row["type"])
        evidence = grouped.setdefault(key, {"peer": set(), "root": set()})
        evidence["peer"].add(row["tx_hash"])
        evidence["root"].add(row["root_hash"])
    signals = [
        {
            "wallet": key[0],
            "counterparty": key[1],
            "contract": key[2],
            "type": key[3],
            "peer_transactions": sorted(evidence["peer"]),
            "root_transactions": sorted(evidence["root"]),
            "strength": "observed relationship; ownership unknown",
        }
        for key, evidence in sorted(grouped.items())
    ]
    return signals[:100], len(rows) > 500 or len(signals) > 100


def behavior(conn, address, now=None):
    now = int(time.time()) if now is None else now
    rows = conn.execute(
        """WITH sample AS (SELECT * FROM trades WHERE whale_address=?
        AND timestamp BETWEEN ? AND ? ORDER BY timestamp DESC,trade_id LIMIT 500)
        SELECT a.trade_id,a.condition_id,a.tx_hash AS root_hash,b.whale_address,b.tx_hash AS peer_hash
        FROM sample a JOIN trades b ON b.condition_id=a.condition_id AND b.side=a.side AND b.outcome=a.outcome
        AND b.timestamp BETWEEN a.timestamp-120 AND a.timestamp+120
        WHERE b.whale_address!=a.whale_address
        ORDER BY a.timestamp DESC,a.trade_id,b.whale_address,b.trade_id LIMIT 5001""",
        (address, now - 604800, now),
    ).fetchall()
    peers = {}
    for row in rows[:5000]:
        item = peers.setdefault(
            row["whale_address"], {"trades": set(), "markets": set(), "evidence": set()}
        )
        item["trades"].add(row["trade_id"])
        item["markets"].add(row["condition_id"])
        item["evidence"].add((row["root_hash"], row["peer_hash"]))
    signals = [
        {
            "wallet": wallet,
            "matching_trades": len(item["trades"]),
            "markets": len(item["markets"]),
            "transactions": [
                {"root": pair[0], "peer": pair[1]}
                for pair in sorted(item["evidence"])[:10]
            ],
        }
        for wallet, item in peers.items()
        if len(item["trades"]) >= 3 and len(item["markets"]) >= 2
    ]
    return (
        sorted(signals, key=lambda item: (-item["matching_trades"], item["wallet"]))[
            :20
        ],
        len(rows) > 5000 or len(signals) > 20,
    )


def read_report(store, address):
    with store.connection() as conn:
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT * FROM funding_reports WHERE address=?", (address,)
        ).fetchone()
        if not row:
            overlap, overlap_truncated = behavior(conn, address)
            return {
                "address": address,
                "status": "not_requested",
                "edges": [],
                "nodes": [],
                "warnings": [CAUTION],
                "coverage": [],
                "relationships": [],
                "summary": [],
                "behavior": overlap,
                "behavior_truncated": overlap_truncated,
            }
        report = (
            json.loads(row["report"])
            if row["report"]
            else {"edges": [], "nodes": [], "warnings": [], "coverage": []}
        )
        report.update(
            address=address,
            status=row["status"],
            requested_at=row["requested_at"],
            checked_at=row["checked_at"],
        )
        edges = [
            json.loads(edge[0])
            for edge in conn.execute(
                "SELECT payload FROM funding_edges WHERE root=? ORDER BY timestamp DESC,edge_id LIMIT 10001",
                (address,),
            )
        ]
        report["edges_truncated"] = len(edges) > 10000
        edges = edges[:10000]
        for edge in edges:
            edge["retained_from_previous"] = (
                edge.get("observation_generation") != row["generation"]
            )
        edges, report["classification"] = classify_saved(conn, address, edges)
        report["edges"] = edges
        report["relationships"], report["relationships_truncated"] = relationships(
            conn, address
        )
        report["behavior"], report["behavior_truncated"] = behavior(conn, address)
    grouped = {}
    with localcontext() as context:
        context.prec = 400
        for edge in edges:
            if (
                edge["depth"] != 0
                or edge["receiver"] != address
                or edge["sender"] in (address, "0x" + "0" * 40)
            ):
                continue
            key = (
                edge["sender"],
                edge.get("contract") or "native",
                edge.get("asset", "Unknown"),
            )
            item = grouped.setdefault(
                key,
                {
                    "sender": key[0],
                    "contract": key[1],
                    "asset": key[2],
                    "amount": Decimal(0),
                    "transfers": 0,
                    "identity_ambiguous": False,
                    "first_seen": edge["timestamp"],
                    "last_seen": edge["timestamp"],
                },
            )
            item["amount"] += Decimal(edge["amount"])
            item["transfers"] += 1
            item["identity_ambiguous"] = item["identity_ambiguous"] or edge.get(
                "identity_ambiguous", False
            )
            item["first_seen"] = min(item["first_seen"], edge["timestamp"])
            item["last_seen"] = max(item["last_seen"], edge["timestamp"])
        report["summary"] = [
            {**item, "amount": format(item["amount"], "f")} for item in grouped.values()
        ]
    report.setdefault("warnings", []).append(CAUTION)
    report["limitations"] = [
        "Recent bounded Polygon sample, not complete lifetime history.",
        "Token symbols are untrusted metadata; compare contract addresses. Amounts are token units, not USD.",
        "Gas transfers, settlement, minting, spam and unsolicited dust are not necessarily trading deposits.",
        "Unlabelled exchanges, bridges, mixers and shared services can create false relationship signals.",
        "No cross-chain continuity, wallet-controller verification, real-world identity or exact bet-funding attribution.",
        "Upstream timing is compatible with a path, not proof that the same funds flowed through it.",
        "Relationships compare saved investigations only; absence of a match proves nothing.",
    ]
    return report
