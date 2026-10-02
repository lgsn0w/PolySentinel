from dataclasses import replace
import json
import time
from types import SimpleNamespace

import pytest

from polysentinel.classification import (
    classify_saved,
    process_classification,
    queue_classification,
)
from polysentinel.config import Settings
from polysentinel.funding import queue, read_report
from polysentinel.receipts import PUSD, TRANSFER_TOPIC, ORDER_FILLED_V2_TOPIC
from polysentinel.storage import Store
from polysentinel.web import create_app

ROOT = "0x" + "a" * 40
SENDER = "0x" + "b" * 40
TX = "0x" + "c" * 64
BLOCK = "0x" + "d" * 64
EXCHANGE = "0xe111180000d2663c0091e4f400237545b87b996b"


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "classification.sqlite3")


def address_topic(address):
    return "0x" + "0" * 24 + address[2:]


def transfer(index=1, raw=1_250_000):
    return {
        "address": PUSD,
        "topics": [TRANSFER_TOPIC, address_topic(SENDER), address_topic(ROOT)],
        "data": "0x" + f"{raw:064x}",
        "transactionHash": TX,
        "blockHash": BLOCK,
        "logIndex": hex(index),
        "removed": False,
    }


def receipt(logs=None, tx_hash=TX):
    return {
        "result": {
            "transactionHash": tx_hash,
            "blockHash": BLOCK,
            "blockNumber": "0x100",
            "status": "0x1",
            "from": SENDER,
            "to": PUSD,
            "logs": logs if logs is not None else [transfer()],
        }
    }


def edge(number=1, amount="1.25", tx_hash=TX):
    return {
        "id": str(number),
        "sender": SENDER,
        "receiver": ROOT,
        "contract": PUSD,
        "amount": amount,
        "asset": "pUSD",
        "timestamp": int(time.time()) - 100,
        "hash": tx_hash,
        "kind": "erc20",
        "depth": 0,
        "identity_ambiguous": True,
        "ancestry": True,
    }


def seed(store, edges=None):
    edges = edges or [edge()]
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO funding_reports(address,status,requested_at) VALUES(?,'partial',1000)",
            (ROOT,),
        )
        for item in edges:
            conn.execute(
                "INSERT INTO funding_edges VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ROOT,
                    item["id"],
                    item["sender"],
                    item["receiver"],
                    item["contract"],
                    item["amount"],
                    item["timestamp"],
                    item["hash"],
                    item["kind"],
                    item["depth"],
                    json.dumps(item),
                ),
            )


def client(payload=None):
    return SimpleNamespace(
        settings=SimpleNamespace(etherscan_key="NOT-TO-EXPOSE"),
        get=lambda url, params: receipt() if payload is None else payload,
    )


def test_classification_queue_requires_evidence_and_is_idempotent(store):
    assert queue_classification(store, ROOT, 1000) == ("no_evidence", False)
    seed(store)
    assert queue_classification(store, ROOT, 1000) == ("queued", True)
    assert queue_classification(store, ROOT, 1001) == ("queued", False)
    assert process_classification(store, client(), now=1001)
    assert queue_classification(store, ROOT, 1100) == ("cooldown", False)


def test_classification_verifies_and_canonicalizes_duplicate_api_rows(store):
    seed(store, [edge(), edge(2)])
    queue_classification(store, ROOT)
    assert process_classification(store, client())
    report = read_report(store, ROOT)
    assert len(report["edges"]) == 1
    assert report["edges"][0]["id"] == f"137:{TX}:1"
    assert report["edges"][0]["classification"]["category"] == "direct_transfer"
    assert report["summary"][0]["amount"] == "1.25"
    assert not report["summary"][0]["identity_ambiguous"]
    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM funding_edges").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM receipt_cache").fetchone()[0] == 1


def test_identical_real_transfer_logs_are_not_collapsed(store):
    seed(store, [edge(), edge(2)])
    queue_classification(store, ROOT)
    process_classification(store, client(receipt([transfer(1), transfer(2)])))
    report = read_report(store, ROOT)
    assert len(report["edges"]) == 2
    assert {item["id"] for item in report["edges"]} == {f"137:{TX}:1", f"137:{TX}:2"}
    assert report["summary"][0]["amount"] == "2.50"
    assert all(
        item["classification"]["category"] == "unknown" for item in report["edges"]
    )


