from collections import deque
import hashlib
import json
import re
import time
from urllib.parse import urlsplit

from .clients import UpstreamError

API_URL = "https://api.etherscan.io/v2/api"
CHAIN_ID = 137
CONTRACT_SOURCE = "https://docs.polymarket.com/resources/contracts"
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
POLYMARKET_INFRASTRUCTURE = {
    address.lower(): label
    for address, label in {
        "0xE111180000d2663C0091e4f400237545B87B996B": "Polymarket CTF Exchange",
        "0xe2222d279d744050d28e00520010520000310F59": "Polymarket Neg Risk CTF Exchange",
        "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296": "Polymarket Neg Risk Adapter",
        "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045": "Polymarket Conditional Tokens",
        "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB": "Polymarket pUSD",
        "0x93070a847efEf7F70739046A929D47a521F5B8ee": "Polymarket Collateral Onramp",
        "0x2957922Eb93258b93368531d39fAcCA3B4dC5854": "Polymarket Collateral Offramp",
        "0xebC2459Ec962869ca4c0bd1E06368272732BCb08": "Polymarket Permissioned Ramp",
        "0xAdA100Db00Ca00073811820692005400218FcE1f": "Polymarket CTF Collateral Adapter",
        "0xadA2005600Dec949baf300f4C6120000bDB6eAab": "Polymarket Neg Risk CTF Collateral Adapter",
        "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07": "Polymarket Deposit Wallet Factory",
        "0x7A18EDfe055488A3128f01F563e5B479D92ffc3a": "Polymarket Deposit Wallet Beacon",
        "0xaacfeea03eb1561c4e67d661e40682bd20e3541b": "Polymarket Gnosis Safe Factory",
        "0xaB45c5A4B0c941a2F231C04C3f49182e1A254052": "Polymarket Proxy Factory",
    }.items()
}
INFRASTRUCTURE = frozenset(POLYMARKET_INFRASTRUCTURE)
ZERO_ADDRESS = "0x" + "0" * 40
ENDPOINTS = ("txlist", "txlistinternal", "tokentx")


def _address(value):
    value = str(value or "")
    return value.lower() if ADDRESS_RE.fullmatch(value) else None


def _timestamp(value, current_time):
    value = _integer(value)
    return value if 0 < value <= current_time else None


def _integer(value):
    if value is None or isinstance(value, bool):
        return None
    value = str(value)
    if not value.isascii() or not value.isdigit() or len(value) > 100:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _amount(value, decimals):
    integer = _integer(value)
    decimal_places = _integer(decimals)
    if (
        integer is None
        or integer <= 0
        or decimal_places is None
        or decimal_places > 255
    ):
        return None
    digits = str(integer)
    if decimal_places == 0:
        return digits
    if len(digits) <= decimal_places:
        rendered = "0." + "0" * (decimal_places - len(digits)) + digits
    else:
        rendered = digits[:-decimal_places] + "." + digits[-decimal_places:]
    return rendered.rstrip("0").rstrip(".")


def _safe_url(value):
    try:
        parts = urlsplit(str(value))
    except ValueError:
        return None
    return str(value) if parts.scheme == "https" and bool(parts.netloc) else None


def _infrastructure(client):
    result = {
        address: {"label": label, "source": CONTRACT_SOURCE}
        for address, label in POLYMARKET_INFRASTRUCTURE.items()
    }
    supplied = getattr(client, "provenance_labels", {})
    if not isinstance(supplied, dict):
        return result
    for raw_address, details in supplied.items():
        address = _address(raw_address)
        if (
            not address
            or not isinstance(details, dict)
            or details.get("infrastructure") is not True
        ):
            continue
        source = _safe_url(details.get("source"))
        label = details.get("label")
        if source and isinstance(label, str) and label.strip():
            result[address] = {"label": label.strip()[:200], "source": source}
    return result


def verified_infrastructure(client=None):
    if client is None:
        return {
            address: {"label": label, "source": CONTRACT_SOURCE}
            for address, label in POLYMARKET_INFRASTRUCTURE.items()
        }
    return _infrastructure(client)


