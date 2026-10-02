from decimal import Decimal, InvalidOperation
import re

CHAIN_ID = 137
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ORDER_FILLED_V2_TOPIC = (
    "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
)
ORDERS_MATCHED_V2_TOPIC = (
    "0x174b3811690657c217184f89418266767c87e4805d09680c39fc9c031c0cab7c"
)
ORDER_FILLED_V1_TOPIC = (
    "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"
)
POSITION_SPLIT_TOPIC = (
    "0x2e6bb91f8cbcda0c93623c54d0403a43514fabc40084ec96b6d5379a74786298"
)
POSITIONS_MERGE_TOPIC = (
    "0x6f13ca62553fcc2bcd2372180a43949c1e4cebba603901ede2f4e14f36b282ca"
)
PAYOUT_REDEMPTION_TOPIC = (
    "0x2682012a4a4f1973119f1c9b90745d1bd91fa2bab387344f044cb3586864d18d"
)
PUSD = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"
USDC = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
BRIDGED_USDC = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
POLYGON_GAS_TOKEN = "0x0000000000000000000000000000000000001010"
KNOWN_COLLATERAL = frozenset((PUSD, USDC, BRIDGED_USDC))
V2_EXCHANGES = frozenset(
    (
        "0xe111180000d2663c0091e4f400237545b87b996b",
        "0xe2222d279d744050d28e00520010520000310f59",
    )
)
CTF_CONTRACTS = frozenset(
    (
        "0x4d97dcd97ec945f40cf65f87097ace5ea0476045",
        "0xd91e80cf2e7be2e162c6513ced06f1dd0da35296",
        "0xada100db00ca00073811820692005400218fce1f",
        "0xada2005600dec949baf300f4c6120000bdb6eaab",
    )
)
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
BYTES_RE = re.compile(r"^0x(?:[0-9a-fA-F]{2})*$")
QUANTITY_RE = re.compile(r"^0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)$")
ZERO_ADDRESS = "0x" + "0" * 40
MAX_UINT256 = 2**256 - 1


def _unknown(reason, status="unknown"):
    return {"status": status, "reason": reason, "receipt": None}


def _address(value):
    return (
        value.lower()
        if isinstance(value, str) and ADDRESS_RE.fullmatch(value)
        else None
    )


def _hash(value):
    return (
        value.lower() if isinstance(value, str) and HASH_RE.fullmatch(value) else None
    )


def _quantity(value):
    if not isinstance(value, str) or not QUANTITY_RE.fullmatch(value):
        return None
    return int(value, 16)


def _bytes(value):
    return (
        value.lower() if isinstance(value, str) and BYTES_RE.fullmatch(value) else None
    )


def parse_receipt(payload, expected_hash):
    expected = _hash(expected_hash)
    if expected is None:
        return _unknown("invalid expected transaction hash")
    if not isinstance(payload, dict):
        return _unknown("invalid JSON-RPC response")
    result = payload.get("result")
    if not isinstance(result, dict):
        return _unknown("receipt unavailable")
    if any(
        key not in result
        for key in (
            "status",
            "transactionHash",
            "blockHash",
            "blockNumber",
            "from",
            "to",
            "logs",
        )
    ):
        return _unknown("malformed receipt")
    tx_hash = _hash(result.get("transactionHash"))
    block_hash = _hash(result.get("blockHash"))
    block_number = _quantity(result.get("blockNumber"))
    sender = _address(result.get("from"))
    receiver_value = result.get("to")
    receiver = None if receiver_value is None else _address(receiver_value)
    status = result.get("status")
    logs = result.get("logs")
    if status not in ("0x0", "0x1"):
        return _unknown("invalid receipt status")
    if tx_hash != expected or block_hash is None or block_number is None:
        return _unknown("receipt identity mismatch")
    if (
        sender is None
        or (receiver_value is not None and receiver is None)
        or not isinstance(logs, list)
        or len(logs) > 2048
    ):
        return _unknown("malformed receipt")
    normalized_logs = []
    indices = set()
    for item in logs:
        if not isinstance(item, dict):
            return _unknown("malformed receipt log")
        address = _address(item.get("address"))
        log_tx_hash = _hash(item.get("transactionHash"))
        log_block_hash = _hash(item.get("blockHash"))
        log_index = _quantity(item.get("logIndex"))
        data = _bytes(item.get("data"))
        topics = item.get("topics")
        item_block_number = item.get("blockNumber")
        if (
            item_block_number is not None
            and _quantity(item_block_number) != block_number
        ):
            return _unknown("malformed receipt log")
        if (
            address is None
            or log_tx_hash != tx_hash
            or log_block_hash != block_hash
            or log_index is None
            or log_index in indices
            or data is None
            or len(data) > 2 + 2 * 1024 * 1024
            or item.get("removed") is not False
            or not isinstance(topics, list)
            or len(topics) > 4
            or any(_hash(topic) is None for topic in topics)
        ):
            return _unknown("malformed receipt log")
        indices.add(log_index)
        normalized_logs.append(
            {
                "address": address,
                "topics": [topic.lower() for topic in topics],
                "data": data,
                "transactionHash": tx_hash,
                "blockHash": block_hash,
                "logIndex": log_index,
                "removed": False,
            }
        )
    receipt = {
        "transactionHash": tx_hash,
        "blockHash": block_hash,
        "blockNumber": block_number,
        "status": status,
        "from": sender,
        "to": receiver,
        "logs": normalized_logs,
    }
    if status == "0x0":
        return {
            "status": "failed",
            "reason": "transaction execution failed",
            "receipt": receipt,
        }
    return {
        "status": "verified",
        "reason": "successful receipt verified",
        "receipt": receipt,
    }