def test_cache_avoids_repeated_upstream_requests(store):
    seed(store)
    queue_classification(store, ROOT, 1000)
    process_classification(store, client())
    with store.connection() as conn:
        conn.execute("UPDATE classification_jobs SET status='queued'")
    probe = SimpleNamespace(
        settings=SimpleNamespace(etherscan_key="key"),
        get=lambda *args: pytest.fail("cache missed"),
    )
    process_classification(store, probe)
    report = read_report(store, ROOT)
    assert report["classification"]["requests"] == 0
    assert report["classification"]["verified_receipts"] == 1


def test_wrong_receipt_identity_never_classifies_as_a_deposit(store):
    seed(store)
    queue_classification(store, ROOT)
    process_classification(store, client(receipt(tx_hash="0x" + "e" * 64)))
    report = read_report(store, ROOT)
    assert report["classification"]["status"] == "partial"
    assert report["edges"][0]["classification"]["category"] == "unknown"
    assert report["classification"]["direct_transfers"] == []


def test_request_budget_stops_and_reports_unclassified_transactions(store):
    seed(store, [edge(), edge(2, tx_hash="0x" + "e" * 64)])
    queue_classification(store, ROOT)
    process_classification(store, client(), max_requests=1)
    report = read_report(store, ROOT)
    assert report["classification"]["requests"] == 1
    assert report["classification"]["skipped_receipts"] == 1
    assert report["classification"]["status"] == "partial"


def test_stale_worker_cannot_commit_receipt_cache_or_job_result(store):
    seed(store)
    queue_classification(store, ROOT)

    def get(*args):
        with store.connection() as conn:
            conn.execute(
                "UPDATE classification_jobs SET status='queued',generation=generation+1"
            )
        return receipt()

    probe = SimpleNamespace(settings=SimpleNamespace(etherscan_key="key"), get=get)
    process_classification(store, probe)
    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM receipt_cache").fetchone()[0] == 0
        assert (
            conn.execute("SELECT status FROM classification_jobs").fetchone()[0]
            == "queued"
        )


def test_failed_lookup_preserves_old_verified_receipt_but_marks_stale(store):
    seed(store)
    queue_classification(store, ROOT)
    process_classification(store, client())
    with store.connection() as conn:
        conn.execute(
            "UPDATE receipt_cache SET checked_at=?", (int(time.time()) - 7200,)
        )
        conn.execute("UPDATE classification_jobs SET status='queued'")
    process_classification(store, client({"error": "unavailable"}))
    report = read_report(store, ROOT)
    assert report["edges"][0]["receipt_stale"]
    assert report["classification"]["status"] == "partial"
    assert report["edges"][0]["classification"]["receipt_verified"]


def test_valid_failed_receipt_invalidates_previous_success_after_reorg(store):
    seed(store)
    queue_classification(store, ROOT)
    process_classification(store, client())
    with store.connection() as conn:
        conn.execute(
            "UPDATE receipt_cache SET checked_at=?", (int(time.time()) - 7200,)
        )
        conn.execute("UPDATE classification_jobs SET status='queued'")
    payload = receipt(logs=[])
    payload["result"]["status"] = "0x0"
    payload["result"]["blockHash"] = "0x" + "e" * 64
    process_classification(store, client(payload))
    report = read_report(store, ROOT)
    assert report["classification"]["failed_execution_receipts"] == 1
    assert report["classification"]["direct_transfers"] == []
    assert report["edges"][0]["classification"]["category"] == "unknown"
    assert not report["edges"][0]["classification"]["receipt_verified"]
    assert (
        report["edges"][0]["classification"]["reason"] == "transaction execution failed"
    )
    with store.connection() as conn:
        assert (
            conn.execute("SELECT status FROM receipt_cache").fetchone()[0] == "failed"
        )


def test_classification_api_uses_existing_local_json_guard_and_budget(store):
    settings = replace(Settings(), database=store.path, etherscan_key="NOT-TO-EXPOSE")
    app = create_app(settings, store).test_client()
    url = "/api/funding/" + ROOT
    assert app.post(url, json={"action": "classify"}).status_code == 409
    seed(store)
    assert (
        app.post(
            url,
            json={"action": "classify"},
            environ_overrides={"REMOTE_ADDR": "203.0.113.1"},
        ).status_code
        == 403
    )
    assert app.post(url, json={"action": "evil"}).status_code == 400
    assert app.post(url, json=["classify"]).status_code == 400
    assert app.post(url, json={"action": "classify"}).status_code == 202
    assert "NOT-TO-EXPOSE" not in app.get(url).get_data(as_text=True)


def test_classification_and_exploration_share_pending_capacity(store):
    seed(store)
    queue_classification(store, ROOT, 1000)
    for number in range(9):
        assert queue(store, "0x" + f"{number:040x}", 1000)[1]
    assert queue(store, SENDER, 1000) == ("busy", False)