def _unsupported(message):
    message = str(message).lower()
    return any(
        term in message
        for term in (
            "not supported",
            "unsupported",
            "chainid",
            "subscription",
            "paid plan",
        )
    )


def _page(payload):
    if not isinstance(payload, dict):
        raise ValueError("invalid response")
    result = payload.get("result")
    if payload.get("status") == "1" and isinstance(result, list):
        return result
    message = " ".join(str(payload.get(key, "")) for key in ("message", "result"))
    if (
        payload.get("status") == "0"
        and isinstance(result, (str, list))
        and (result == [] or "no transactions found" in message.lower())
    ):
        return []
    if _unsupported(message):
        raise NotImplementedError(message or "unsupported endpoint")
    raise ValueError(message or "invalid response")


def _edge(row, action, depth, occurrence, current_time):
    sender = _address(row.get("from"))
    receiver = _address(row.get("to"))
    tx_hash = str(row.get("hash") or "").lower()
    timestamp = _timestamp(row.get("timeStamp"), current_time)
    if not sender or not receiver:
        return None, True, False
    if action != "tokentx" and (sender == ZERO_ADDRESS or receiver == ZERO_ADDRESS):
        return None, True, False
    if not HASH_RE.fullmatch(tx_hash) or timestamp is None:
        return None, True, False
    if (
        str(row.get("isError", "0")) != "0"
        or str(row.get("txreceipt_status", "1")) == "0"
    ):
        return None, True, False
    if action == "tokentx":
        contract = _address(row.get("contractAddress"))
        integer = _integer(row.get("value"))
        amount = _amount(row.get("value"), row.get("tokenDecimal"))
        if integer == 0:
            return None, False, False
        if not contract or not amount:
            return None, True, False
        symbol = str(row.get("tokenSymbol") or "ERC20").strip()[:64] or "ERC20"
        asset = "token:" + symbol
        kind = (
            "erc20_mint"
            if sender == ZERO_ADDRESS
            else "erc20_burn" if receiver == ZERO_ADDRESS else "erc20"
        )
        log_index = _integer(row.get("logIndex"))
        ambiguous = log_index is None
        discriminator = (
            f"log:{log_index}" if log_index is not None else f"occurrence:{occurrence}"
        )
    else:
        contract = None
        integer = _integer(row.get("value"))
        amount = _amount(row.get("value"), 18)
        if integer == 0:
            return None, False, False
        if not amount:
            return None, True, False
        asset = "native:POL"
        kind = "internal" if action == "txlistinternal" else "native"
        discriminator = str(row.get("traceId") or row.get("transactionIndex") or "")
        ambiguous = False
    identity = "|".join(
        (
            action,
            tx_hash,
            discriminator,
            sender,
            receiver,
            contract or "",
            str(row.get("value")),
        )
    )
    event_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    edge = {
        "id": event_id,
        "event_id": event_id,
        "sender": sender,
        "receiver": receiver,
        "asset": asset,
        "contract": contract,
        "amount": amount,
        "timestamp": timestamp,
        "hash": tx_hash,
        "kind": kind,
        "depth": depth,
        "identity_ambiguous": ambiguous,
        "ancestry": False,
        "evidence": f"https://polygonscan.com/tx/{tx_hash}",
    }
    if action == "tokentx":
        edge.update(
            raw_value=str(integer),
            token_decimals=int(row["tokenDecimal"]),
            log_index=log_index,
        )
    return edge, False, ambiguous


def _normal_duplicate(edge, normal_keys):
    key = (edge["hash"], edge["sender"], edge["receiver"], edge["amount"])
    return edge["kind"] == "internal" and key in normal_keys


