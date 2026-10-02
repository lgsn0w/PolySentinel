import copy

import pytest

from polysentinel.receipts import (
    BRIDGED_USDC,
    CTF_CONTRACTS,
    KNOWN_COLLATERAL,
    ORDER_FILLED_V2_TOPIC,
    POLYGON_GAS_TOKEN,
    POSITION_SPLIT_TOPIC,
    PUSD,
    TRANSFER_TOPIC,
    USDC,
    V2_EXCHANGES,
    classify,
    parse_receipt,
    verified_transfers,
)

TX = "0x" + "a" * 64
BLOCK = "0x" + "b" * 64
SENDER = "0x" + "1" * 40
ROOT = "0x" + "2" * 40
OTHER = "0x" + "3" * 40
EXCHANGE = "0xe111180000d2663c0091e4f400237545b87b996b"
CTF = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"


def topic_address(address):
    return "0x" + "0" * 24 + address[2:]


def word(value):
    return f"{value:064x}"


def transfer(index=4, sender=SENDER, receiver=ROOT, amount=1_250_000, contract=PUSD):
    return {
        "address": contract,
        "topics": [TRANSFER_TOPIC, topic_address(sender), topic_address(receiver)],
        "data": "0x" + word(amount),
        "transactionHash": TX,
        "blockHash": BLOCK,
        "logIndex": hex(index),
        "removed": False,
    }


def rpc(logs=None, status="0x1", sender=SENDER, receiver=PUSD):
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "status": status,
            "transactionHash": TX,
            "blockHash": BLOCK,
            "blockNumber": "0x123",
            "from": sender,
            "to": receiver,
            "logs": [transfer()] if logs is None else logs,
        },
    }


def edge(**changes):
    result = {
        "sender": SENDER,
        "receiver": ROOT,
        "root": ROOT,
        "contract": PUSD,
        "amount": "1.25",
        "raw_value": "1250000",
        "token_decimals": 6,
        "hash": TX,
        "kind": "erc20",
    }
    result.update(changes)
    return result


def parsed(logs=None, **changes):
    payload = rpc(logs)
    if "sender" in changes:
        changes["from"] = changes.pop("sender")
    payload["result"].update(changes)
    return parse_receipt(payload, TX)


def order_filled(index=8, address=EXCHANGE, maker=ROOT, taker=OTHER, side=0):
    data = "0x" + "".join(word(value) for value in (side, 1, 1_250_000, 2, 0, 0, 0))
    return {
        "address": address,
        "topics": [
            ORDER_FILLED_V2_TOPIC,
            "0x" + "9" * 64,
            topic_address(maker),
            topic_address(taker),
        ],
        "data": data,
        "transactionHash": TX,
        "blockHash": BLOCK,
        "logIndex": hex(index),
        "removed": False,
    }


def test_parse_receipt_normalizes_safe_snapshot():
    result = parsed()
    assert result["status"] == "verified"
    assert result["receipt"] == {
        "transactionHash": TX,
        "blockHash": BLOCK,
        "blockNumber": 0x123,
        "status": "0x1",
        "from": SENDER,
        "to": PUSD,
        "logs": [
            {
                "address": PUSD,
                "topics": [TRANSFER_TOPIC, topic_address(SENDER), topic_address(ROOT)],
                "data": "0x" + word(1_250_000),
                "transactionHash": TX,
                "blockHash": BLOCK,
                "logIndex": 4,
                "removed": False,
            }
        ],
    }


