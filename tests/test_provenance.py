from types import SimpleNamespace

import pytest

from polysentinel.clients import UpstreamError
from polysentinel.provenance import (
    CONTRACT_SOURCE,
    investigation,
    verified_infrastructure,
)

ROOT = "0x" + "1" * 40
FUNDER = "0x" + "2" * 40
OLDER = "0x" + "3" * 40
OTHER = "0x" + "4" * 40
TOKEN = "0x" + "5" * 40
HASH = "0x" + "a" * 64
HASH2 = "0x" + "b" * 64


class FakeClient:
    def __init__(self, get, key="key"):
        self.settings = SimpleNamespace(etherscan_key=key)
        self.get = get


def empty():
    return {
        "status": "0",
        "message": "No transactions found",
        "result": "No transactions found",
    }


def native(
    sender=FUNDER,
    receiver=ROOT,
    value="1000000000000000000",
    timestamp="100",
    tx_hash=HASH,
):
    return {
        "from": sender,
        "to": receiver,
        "value": value,
        "timeStamp": timestamp,
        "hash": tx_hash,
        "isError": "0",
        "txreceipt_status": "1",
    }


def token(
    sender=FUNDER,
    receiver=ROOT,
    value="1234500",
    decimals="6",
    timestamp="100",
    contract=TOKEN,
    tx_hash=HASH,
    log_index=None,
):
    return {
        "from": sender,
        "to": receiver,
        "value": value,
        "tokenDecimal": decimals,
        "tokenSymbol": "USDC",
        "contractAddress": contract,
        "timeStamp": timestamp,
        "hash": tx_hash,
        "isError": "0",
        "transactionIndex": "7",
        "logIndex": log_index,
    }


def test_no_key_and_input_validation_do_not_call_upstream():
    client = FakeClient(lambda url, params: pytest.fail("unexpected request"), key="")
    assert investigation(client, ROOT)["status"] == "no_key"
    with pytest.raises(ValueError, match="address"):
        investigation(client, "broken")
    with pytest.raises(ValueError, match="limits"):
        investigation(FakeClient(lambda url, params: empty()), ROOT, max_depth=True)


def test_reads_three_descending_paginated_streams_and_marks_page_limit():
    calls = []

    def get(url, params):
        calls.append(dict(params))
        if params["action"] == "txlist" and params["page"] == 1:
            return {"status": "1", "result": [native()]}
        return empty()

    report = investigation(FakeClient(get), ROOT, max_depth=1, page_size=1, max_pages=1)
    assert report["status"] == "partial"
    assert report["requests"] == 3
    assert {call["action"] for call in calls} == {"txlist", "txlistinternal", "tokentx"}
    assert all(call["sort"] == "desc" and call["chainid"] == 137 for call in calls)
    tx_coverage = next(
        item for item in report["coverage"] if item["action"] == "txlist"
    )
    assert tx_coverage["error"] == "page_limit" and not tx_coverage["complete"]


def test_exact_token_decimals_and_duplicate_transfer_events_survive():
    def get(url, params):
        if params["action"] == "tokentx":
            return {"status": "1", "result": [token(), token()]}
        return empty()

    report = investigation(FakeClient(get), ROOT, max_depth=1, page_size=10)
    transfers = [edge for edge in report["edges"] if edge["kind"] == "erc20"]
    assert [edge["amount"] for edge in transfers] == ["1.2345", "1.2345"]
    assert len({edge["event_id"] for edge in transfers}) == 2
    assert all(edge["id"] == edge["event_id"] for edge in transfers)
    assert all(
        edge["asset"] == "token:USDC" and edge["contract"] == TOKEN
        for edge in transfers
    )
    assert any("indexing is ambiguous" in warning for warning in report["warnings"])


def test_large_token_integer_is_not_rounded_by_decimal_context():
    exact = "123456789012345678901234567890123456789"

    def get(url, params):
        if params["action"] == "tokentx":
            return {"status": "1", "result": [token(value=exact, decimals="18")]}
        return empty()

    edge = investigation(FakeClient(get), ROOT, max_depth=1, page_size=10)["edges"][0]
    assert edge["amount"] == "123456789012345678901.234567890123456789"