def investigation(
    client,
    address,
    max_depth=3,
    max_nodes=12,
    max_requests=30,
    page_size=100,
    max_pages=2,
):
    root = _address(address)
    if not root:
        raise ValueError("address must be a 20-byte hexadecimal address")
    bounds = (max_depth, max_nodes, max_requests, page_size, max_pages)
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in bounds
    ):
        raise ValueError("limits must be non-negative integers")
    if max_nodes < 1 or max_requests < 1 or page_size < 1 or max_pages < 1:
        raise ValueError("node, request, page size, and page limits must be positive")
    key = getattr(getattr(client, "settings", None), "etherscan_key", "")
    base = {
        "address": root,
        "nodes": [],
        "edges": [],
        "warnings": [],
        "coverage": [],
        "requests": 0,
        "limits": {
            "max_depth": max_depth,
            "max_nodes": max_nodes,
            "max_requests": max_requests,
            "page_size": page_size,
            "max_pages": max_pages,
            "deadline_seconds": 90,
        },
    }
    if not isinstance(key, str) or not key.strip():
        return {"status": "no_key", **base}
    infrastructure = _infrastructure(client)
    root_state = (root, None)
    queue = deque([root_state])
    pending = {root_state}
    cutoffs = {root_state: None}
    depths = {root_state: 0}
    processed_cutoffs = {}
    node_indices = {}
    nodes = []
    edges = []
    coverage = []
    warnings = [
        "Unknown exchanges, bridges, and shared services are not identified or attributed"
    ]
    requests = 0
    deadline = time.monotonic() + 90
    current_time = int(time.time())
    truncated = False
    successes = 0
    unsupported_errors = 0
    normal_keys = set()
    while queue:
        state = queue.popleft()
        pending.discard(state)
        current, required_contract = state
        depth = depths[state]
        before = cutoffs[state]
        details = infrastructure.get(current)
        if state not in node_indices:
            node_indices[state] = len(nodes)
            nodes.append(
                {
                    "address": current,
                    "contract": required_contract,
                    "cutoff": before,
                    "depth": depth,
                    "infrastructure": bool(details),
                    "label": details["label"] if details else None,
                    "source": details["source"] if details else None,
                    "stop_reason": None,
                }
            )
        else:
            nodes[node_indices[state]]["cutoff"] = before
        if details or depth >= max_depth:
            if details:
                nodes[node_indices[state]]["stop_reason"] = "verified_infrastructure"
                warnings.append(
                    f"Traversal stopped at verified infrastructure {current}"
                )
            elif depth >= max_depth:
                nodes[node_indices[state]]["stop_reason"] = "depth_limit"
                truncated = True
                warnings.append(f"Depth limit reached at {current}")
            continue
        current_edges = []
        actions = ENDPOINTS if state == root_state else ("tokentx",)
        for action in actions:
            occurrences = {}
            record = {
                "address": current,
                "action": action,
                "pages": 0,
                "rows": 0,
                "invalid_rows": 0,
                "complete": False,
                "error": None,
                "contract": required_contract,
                "cutoff": before,
            }
            coverage.append(record)
            page_fingerprints = set()
            for page_number in range(1, max_pages + 1):
                if requests >= max_requests:
                    record["error"] = "request_budget"
                    truncated = True
                    break
                if time.monotonic() >= deadline:
                    record["error"] = "deadline"
                    truncated = True
                    break
                params = {
                    "chainid": CHAIN_ID,
                    "module": "account",
                    "action": action,
                    "address": current,
                    "startblock": 0,
                    "endblock": 99999999,
                    "page": page_number,
                    "offset": page_size,
                    "sort": "desc",
                    "apikey": key,
                }
                if required_contract:
                    params["contractaddress"] = required_contract
                requests += 1
                try:
                    rows = _page(client.get(API_URL, params))
                except NotImplementedError:
                    record["error"] = "unsupported"
                    unsupported_errors += 1
                    warnings.append(f"{action} unavailable for {current}: unsupported")
                    break
                except (UpstreamError, ValueError, TypeError, KeyError):
                    record["error"] = "upstream_error"
                    warnings.append(f"{action} unavailable for {current}")
                    break
                successes += 1
                try:
                    fingerprint_payload = json.dumps(
                        rows, sort_keys=True, separators=(",", ":"), default=str
                    )
                except (TypeError, ValueError):
                    fingerprint_payload = repr(rows)
                fingerprint = hashlib.sha256(
                    fingerprint_payload.encode("utf-8", "replace")
                ).hexdigest()
                if fingerprint in page_fingerprints:
                    record["error"] = "repeated_page"
                    truncated = True
                    warnings.append(f"Repeated {action} page for {current}")
                    break
                page_fingerprints.add(fingerprint)
                record["pages"] += 1
                record["rows"] += len(rows)
                for row in rows:
                    if not isinstance(row, dict):
                        record["invalid_rows"] += 1
                        continue
                    semantic = tuple(
                        str(value)
                        for value in (
                            action,
                            row.get("hash"),
                            row.get("from"),
                            row.get("to"),
                            row.get("contractAddress"),
                            row.get("value"),
                            row.get("logIndex"),
                        )
                    )
                    occurrence = occurrences.get(semantic, 0)
                    occurrences[semantic] = occurrence + 1
                    edge, invalid, ambiguous = _edge(
                        row, action, depth, occurrence, current_time
                    )
                    if invalid:
                        record["invalid_rows"] += 1
                        continue
                    if edge is None:
                        continue
                    if current not in (edge["sender"], edge["receiver"]):
                        record["invalid_rows"] += 1
                        continue
                    if ambiguous:
                        warnings.append(
                            "ERC20 transfer log index unavailable; duplicate event indexing is ambiguous"
                        )
                        record["ambiguous_rows"] = record.get("ambiguous_rows", 0) + 1
                    if state == root_state or (
                        edge["contract"] == required_contract
                        and edge["timestamp"] <= before
                    ):
                        edge["ancestry"] = (
                            edge["receiver"] == current
                            and edge["sender"] != current
                            and edge["kind"] == "erc20"
                        )
                        current_edges.append(edge)
                if len(rows) < page_size:
                    record["complete"] = True
                    break
            else:
                record["error"] = "page_limit"
                truncated = True
        for edge in current_edges:
            key_tuple = (edge["hash"], edge["sender"], edge["receiver"], edge["amount"])
            if edge["kind"] == "native":
                normal_keys.add(key_tuple)
        for edge in current_edges:
            if _normal_duplicate(edge, normal_keys):
                continue
            edges.append(edge)
        incoming = sorted(
            (edge for edge in current_edges if edge["receiver"] == current),
            key=lambda edge: (edge["timestamp"], edge["event_id"]),
            reverse=True,
        )
        for edge in incoming:
            if edge["kind"] != "erc20" or not edge["contract"]:
                continue
            sender = edge["sender"]
            if sender in (ZERO_ADDRESS, current):
                continue
            child = (sender, edge["contract"])
            if child in cutoffs:
                known = cutoffs[child]
                expanded = max(known, edge["timestamp"])
                if expanded > known:
                    cutoffs[child] = expanded
                    if child in node_indices:
                        nodes[node_indices[child]]["cutoff"] = expanded
                    processed = processed_cutoffs.get(child)
                    if (
                        processed is not None
                        and expanded > processed
                        and child not in pending
                    ):
                        queue.append(child)
                        pending.add(child)
                        warnings.append(
                            f"Expanded temporal cutoff revisited for {sender}"
                        )
                continue
            if len(cutoffs) >= max_nodes:
                truncated = True
                continue
            cutoffs[child] = edge["timestamp"]
            depths[child] = depth + 1
            queue.append(child)
            pending.add(child)
        processed_cutoffs[state] = before
    unique = {}
    for edge in edges:
        unique.setdefault(edge["event_id"], edge)
    edges = sorted(
        unique.values(),
        key=lambda edge: (edge["depth"], -edge["timestamp"], edge["event_id"]),
    )
    if any(edge["kind"] in ("native", "internal") for edge in edges):
        warnings.append(
            "Native transfers may only fund gas and are not treated as capital attribution"
        )
    if truncated:
        warnings.append(
            "Investigation is a bounded recent sample, not complete transaction history"
        )
    if (
        successes == 0
        and unsupported_errors
        and all(item["error"] == "unsupported" for item in coverage)
    ):
        status = "unsupported"
    elif truncated or any(
        not item["complete"] or item["invalid_rows"] or item.get("ambiguous_rows")
        for item in coverage
    ):
        status = "partial"
    else:
        status = "complete"
    return {
        "status": status,
        "address": root,
        "nodes": nodes,
        "edges": edges,
        "warnings": list(dict.fromkeys(warnings)),
        "coverage": coverage,
        "requests": requests,
        "limits": base["limits"],
    }