def test_all_known_registry_entries_are_canonical_addresses():
    addresses = KNOWN_COLLATERAL | V2_EXCHANGES | CTF_CONTRACTS | {POLYGON_GAS_TOKEN}
    assert all(
        len(address) == 42 and address == address.lower() for address in addresses
    )
    assert USDC == "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
    assert KNOWN_COLLATERAL == {PUSD, USDC, BRIDGED_USDC}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(transactionHash="0x" + "c" * 64),
        lambda value: value.update(blockHash="broken"),
        lambda value: value.update(blockNumber="123"),
        lambda value: value.update(status="0x2"),
        lambda value: value.update(logs="not-a-list"),
    ],
)
def test_parse_receipt_rejects_malformed_identity_and_fields(mutation):
    payload = rpc()
    mutation(payload["result"])
    assert parse_receipt(payload, TX)["status"] == "unknown"


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "transactionHash",
        "blockHash",
        "blockNumber",
        "from",
        "to",
        "logs",
    ],
)
def test_parse_receipt_rejects_missing_required_fields(field):
    payload = rpc()
    del payload["result"][field]
    assert parse_receipt(payload, TX)["status"] == "unknown"


def test_parse_receipt_rejects_log_hashes_duplicates_removed_and_bad_hex():
    variants = []
    wrong_tx = transfer()
    wrong_tx["transactionHash"] = "0x" + "c" * 64
    variants.append([wrong_tx])
    duplicate = transfer(5)
    variants.append([duplicate, copy.deepcopy(duplicate)])
    removed = transfer()
    removed["removed"] = True
    variants.append([removed])
    bad_data = transfer()
    bad_data["data"] = "0x123"
    variants.append([bad_data])
    wrong_block_number = transfer()
    wrong_block_number["blockNumber"] = "0x124"
    variants.append([wrong_block_number])
    too_many_topics = transfer()
    too_many_topics["topics"].extend(["0x" + "d" * 64, "0x" + "e" * 64])
    variants.append([too_many_topics])
    for logs in variants:
        assert parse_receipt(rpc(logs), TX)["status"] == "unknown"


def test_parse_receipt_bounds_log_count_and_data_size():
    assert parse_receipt(rpc([transfer()] * 2049), TX)["status"] == "unknown"
    oversized = transfer()
    oversized["data"] = "0x" + "00" * (1024 * 1024 + 1)
    assert parse_receipt(rpc([oversized]), TX)["status"] == "unknown"


def test_failed_and_unavailable_receipts_are_not_verified():
    failed = parse_receipt(rpc(status="0x0"), TX)
    assert failed["status"] == "failed"
    assert classify(edge(), failed)["receipt_verified"] is False
    assert parse_receipt({"result": None}, TX)["status"] == "unknown"


def test_verified_transfer_uses_exact_decimal_scaling_and_canonical_event_id():
    receipt = parsed()
    matches = verified_transfers(edge(), receipt)
    assert matches == [
        {
            "log_index": 4,
            "raw_value": "1250000",
            "sender": SENDER,
            "receiver": ROOT,
            "contract": PUSD,
            "event_id": f"137:{TX}:4",
        }
    ]
    assert (
        verified_transfers(edge(amount="1.250001", raw_value="1250001"), receipt) == []
    )
    assert verified_transfers(edge(amount=1.25), receipt) == []


def test_large_decimal_amount_is_compared_without_context_rounding():
    amount = "123456789012345678901234567890.123456"
    raw = "123456789012345678901234567890123456"
    receipt = parsed([transfer(amount=int(raw))])
    match = verified_transfers(edge(amount=amount, raw_value=raw), receipt)
    assert match[0]["raw_value"] == raw


def test_decimal_scaling_is_bounded_positive_uint256_and_known_decimals_are_fixed():
    receipt = parsed()
    assert verified_transfers(edge(amount="1e999999999", raw_value=None), receipt) == []
    assert verified_transfers(edge(amount="0", raw_value="0"), receipt) == []
    assert (
        verified_transfers(edge(amount=str(2**256), raw_value=str(2**256)), receipt)
        == []
    )
    assert (
        verified_transfers(edge(token_decimals=18), receipt)[0]["raw_value"]
        == "1250000"
    )


def test_log_index_disambiguates_identical_transfers():
    receipt = parsed([transfer(4), transfer(9)])
    assert len(verified_transfers(edge(), receipt)) == 2
    assert classify(edge(), receipt)["reason"] == "multiple receipt logs match the edge"
    chosen = classify(edge(log_index=9), receipt)
    assert chosen["log_index"] == 9
    assert chosen["category"] == "unknown"


