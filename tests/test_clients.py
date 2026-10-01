from dataclasses import replace

import pytest
import requests

from polysentinel.clients import Client, UpstreamError
from polysentinel.config import Settings


def test_paginated_trades_have_frozen_windows(monkeypatch):
    monkeypatch.setattr("polysentinel.clients.time.time", lambda: 110)
    client = Client(replace(Settings(), page_size=2, max_offset=5))
    calls = []
    def get(url, params):
        calls.append(params)
        data = [{"timestamp": 110}, {"timestamp": 109}, {"timestamp": 108}]
        return data[params["offset"]:params["offset"] + params["limit"]]
    client.get = get
    result = client.trades_since(100)
    assert {r["timestamp"] for r in result} == {108, 109, 110}
    assert len(calls) == 3
    assert all(p["start"] == 100 and p["end"] == 110 for p in calls)


def test_busy_windows_split_before_progress(monkeypatch):
    monkeypatch.setattr("polysentinel.clients.time.time", lambda: 102)
    client = Client(replace(Settings(), page_size=2, max_offset=0))
    def get(url, params):
        data = [{"timestamp": ts} for ts in (102, 101, 100) if params["start"] <= ts <= params["end"]]
        return data[:params["limit"]]
    client.get = get
    assert {r["timestamp"] for r in client.trades_since(100)} == {100, 101, 102}


def test_unsplittable_second_raises(monkeypatch):
    monkeypatch.setattr("polysentinel.clients.time.time", lambda: 100)
    client = Client(replace(Settings(), page_size=2, max_offset=0))
    client.get = lambda url, params: [{"timestamp": 100}] * 2
    with pytest.raises(UpstreamError, match="one second"):
        client.trades_since(100)


@pytest.mark.parametrize("payload", [{"error": "limit"}, [{"timestamp": "broken"}], [{"timestamp": 99}]])
def test_malformed_trade_response_fails_closed(payload, monkeypatch):
    monkeypatch.setattr("polysentinel.clients.time.time", lambda: 110)
    client = Client(Settings())
    client.get = lambda url, params: payload
    with pytest.raises(UpstreamError):
        client.trades_since(100)


def test_portfolio_list_and_profile_contract():
    client = Client(Settings())
    def get(url, params):
        if url.endswith("/public-profile"):
            assert params == {"address": "wallet"}
            return {"createdAt": "2024-01-01T00:00:00Z"}
        return [{"user": "wallet", "value": 123.5}]
    client.get = get
    result = client.wallet_intel("wallet")
    assert result["portfolio_value"] == 123.5
    assert result["account_created_ts"] == 1704067200


def test_http_errors_do_not_leak_api_keys():
    class Session:
        def get(self, *args, **kwargs):
            raise requests.ConnectionError("https://service/?apikey=secret")
    client = Client(Settings(), Session())
    with pytest.raises(UpstreamError) as error:
        client.get("url")
    assert "secret" not in str(error.value)
    assert error.value.__suppress_context__


def test_market_pagination_and_missing_tag_slugs():
    client = Client(Settings())
    calls = []
    def get(url, params):
        calls.append(params["offset"])
        if params["offset"] == 0:
            return [{"tags": [{"slug": None}], "markets": []}] * 100
        return [{"tags": [{"slug": "politics"}], "slug": "event", "markets": [
            {"conditionId": "cid", "question": "Question"}]}]
    client.get = get
    assert client.markets()["cid"]["question"] == "Question"
    assert calls == [0, 100]


def test_market_map_failure_does_not_allow_empty_monitoring():
    client = Client(Settings())
    client.get = lambda url, params: []
    with pytest.raises(UpstreamError, match="No political"):
        client.markets()


def test_targeted_conditions_include_closed_political_markets():
    client = Client(Settings())
    calls = []
    def get(url, params):
        calls.append(params)
        assert params["condition_ids"] == ["closed", "sport"]
        if params["closed"] == "false":
            return [{"conditionId": "sport", "tags": [{"slug": "sport"}]}]
        return [{"conditionId": "closed", "closed": True, "question": "Closed market",
                 "events": [{"slug": "closed-event", "tags": [{"slug": "politics"}]}]}]
    client.get = get
    result = client.conditions(["closed", "sport"])
    assert result["sport"] is None
    assert result["closed"]["question"] == "Closed market"
    assert result["closed"]["link"].endswith("/closed-event")
    assert {p["closed"] for p in calls} == {"true", "false"}


def test_missing_condition_tags_are_not_classified_nonpolitical():
    client = Client(Settings())
    client.get = lambda url, params: [{"conditionId": "cid"}]
    assert client.conditions(["cid"]) == {}