def _receipt(value):
    if not isinstance(value, dict):
        return None
    if value.get("status") == "verified" and isinstance(value.get("receipt"), dict):
        return value["receipt"]
    if value.get("status") == "0x1" and isinstance(value.get("logs"), list):
        return value
    return None


def _topic_address(topic):
    if (
        not isinstance(topic, str)
        or not HASH_RE.fullmatch(topic)
        or topic[2:26] != "0" * 24
    ):
        return None
    return "0x" + topic[-40:].lower()


def _edge_decimals(edge):
    contract = _address(edge.get("contract"))
    if contract in KNOWN_COLLATERAL:
        return 6
    value = edge.get("token_decimals", edge.get("decimals", edge.get("tokenDecimal")))
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return (
        parsed
        if str(value).isascii() and str(value).isdigit() and 0 <= parsed <= 255
        else None
    )


def _edge_raw_value(edge):
    decimals = _edge_decimals(edge)
    amount = edge.get("amount")
    if decimals is None or isinstance(amount, (float, bool)):
        return None
    rendered = str(amount)
    if len(rendered) > 500:
        return None
    try:
        decimal = Decimal(rendered)
    except (InvalidOperation, ValueError):
        return None
    if not decimal.is_finite() or decimal < 0:
        return None
    parts = decimal.as_tuple()
    coefficient = int("".join(str(digit) for digit in parts.digits) or "0")
    scale = parts.exponent + decimals
    if abs(scale) > 512:
        return None
    if scale >= 0:
        raw = coefficient * 10**scale
    else:
        divisor = 10**-scale
        if coefficient % divisor:
            return None
        raw = coefficient // divisor
    if raw <= 0 or raw > MAX_UINT256:
        return None
    supplied = edge.get("raw_value")
    if supplied is not None and (
        isinstance(supplied, bool)
        or len(str(supplied)) > 500
        or not str(supplied).isascii()
        or not str(supplied).isdigit()
        or int(supplied) != raw
    ):
        return None
    return str(raw)


def _transfer(log):
    topics = log["topics"]
    if len(topics) != 3 or topics[0] != TRANSFER_TOPIC or len(log["data"]) != 66:
        return None
    sender = _topic_address(topics[1])
    receiver = _topic_address(topics[2])
    if sender is None or receiver is None:
        return None
    raw_value = int(log["data"][2:], 16)
    if raw_value > MAX_UINT256:
        return None
    return {
        "log_index": log["logIndex"],
        "raw_value": str(raw_value),
        "sender": sender,
        "receiver": receiver,
        "contract": log["address"],
        "event_id": f"{CHAIN_ID}:{log['transactionHash']}:{log['logIndex']}",
    }


def verified_transfers(edge, receipt):
    normalized = _receipt(receipt)
    if normalized is None or not isinstance(edge, dict):
        return []
    sender = _address(edge.get("sender"))
    receiver = _address(edge.get("receiver"))
    contract = _address(edge.get("contract"))
    edge_hash = _hash(edge.get("hash"))
    raw_value = _edge_raw_value(edge)
    if (
        None in (sender, receiver, contract, edge_hash, raw_value)
        or normalized.get("transactionHash") != edge_hash
        or edge.get("kind") != "erc20"
        or sender == ZERO_ADDRESS
        or receiver == ZERO_ADDRESS
    ):
        return []
    requested_index = edge.get("log_index")
    if requested_index is not None:
        if isinstance(requested_index, bool):
            return []
        try:
            requested_index = int(requested_index)
        except (TypeError, ValueError):
            return []
    matches = []
    for log in normalized["logs"]:
        transfer = _transfer(log)
        if (
            transfer
            and transfer["sender"] == sender
            and transfer["receiver"] == receiver
            and transfer["contract"] == contract
            and transfer["raw_value"] == raw_value
            and (requested_index is None or transfer["log_index"] == requested_index)
        ):
            matches.append(transfer)
    return matches


def _static_order_filled(log):
    if log["address"] not in V2_EXCHANGES or log["topics"][0:1] != [
        ORDER_FILLED_V2_TOPIC
    ]:
        return None
    if len(log["topics"]) != 4 or len(log["data"]) != 2 + 7 * 64:
        return None
    maker = _topic_address(log["topics"][2])
    taker = _topic_address(log["topics"][3])
    words = [
        log["data"][2 + offset : 2 + offset + 64] for offset in range(0, 7 * 64, 64)
    ]
    if maker is None or taker is None or int(words[0], 16) not in (0, 1):
        return None
    return {
        "type": "OrderFilled",
        "maker": maker,
        "taker": taker,
        "contract": log["address"],
        "log_index": log["logIndex"],
        "event_id": f"{CHAIN_ID}:{log['transactionHash']}:{log['logIndex']}",
    }


