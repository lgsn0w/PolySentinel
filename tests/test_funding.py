from dataclasses import replace
import json
import sqlite3
import time

import pytest

from polysentinel.config import Settings
from polysentinel.funding import behavior, process_one, queue, read_report
from polysentinel.provenance import INFRASTRUCTURE
from polysentinel.storage import Store
from polysentinel.web import create_app

ROOT = "0x" + "a" * 40
PEER = "0x" + "b" * 40
SENDER = "0x" + "c" * 40
TOKEN = "0x" + "d" * 40


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.sqlite3")


def edge(
    sender=SENDER,
    receiver=ROOT,
    contract=TOKEN,
    amount="1.234567890123456789",
    depth=0,
    number=1,
):
    return {
        "id": str(number),
        "sender": sender,
        "receiver": receiver,
        "contract": contract,
        "amount": amount,
        "timestamp": 1000,
        "hash": "0x" + f"{number:064x}",
        "kind": "erc20" if contract else "native",
        "asset": "TEST" if contract else "POL",
        "depth": depth,
    }


def complete(store, monkeypatch, address, edges, status="complete", now=1000):
    queue(store, address, now)
    monkeypatch.setattr(
        "polysentinel.funding.investigation",
        lambda client, root: {
            "address": root,
            "status": status,
            "edges": edges,
            "nodes": [],
            "warnings": [],
            "coverage": [],
        },
    )
    assert process_one(store, object(), now)


def test_v1_migration_preserves_existing_rows_and_is_idempotent(tmp_path):
    path = tmp_path / "v1.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE wallets(address TEXT PRIMARY KEY,funding_source TEXT NOT NULL DEFAULT 'Unknown',account_created_ts INTEGER,portfolio_value REAL,enriched_at INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute("INSERT INTO wallets(address) VALUES(?)", (ROOT,))
    conn.execute("PRAGMA user_version=1")
    conn.commit()
    conn.close()
    migrated = Store(path)
    Store(path)
    with migrated.connection() as conn:
        assert conn.execute("SELECT address FROM wallets").fetchone()[0] == ROOT
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM funding_reports").fetchone()[0] == 0


def test_queue_idempotence_cooldown_and_capacity(store, monkeypatch):
    assert queue(store, ROOT, 1000) == ("queued", True)
    assert queue(store, ROOT, 1001) == ("queued", False)
    complete(store, monkeypatch, ROOT, [edge()])
    assert queue(store, ROOT, 1100) == ("cooldown", False)
    assert queue(store, ROOT, 1600) == ("queued", True)
    for number in range(9):
        assert queue(store, "0x" + f"{number:040x}", 1600)[1]
    assert queue(store, PEER, 1600) == ("busy", False)


def test_report_exact_totals_and_root_only(store, monkeypatch):
    complete(
        store,
        monkeypatch,
        ROOT,
        [edge(), edge(number=2), edge(receiver=PEER, depth=1, number=3)],
    )
    report = read_report(store, ROOT)
    assert report["summary"][0]["amount"] == "2.469135780246913578"
    assert report["summary"][0]["transfers"] == 2
    assert len(report["edges"]) == 3
    assert report["limitations"]


def test_failed_refresh_preserves_previous_evidence(store, monkeypatch):
    complete(store, monkeypatch, ROOT, [edge()])
    prior = read_report(store, ROOT)["checked_at"]
    complete(store, monkeypatch, ROOT, [], status="partial", now=2000)
    report = read_report(store, ROOT)
    assert report["status"] == "partial"
    assert len(report["edges"]) == 1
    assert report["previous_evidence_retained"]
    assert report["previous_evidence_checked_at"] == prior


def test_partial_refresh_merges_new_edges_without_losing_prior_tokens(
    store, monkeypatch
):
    complete(store, monkeypatch, ROOT, [edge()])
    complete(
        store,
        monkeypatch,
        ROOT,
        [edge(contract=None, number=2)],
        status="partial",
        now=2000,
    )
    report = read_report(store, ROOT)
    assert len(report["edges"]) == 2
    assert any(
        item["contract"] == TOKEN and item["retained_from_previous"]
        for item in report["edges"]
    )
    assert any(
        item["contract"] is None and not item["retained_from_previous"]
        for item in report["edges"]
    )
    assert report["previous_evidence_retained"]


def test_investigation_never_overwrites_legacy_funding_hint(store, monkeypatch):
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO wallets(address,funding_source) VALUES(?,'Legacy value')",
            (ROOT,),
        )
    complete(store, monkeypatch, ROOT, [edge(sender=next(iter(INFRASTRUCTURE)))])
    with store.connection() as conn:
        assert (
            conn.execute(
                "SELECT funding_source FROM wallets WHERE address=?", (ROOT,)
            ).fetchone()[0]
            == "Legacy value"
        )


def test_global_budget_counts_refreshes_not_just_addresses(store, monkeypatch):
    complete(store, monkeypatch, ROOT, [])
    with store.connection() as conn:
        conn.executemany(
            "INSERT INTO funding_requests(address,requested_at) VALUES(?,?)",
            [(ROOT, 2000)] * 29,
        )
    assert queue(store, ROOT, 3000) == ("daily_limit", False)
    assert queue(store, PEER, 3000) == ("daily_limit", False)


