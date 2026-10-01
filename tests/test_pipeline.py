from dataclasses import replace
import sqlite3
import time

import pytest

from polysentinel.config import Settings
from polysentinel.scanner import WhaleSentinel
from polysentinel.storage import Store
from polysentinel.web import create_app

WALLET = "0x" + "a" * 40
MARKET = {"question": "Test market", "category": "Politics", "link": "https://polymarket.com/event/test"}


def trade(number=1, ts=1000, usd=1500, **extra):
    return {"proxyWallet": WALLET, "timestamp": ts, "size": usd * 2, "price": .5,
            "side": "BUY", "outcome": "Yes", "conditionId": "cid", "asset": "asset",
            "transactionHash": f"tx{number}", **extra}


@pytest.fixture
def scanner(tmp_path):
    settings = replace(Settings(), database=str(tmp_path / "sentinel.sqlite3"))
    scanner = WhaleSentinel(settings)
    scanner.market_cache = {"cid": MARKET}
    scanner.market_refresh = time.time()
    return scanner


def rows(scanner):
    with scanner.store.connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM trades ORDER BY timestamp,trade_id")]


def test_replay_timestamp_ties_and_restart(scanner):
    batch = [trade(1), trade(2)]
    assert scanner.ingest(batch, 1100) == 2
    assert scanner.ingest(batch, 1100) == 0
    restored = WhaleSentinel(scanner.settings)
    restored.market_cache = scanner.market_cache
    assert restored.ingest(batch + [trade(3)], 1100) == 1
    assert len(rows(restored)) == 3
    assert restored.store.state()["cursor"] == 1000
    assert sum(r["size_usd"] for r in rows(restored)) == 4500


def test_same_transaction_distinct_fills(scanner):
    assert scanner.ingest([trade(asset="one"), trade(asset="two"), trade(usd=1600)], 1100) == 3


def test_documented_unlabeled_outcome_does_not_block_batch(scanner):
    scanner.ingest([trade(1), trade(2, outcome="", outcome_index=999)], 1100)
    assert len(rows(scanner)) == 2
    assert any(row["position"] == "BUY Unlabeled outcome" for row in rows(scanner))
    assert scanner.store.state()["last_success"] == 1100


def test_unlabeled_tokens_do_not_accumulate_together(scanner):
    scanner.ingest([trade(1, asset="one", outcome="", outcome_index=999),
                    trade(2, asset="two", outcome="", outcome_index=999)], 1100)
    assert not any(row["flagged"] for row in rows(scanner))


def test_trade_persisted_before_alert_and_survives_restart(scanner):
    scanner.ingest([trade()], 1100)
    assert rows(scanner)[0]["flagged"] == 0
    restored = WhaleSentinel(scanner.settings)
    restored.market_cache = scanner.market_cache
    restored.ingest([trade(2, ts=1100)], 1200)
    assert all(r["flagged"] == 1 for r in rows(restored))


def test_sliding_window_does_not_extend_on_activity(scanner):
    scanner.ingest([trade(1, ts=1000, usd=1000), trade(2, ts=1500, usd=1000),
                    trade(3, ts=2000, usd=1000)], 2100)
    assert not any(r["flagged"] for r in rows(scanner))


def test_window_boundary_and_late_trade(scanner):
    scanner.ingest([trade(1, ts=1600)], 1700)
    scanner.ingest([trade(2, ts=1000)], 1700)
    assert all(r["flagged"] for r in rows(scanner))


def test_different_sides_and_markets_do_not_accumulate(scanner):
    scanner.market_cache["cid2"] = MARKET
    scanner.ingest([trade(1), trade(2, side="SELL"), trade(3, conditionId="cid2")], 1100)
    assert not any(r["flagged"] for r in rows(scanner))


def test_write_failure_rolls_back_trade_and_progress(scanner):
    with scanner.store.connection() as conn:
        conn.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON trades BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        scanner.ingest([trade()], 1100)
    assert rows(scanner) == []
    assert scanner.store.state()["cursor"] == 0
    with scanner.store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wallets").fetchone()[0] == 0
        conn.execute("DROP TRIGGER fail_insert")
    assert scanner.ingest([trade()], 1100) == 1


@pytest.mark.parametrize("extra", [{"price": float("nan")}, {"size": -1}, {"proxyWallet": "bad"},
                                   {"side": "invalid"}, {"price": 2}, {"asset": None},
                                   {"outcome": None}, {"transactionHash": None},
                                   {"outcome": None, "outcome_index": 999},
                                   {"outcome": "   ", "outcome_index": 999}])
def test_invalid_batch_does_not_advance_progress(scanner, extra):
    with pytest.raises(ValueError):
        scanner.ingest([trade(1), trade(2, **extra)], 1100)
    assert rows(scanner) == []
    assert scanner.store.state()["cursor"] == 0