def _dynamic_event(log):
    topic = log["topics"][0] if log["topics"] else None
    names = {
        POSITION_SPLIT_TOPIC: "PositionSplit",
        POSITIONS_MERGE_TOPIC: "PositionsMerge",
        PAYOUT_REDEMPTION_TOPIC: "PayoutRedemption",
    }
    if (
        log["address"] not in CTF_CONTRACTS
        or topic not in names
        or len(log["topics"]) != 4
    ):
        return None
    data = log["data"][2:]
    if len(data) < 4 * 64 or len(data) % 64:
        return None
    words = [data[offset : offset + 64] for offset in range(0, len(data), 64)]
    stakeholder = _topic_address(log["topics"][1])
    if topic == PAYOUT_REDEMPTION_TOPIC:
        collateral = _topic_address(log["topics"][2])
        offset_word = 1
    else:
        collateral = _topic_address("0x" + words[0])
        offset_word = 1
    if stakeholder is None or collateral is None or int(words[offset_word], 16) != 96:
        return None
    count = int(words[3], 16)
    if count > 256 or len(words) != 4 + count:
        return None
    return {
        "type": names[topic],
        "stakeholder": stakeholder,
        "collateral": collateral,
        "contract": log["address"],
        "log_index": log["logIndex"],
        "event_id": f"{CHAIN_ID}:{log['transactionHash']}:{log['logIndex']}",
    }


def _result(category, reason, verified=False, transfer=None, evidence=None):
    return {
        "category": category,
        "reason": reason,
        "receipt_verified": verified,
        "log_index": transfer["log_index"] if transfer else None,
        "event_id": transfer["event_id"] if transfer else None,
        "evidence_events": evidence or [],
    }


def classify(edge, receipt):
    normalized = _receipt(receipt)
    if normalized is None:
        status = receipt.get("status") if isinstance(receipt, dict) else None
        reason = (
            "transaction execution failed"
            if status == "failed"
            else "receipt not verified"
        )
        return _result("unknown", reason)
    if not isinstance(edge, dict):
        return _result("unknown", "invalid edge", True)
    if edge.get("kind") in ("native", "internal") or not edge.get("contract"):
        return _result(
            "unknown",
            "native and internal value movements do not prove a deposit",
            True,
        )
    matches = verified_transfers(edge, normalized)
    if not matches:
        return _result("unknown", "no exact ERC-20 Transfer matched the edge", True)
    if len(matches) != 1:
        return _result("unknown", "multiple receipt logs match the edge", True)
    transfer = matches[0]
    root = _address(edge.get("root"))
    contract = _address(edge.get("contract"))
    protocol_events = []
    for log in normalized["logs"]:
        order = _static_order_filled(log)
        if order and root in (order["maker"], order["taker"]) and contract == PUSD:
            protocol_events.append(order)
        ctf = _dynamic_event(log)
        if ctf and root == ctf["stakeholder"] and contract == ctf["collateral"]:
            protocol_events.append(ctf)
    if protocol_events:
        types = {item["type"] for item in protocol_events}
        if types == {"PositionSplit"}:
            category = "position_split"
        elif types == {"PositionsMerge"}:
            category = "positions_merge"
        elif types == {"PayoutRedemption"}:
            category = "payout_redemption"
        else:
            category = "trade_related"
        return _result(
            category,
            "trusted protocol context is wallet-related but does not prove this transfer is settlement or a deposit",
            True,
            transfer,
            protocol_events,
        )
    if any(
        log["topics"]
        and log["topics"][0]
        in (
            ORDER_FILLED_V2_TOPIC,
            ORDERS_MATCHED_V2_TOPIC,
            ORDER_FILLED_V1_TOPIC,
            POSITION_SPLIT_TOPIC,
            POSITIONS_MERGE_TOPIC,
            PAYOUT_REDEMPTION_TOPIC,
        )
        for log in normalized["logs"]
    ):
        return _result(
            "unknown",
            "protocol event was untrusted, malformed, or unrelated to the edge",
            True,
            transfer,
        )
    simple_logs = [
        log for log in normalized["logs"] if log["address"] != POLYGON_GAS_TOKEN
    ]
    if (
        contract in KNOWN_COLLATERAL
        and root in (transfer["sender"], transfer["receiver"])
        and len(simple_logs) == 1
        and normalized["from"] == transfer["sender"]
        and normalized["to"] == contract
    ):
        return _result(
            "direct_transfer",
            "verified simple direct collateral transfer",
            True,
            transfer,
        )
    return _result(
        "unknown",
        "complex or unrecognized transfer cannot be attributed",
        True,
        transfer,
    )
