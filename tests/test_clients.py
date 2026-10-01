from dataclasses import replace

import pytest
import requests

from polysentinel.clients import Client, UpstreamError
from polysentinel.config import Settings


def test_paginated_trades_use_stable_cursors_and_keep_filters():
    client = Client(replace(Settings(), page_size=2))
    calls = []
    def get(url, params):
        calls.append(params)
        assert url.endswith("/v2/trades")
        assert "offset" not in params and "start" not in params
        if "cursor" not in params:
            return {"data": [{"timestamp": 110}, {"timestamp": 109}],
                    "pagination": {"next_cursor": "next", "has_more": True}}
        assert params["cursor"] == "next"
        return {"data": [{"timestamp": 108}, {"timestamp": 99}],
                "pagination": {"next_cursor": "last", "has_more": True}}
    client.get = get
    result = client.trades_since(100)
    assert {r["timestamp"] for r in result} == {108, 109, 110}
    assert len(calls) == 2
    assert all(p["filter_type"] == "CASH" and p["filter_amount"] == 10 for p in calls)


def test_same_second_trades_span_cursor_pages():
    client = Client(replace(Settings(), page_size=2))
    def get(url, params):
        if "cursor" not in params:
            return {"data": [{"timestamp": 100, "transaction_hash": "one"},
                             {"timestamp": 100, "transaction_hash": "two"}],
                    "pagination": {"next_cursor": "next", "has_more": True}}
        return {"data": [{"timestamp": 100, "transaction_hash": "three"}],
                "pagination": {"next_cursor": None, "has_more": False}}
    client.get = get
    assert {r["transactionHash"] for r in client.trades_since(100)} == {"one", "two", "three"}


def test_repeated_trade_cursor_fails_closed():
    client = Client(Settings())
    client.get = lambda url, params: {"data": [{"timestamp": 100}],
                                     "pagination": {"next_cursor": "same", "has_more": True}}
    with pytest.raises(UpstreamError, match="repeated"):
        client.trades_since(100)


@pytest.mark.parametrize("payload", [{"error": "limit"}, [{"timestamp": "broken"}], [{"timestamp": 99}]])
def test_malformed_trade_response_fails_closed(payload):
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
        assert url.endswith("/events/keyset")
        assert "offset" not in params
        calls.append(params.get("after_cursor"))
        if "after_cursor" not in params:
            return {"events": [{"tags": [{"slug": None}], "markets": []}] * 100,
                    "next_cursor": "next"}
        return {"events": [{"tags": [{"slug": "politics"}], "slug": "event", "markets": [
            {"conditionId": "cid", "question": "Question"}]}]}
    client.get = get
    assert client.markets()["cid"]["question"] == "Question"
    assert calls == [None, "next", None, "next"]


def test_market_map_failure_does_not_allow_empty_monitoring():
    client = Client(Settings())
    client.get = lambda url, params: {"events": []}
    with pytest.raises(UpstreamError, match="No political"):
        client.markets()


def test_market_keyset_repeated_cursor_fails_closed():
    client = Client(Settings())
    client.get = lambda url, params: {"events": [], "next_cursor": "repeated"}
    with pytest.raises(UpstreamError, match="repeated"):
        client.markets()


@pytest.mark.parametrize("cursor", [0, [], ""])
def test_market_falsy_cursor_fails_closed(cursor):
    client = Client(Settings())
    client.get = lambda url, params: {"events": [], "next_cursor": cursor}
    with pytest.raises(UpstreamError, match="cursor"):
        client.markets()


def test_v2_trade_aliases_match_ingestion_contract():
    client = Client(Settings())
    client.get = lambda url, params: {"data": [{"timestamp": 100, "proxy_wallet": "wallet",
        "condition_id": "condition", "token_id": "token", "transaction_hash": "tx"}],
        "pagination": {"next_cursor": None, "has_more": False}}
    row = client.trades_since(100)[0]
    assert (row["proxyWallet"],row["conditionId"],row["asset"],row["transactionHash"]) == ("wallet","condition","token","tx")


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