def test_enrichment_failure_retains_previous_values(scanner):
    scanner.ingest([trade(usd=5000)], 1100)
    with scanner.store.connection() as conn:
        conn.execute("UPDATE wallets SET funding_source='Known',portfolio_value=50")
    class EmptyClient:
        def wallet_intel(self, wallet):
            return {}
    assert scanner.enrich_once(EmptyClient())
    with scanner.store.connection() as conn:
        row = conn.execute("SELECT * FROM wallets").fetchone()
        assert row["portfolio_value"] == 50
        assert row["funding_source"] == "Known"


def test_api_chart_sentiment_and_volume(scanner):
    now = int(time.time())
    scanner.ingest([trade(1, ts=now, usd=5000), trade(2, ts=now, usd=100, side="SELL"),
                    trade(3, ts=now, usd=100, outcome="No", side="SELL"),
                    trade(4, ts=now, usd=100, outcome="Candidate")], now)
    client = create_app(store=scanner.store).test_client()
    data = client.get("/api/stats").get_json()
    assert len(data["velocity_chart"]) == len(data["velocity_timestamps"]) == 48
    assert data["velocity_timestamps"][-1] - data["velocity_timestamps"][0] == 47 * 1800
    assert sum(data["velocity_chart"]) == 5300
    assert data["sentiment"]["bulls"] == 2
    assert data["sentiment"]["bears"] == 1
    assert data["volume_chart"] == {"whale": 5000, "retail": 300}
    roster = client.get("/api/insider_data").get_json()["roster"]
    assert len(roster) == 1
    assert roster[0]["total_scanned_volume"] == 5000
    assert len(client.get(f"/api/whale/{WALLET}").get_json()["history"]) == 1
    assert client.get("/api/whale/invalid").status_code == 400


def test_empty_database_pages_and_health(scanner):
    client = create_app(store=scanner.store).test_client()
    for route in ("/", "/insider", "/about", "/dev", "/disclaimer", "/documentation"):
        assert client.get(route).status_code == 200
    assert client.get("/api/stats").get_json()["feed"] == []
    assert client.get("/api/insider_data").get_json()["roster"] == []
    assert client.get("/healthz").get_json()["scanner"]["fresh"] is False


def test_database_error_is_not_empty_success(scanner, monkeypatch):
    client = create_app(store=scanner.store).test_client()
    def fail():
        raise sqlite3.OperationalError("private database path")
    monkeypatch.setattr(scanner.store, "connection", fail)
    response = client.get("/api/stats")
    assert response.status_code == 503
    assert "private" not in response.get_data(as_text=True)


def test_poll_uses_durable_cursor_with_overlap(scanner):
    scanner.ingest([trade(ts=1000)], 1100)
    class FakeClient:
        def trades_since(self, since):
            assert since == 880
            return [trade(ts=1000), trade(2, ts=1000)]
    restored = WhaleSentinel(scanner.settings, client=FakeClient())
    restored.market_cache = scanner.market_cache
    restored.market_refresh = time.time()
    assert restored.poll_once() == 1


def test_unknown_market_survives_until_classified_after_overlap(scanner):
    assert scanner.ingest([trade(conditionId="new")], 1100) == 0
    assert scanner.store.state()["cursor"] == 1000
    restored = WhaleSentinel(scanner.settings)
    restored.market_cache = {"new": MARKET}
    assert restored.ingest([], 5000) == 1
    assert rows(restored)[0]["condition_id"] == "new"
    with restored.store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pending_trades").fetchone()[0] == 0


def test_pending_market_classified_nonpolitical_is_excluded(scanner):
    scanner.ingest([trade(conditionId="sports")], 1100)
    scanner.market_cache["sports"] = None
    scanner.ingest([], 5000)
    assert rows(scanner) == []
    with scanner.store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pending_trades").fetchone()[0] == 0


def test_closed_market_pending_is_resolved_by_targeted_lookup(scanner):
    scanner.ingest([trade(conditionId="closed")], 1100)
    class FakeClient:
        def trades_since(self, since):
            return []
        def conditions(self, ids):
            assert ids == ["closed"]
            return {"closed": MARKET}
    scanner.client = FakeClient()
    assert scanner.poll_once() == 1
    assert rows(scanner)[0]["condition_id"] == "closed"


def test_failed_classification_is_durable(scanner):
    class FakeClient:
        def trades_since(self, since):
            return [trade(conditionId="unknown")]
        def conditions(self, ids):
            raise RuntimeError("not available")
    scanner.client = FakeClient()
    assert scanner.poll_once() == 0
    with scanner.store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pending_trades").fetchone()[0] == 1


def test_insider_response_includes_freshness_contract(scanner):
    now = int(time.time())
    scanner.ingest([], now)
    client = create_app(store=scanner.store).test_client()
    data = client.get("/api/insider_data").get_json()
    assert data["timestamp"] >= now * 1000
    assert data["scanner"]["status"] == "ok"
    assert data["scanner"]["last_success"] == now


def test_unsupported_schema_is_preserved(tmp_path):
    path = tmp_path / "future.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version=99")
    conn.close()
    with pytest.raises(RuntimeError):
        Store(path)
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 99
    conn.close()