def test_same_token_events_seen_from_both_endpoints_have_stable_ids():
    def get(url, params):
        if params["action"] == "tokentx" and params["address"] in (ROOT, FUNDER):
            return {"status": "1", "result": [token(), token()]}
        return empty()

    report = investigation(FakeClient(get), ROOT, max_depth=2, page_size=10)
    transfers = [edge for edge in report["edges"] if edge["kind"] == "erc20"]
    assert len(transfers) == 2
    assert len({edge["event_id"] for edge in transfers}) == 2


def test_filters_failed_zero_and_malformed_transfers_without_evidence():
    failed = native()
    failed["isError"] = "1"
    malformed = native(tx_hash="bad")
    unrelated = native(sender=OLDER, receiver=OTHER)
    rows = [failed, native(value="0"), malformed, unrelated]
    client = FakeClient(
        lambda url, params: (
            {"status": "1", "result": rows} if params["action"] == "txlist" else empty()
        )
    )
    report = investigation(client, ROOT, max_depth=1, page_size=10)
    assert report["edges"] == []
    assert report["status"] == "partial"
    assert report["coverage"][0]["invalid_rows"] == 3


def test_normal_internal_duplicate_is_collapsed_but_trace_is_preserved():
    internal_duplicate = native()
    traced = native(value="2000000000000000000")
    traced["traceId"] = "0_1"

    def get(url, params):
        if params["action"] == "txlist":
            return {"status": "1", "result": [native()]}
        if params["action"] == "txlistinternal":
            return {"status": "1", "result": [internal_duplicate, traced]}
        return empty()

    report = investigation(FakeClient(get), ROOT, max_depth=1, page_size=10)
    assert [(edge["kind"], edge["amount"]) for edge in report["edges"]] == [
        ("internal", "2"),
        ("native", "1"),
    ]


def test_request_budget_and_upstream_errors_are_explicit_partial_coverage():
    def get(url, params):
        if params["action"] == "txlist":
            raise UpstreamError("unavailable")
        return empty()

    report = investigation(FakeClient(get), ROOT, max_requests=2)
    assert report["status"] == "partial" and report["requests"] == 2
    assert [item["error"] for item in report["coverage"]] == [
        "upstream_error",
        None,
        "request_budget",
    ]


def test_unsupported_plan_status_is_not_reported_as_complete():
    client = FakeClient(
        lambda url, params: {
            "status": "0",
            "message": "NOTOK",
            "result": "This chainid is not supported by your plan",
        }
    )
    report = investigation(client, ROOT)
    assert report["status"] == "unsupported"
    assert all(item["error"] == "unsupported" for item in report["coverage"])


def test_temporal_boundary_blocks_future_ancestor_transfer():
    def get(url, params):
        if params["action"] != "tokentx":
            return empty()
        if params["address"] == ROOT:
            return {"status": "1", "result": [token(timestamp="100")]}
        if params["address"] == FUNDER:
            return {
                "status": "1",
                "result": [
                    token(
                        sender=OLDER, receiver=FUNDER, timestamp="101", tx_hash=HASH2
                    ),
                    token(
                        sender=OTHER,
                        receiver=FUNDER,
                        timestamp="99",
                        tx_hash="0x" + "c" * 64,
                    ),
                    token(
                        sender=OLDER,
                        receiver=FUNDER,
                        timestamp="98",
                        contract="0x" + "6" * 40,
                        tx_hash="0x" + "d" * 64,
                    ),
                ],
            }
        return empty()

    report = investigation(FakeClient(get), ROOT, max_depth=2, page_size=10)
    assert not any(edge["sender"] == OLDER for edge in report["edges"])
    assert any(
        edge["sender"] == OTHER and edge["depth"] == 1 for edge in report["edges"]
    )