def test_simple_known_collateral_transfer_is_direct_and_gas_log_is_allowed():
    direct = classify(edge(), parsed())
    assert direct == {
        "category": "direct_transfer",
        "reason": "verified simple direct collateral transfer",
        "receipt_verified": True,
        "log_index": 4,
        "event_id": f"137:{TX}:4",
        "evidence_events": [],
    }
    gas = transfer(7, contract=POLYGON_GAS_TOKEN)
    with_gas = classify(edge(), parsed([transfer(), gas]))
    assert with_gas["category"] == "direct_transfer"
    assert classify(edge(root=None), parsed())["category"] == "unknown"
    assert classify(edge(root=OTHER), parsed())["category"] == "unknown"


def test_wrong_top_level_sender_unknown_token_native_and_complex_stay_unknown():
    assert classify(edge(), parsed(sender=OTHER))["category"] == "unknown"
    token = "0x" + "5" * 40
    unknown = parsed([transfer(contract=token)], to=token)
    assert classify(edge(contract=token), unknown)["category"] == "unknown"
    assert (
        classify(edge(kind="native", contract=None), parsed())["category"] == "unknown"
    )
    unrelated = transfer(6, sender=OTHER, receiver=SENDER, amount=2)
    assert classify(edge(), parsed([transfer(), unrelated]))["category"] == "unknown"


def test_transfer_matching_is_bound_to_edge_transaction_and_plain_erc20_kind():
    receipt = parsed()
    assert verified_transfers(edge(hash="0x" + "c" * 64), receipt) == []
    assert (
        verified_transfers(edge(kind="erc20_mint", sender="0x" + "0" * 40), receipt)
        == []
    )
    assert (
        verified_transfers(edge(kind="erc20_burn", receiver="0x" + "0" * 40), receipt)
        == []
    )


def test_circle_usdc_simple_transfer_is_recognized_with_fixed_six_decimals():
    receipt = parsed([transfer(contract=USDC)], to=USDC)
    result = classify(edge(contract=USDC, token_decimals=18), receipt)
    assert result["category"] == "direct_transfer"


def test_trusted_order_is_only_trade_related_when_wallet_and_collateral_correlate():
    receipt = parsed([transfer(), order_filled()])
    result = classify(edge(), receipt)
    assert result["category"] == "trade_related"
    assert result["evidence_events"][0]["maker"] == ROOT
    unrelated = classify(edge(root=SENDER), receipt)
    assert unrelated["category"] == "unknown"
    wrong_collateral = "0x" + "5" * 40
    other_receipt = parsed(
        [transfer(contract=wrong_collateral), order_filled()], to=EXCHANGE
    )
    assert (
        classify(edge(contract=wrong_collateral), other_receipt)["category"]
        == "unknown"
    )


def test_spoofed_or_malformed_protocol_topic_never_adds_context():
    spoof = order_filled(address=OTHER)
    assert classify(edge(), parsed([transfer(), spoof]))["category"] == "unknown"
    malformed = order_filled()
    malformed["data"] = "0x" + word(0)
    assert classify(edge(), parsed([transfer(), malformed]))["category"] == "unknown"


def test_ctf_position_split_requires_valid_abi_stakeholder_and_collateral():
    partition = [1, 2]
    data = "0x" + topic_address(PUSD)[2:] + word(96) + word(1_250_000)
    data += word(len(partition)) + "".join(word(value) for value in partition)
    event = {
        "address": CTF,
        "topics": [
            POSITION_SPLIT_TOPIC,
            topic_address(ROOT),
            "0x" + "0" * 64,
            "0x" + "7" * 64,
        ],
        "data": data,
        "transactionHash": TX,
        "blockHash": BLOCK,
        "logIndex": "0xa",
        "removed": False,
    }
    result = classify(edge(), parsed([transfer(), event], to=CTF))
    assert result["category"] == "position_split"
    event["data"] = event["data"][:-64]
    assert (
        classify(edge(), parsed([transfer(), event], to=CTF))["category"] == "unknown"
    )