def test_transaction_rollback_preserves_prior_report(store, monkeypatch):
    complete(store, monkeypatch, ROOT, [edge()])
    queue(store, ROOT, 2000)
    monkeypatch.setattr(
        "polysentinel.funding.investigation",
        lambda *args: {"status": "complete", "edges": [{"sender": SENDER}]},
    )
    with pytest.raises(KeyError):
        process_one(store, object(), 2000)
    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM funding_edges").fetchone()[0] == 1
        assert (
            json.loads(
                conn.execute("SELECT report FROM funding_reports").fetchone()[0]
            )["status"]
            == "complete"
        )


def test_stale_worker_cannot_overwrite_new_generation(store, monkeypatch):
    queue(store, ROOT, 1000)

    def lookup(*args):
        with store.connection() as conn:
            conn.execute(
                "UPDATE funding_reports SET status='queued',generation=generation+1 WHERE address=?",
                (ROOT,),
            )
        return {"status": "complete", "edges": [edge()]}

    monkeypatch.setattr("polysentinel.funding.investigation", lookup)
    assert process_one(store, object(), 1000)
    report = read_report(store, ROOT)
    assert report["status"] == "queued"
    assert report["edges"] == []


def test_expired_job_is_recovered(store, monkeypatch):
    queue(store, ROOT, 1000)
    with store.connection() as conn:
        conn.execute("UPDATE funding_reports SET status='running',started_at=1000")
    monkeypatch.setattr(
        "polysentinel.funding.investigation",
        lambda *args: {"status": "complete", "edges": [], "warnings": []},
    )
    assert process_one(store, object(), 1601)
    assert read_report(store, ROOT)["status"] == "complete"


def test_shared_funder_and_destination_require_same_token_and_root_observations(
    store, monkeypatch
):
    complete(
        store, monkeypatch, ROOT, [edge(), edge(sender=ROOT, receiver=SENDER, number=2)]
    )
    complete(
        store,
        monkeypatch,
        PEER,
        [edge(receiver=PEER, number=3), edge(sender=PEER, receiver=SENDER, number=4)],
    )
    signals = read_report(store, ROOT)["relationships"]
    assert {signal["type"] for signal in signals} == {
        "shared_funder",
        "shared_destination",
    }
    assert all(
        signal["wallet"] == PEER and signal["root_transactions"] for signal in signals
    )


@pytest.mark.parametrize(
    "mode", ["native", "different_token", "infrastructure", "upstream_only"]
)
def test_shared_infrastructure_gas_and_unrelated_assets_do_not_cluster(
    store, monkeypatch, mode
):
    sender = next(iter(INFRASTRUCTURE)) if mode == "infrastructure" else SENDER
    contract = None if mode == "native" else TOKEN
    complete(store, monkeypatch, ROOT, [edge(sender=sender, contract=contract)])
    complete(
        store,
        monkeypatch,
        PEER,
        [
            edge(
                sender=sender,
                receiver=PEER,
                contract="0x" + "e" * 40 if mode == "different_token" else contract,
                depth=1 if mode == "upstream_only" else 0,
                number=2,
            )
        ],
    )
    assert read_report(store, ROOT)["relationships"] == []


def test_api_validation_key_requirement_origin_queue_and_export(store):
    settings = replace(Settings(), database=store.path, etherscan_key="")
    client = create_app(settings, store).test_client()
    for route in ("/funding", "/transfers"):
        response = client.get(route)
        assert response.status_code == 200
        assert "Transfer explorer" in response.get_data(as_text=True)
        assert "Funding provenance" not in response.get_data(as_text=True)
    assert client.get("/api/funding/bad").status_code == 400
    assert client.post("/api/funding/" + ROOT, json={}).status_code == 503
    assert client.get("/api/funding/" + ROOT).json["configured"] is False
    settings = replace(settings, etherscan_key="DO-NOT-EXPOSE")
    client = create_app(settings, store).test_client()
    assert (
        client.post(
            "/api/funding/" + ROOT, json={}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.post("/api/funding/" + ROOT, data="{}").status_code == 403
    assert (
        client.post(
            "/api/funding/" + ROOT, json={}, base_url="http://evil.example"
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/funding/" + ROOT, json={}, headers={"Origin": "https://localhost"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/funding/" + ROOT,
            json={},
            headers={"Host": "localhost"},
            environ_overrides={"REMOTE_ADDR": "203.0.113.1"},
        ).status_code
        == 403
    )
    assert client.post("/api/funding/" + ROOT, json={}).status_code == 202
    response = client.get("/api/funding/" + ROOT + "?download=1")
    assert "attachment" in response.headers["Content-Disposition"]
    assert "DO-NOT-EXPOSE" not in response.get_data(as_text=True)


def test_behavior_requires_multiple_markets_and_three_root_trades(store):
    now = int(time.time())
    with store.connection() as conn:
        for wallet in (ROOT, PEER):
            conn.execute("INSERT INTO wallets(address) VALUES(?)", (wallet,))
            for number in range(3):
                conn.execute(
                    """INSERT INTO trades(trade_id,whale_address,timestamp,condition_id,market_question,category,side,outcome,position,size_usd,bet_link,tx_hash)
                    VALUES(?,?,?,?,?,'Politics','BUY','Yes','BUY Yes',1500,'#',?)""",
                    (
                        wallet + str(number),
                        wallet,
                        now - 1000 + number * 250,
                        str(number % 2),
                        "Test",
                        "0x" + f"{number:064x}",
                    ),
                )
        signals, truncated = behavior(conn, ROOT, now)
        assert len(signals) == 1
        assert signals[0]["matching_trades"] == 3 and signals[0]["markets"] == 2
        assert not truncated
        conn.execute("UPDATE trades SET condition_id='one'")
        assert behavior(conn, ROOT, now)[0] == []