def test_verified_and_sourced_infrastructure_is_never_traversed():
    contract = next(iter(verified_infrastructure()))
    calls = []

    def get(url, params):
        calls.append(params["address"])
        if params["address"] == ROOT and params["action"] == "tokentx":
            return {"status": "1", "result": [token(sender=contract)]}
        return empty()

    report = investigation(FakeClient(get), ROOT, max_depth=3, page_size=10)
    assert set(calls) == {ROOT}
    stopped = next(node for node in report["nodes"] if node["address"] == contract)
    assert stopped["stop_reason"] == "verified_infrastructure"
    assert verified_infrastructure()[contract]["source"] == CONTRACT_SOURCE


def test_sourced_injected_infrastructure_and_node_limit_are_honored():
    client = FakeClient(
        lambda url, params: (
            {
                "status": "1",
                "result": [token(sender=FUNDER), token(sender=OLDER, tx_hash=HASH2)],
            }
            if params["action"] == "tokentx" and params["address"] == ROOT
            else empty()
        )
    )
    client.provenance_labels = {
        FUNDER: {
            "label": "Custodian",
            "source": "https://example.test/proof",
            "infrastructure": True,
        },
        OLDER: {"label": "Unsourced", "infrastructure": True},
    }
    report = investigation(client, ROOT, max_nodes=1, page_size=10)
    assert report["status"] == "partial"
    assert len(report["nodes"]) == 1
    assert FUNDER in verified_infrastructure(
        client
    ) and OLDER not in verified_infrastructure(client)
    assert any("bounded recent sample" in warning for warning in report["warnings"])


def test_native_transfer_is_visible_at_root_but_never_traversed():
    calls = []

    def get(url, params):
        calls.append((params["address"], params["action"]))
        if params["address"] == ROOT and params["action"] == "txlist":
            return {"status": "1", "result": [native()]}
        return empty()

    report = investigation(FakeClient(get), ROOT, max_depth=3, page_size=10)
    assert any(edge["kind"] == "native" for edge in report["edges"])
    assert {address for address, action in calls} == {ROOT}
    assert len(report["nodes"]) == 1


def test_token_mint_and_burn_are_visible_but_not_traversed():
    zero = "0x" + "0" * 40

    def get(url, params):
        if params["action"] == "tokentx":
            return {
                "status": "1",
                "result": [
                    token(sender=zero, tx_hash=HASH),
                    token(sender=ROOT, receiver=zero, tx_hash=HASH2),
                ],
            }
        return empty()

    report = investigation(FakeClient(get), ROOT, max_depth=3, page_size=10)
    assert {edge["kind"] for edge in report["edges"]} == {"erc20_mint", "erc20_burn"}
    assert len(report["nodes"]) == 1


def test_future_zero_failed_and_nested_rows_make_coverage_partial():
    future = token(timestamp="9999999999")
    zero_time = token(timestamp="0", tx_hash=HASH2)
    failed = token(tx_hash="0x" + "c" * 64)
    failed["isError"] = "1"
    nested = token(tx_hash="0x" + "d" * 64)
    nested["from"] = [FUNDER]

    def get(url, params):
        return {"status": "1", "result": [future, zero_time, failed, nested]}

    report = investigation(FakeClient(get), ROOT, max_depth=1, page_size=10)
    assert report["status"] == "partial" and report["edges"] == []
    assert report["coverage"][0]["invalid_rows"] == 4


def test_repeated_full_page_stops_pagination_as_partial():
    calls = []

    def get(url, params):
        calls.append(params["page"])
        if params["action"] == "txlist":
            return {"status": "1", "result": [native()]}
        return empty()

    report = investigation(FakeClient(get), ROOT, page_size=1, max_pages=3)
    tx = next(item for item in report["coverage"] if item["action"] == "txlist")
    assert report["status"] == "partial"
    assert tx["error"] == "repeated_page" and calls[:2] == [1, 2]


def test_depth_stop_reason_and_contract_homogeneous_path():
    def get(url, params):
        if params["action"] == "tokentx" and params["address"] == ROOT:
            return {"status": "1", "result": [token(log_index="8")]}
        return empty()

    report = investigation(FakeClient(get), ROOT, max_depth=1, page_size=10)
    node = next(node for node in report["nodes"] if node["address"] == FUNDER)
    assert node["contract"] == TOKEN and node["cutoff"] == 100
    assert node["stop_reason"] == "depth_limit"
