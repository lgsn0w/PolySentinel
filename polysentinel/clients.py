import logging
from datetime import datetime
import math
import time
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)
DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"


class UpstreamError(RuntimeError):
    pass


class Client:
    def __init__(self, settings, session=None):
        self.settings = settings
        self._etherscan_next_request = 0
        self.session = session or requests.Session()
        if session is None:
            retry = Retry(
                total=2,
                backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=("GET",),
                respect_retry_after_header=False,
            )
            self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def get(self, url, params=None):
        if urlsplit(url).hostname == "api.etherscan.io":
            delay = self._etherscan_next_request - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._etherscan_next_request = time.monotonic() + 0.6
        try:
            response = self.session.get(url, params=params, timeout=(5, 15))
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as error:
            endpoint = urlsplit(url)
            status = (
                error.response.status_code if error.response is not None else "unknown"
            )
            raise UpstreamError(
                f"{endpoint.hostname}{endpoint.path}: HTTP {status}"
            ) from None
        except (requests.RequestException, ValueError) as error:
            endpoint = urlsplit(url)
            raise UpstreamError(
                f"{endpoint.hostname}{endpoint.path}: {type(error).__name__}"
            ) from None

    def markets(self):
        markets = {}
        for tag in ("politics", "us-election"):
            markets.update(self._markets_for_tag(tag))
        if not any(markets.values()):
            raise UpstreamError(
                "No political markets found; refusing to discard trades"
            )
        return markets

    def _markets_for_tag(self, tag):
        markets = {}
        cursor, seen = None, set()
        for _ in range(1000):
            params = {"closed": "false", "limit": 100, "tag_slug": tag}
            if cursor:
                params["after_cursor"] = cursor
            page = self.get(f"{GAMMA_API}/events/keyset", params)
            if not isinstance(page, dict) or not isinstance(page.get("events"), list):
                raise UpstreamError("Invalid events response")
            events = page["events"]
            for event in events:
                tags = {str(t.get("slug") or "").lower() for t in event.get("tags", [])}
                political = bool(tags.intersection({"politics", "us-election"}))
                slug = str(event.get("slug") or "")
                for market in event.get("markets", []):
                    cid = market.get("conditionId")
                    if cid:
                        metadata = {
                            "question": str(market.get("question") or "Unknown market"),
                            "category": "Politics",
                            "link": f"https://polymarket.com/event/{slug}",
                        }
                        if political or cid not in markets:
                            markets[cid] = metadata if political else None
            cursor = page.get("next_cursor")
            if cursor is None:
                return markets
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise UpstreamError("Invalid or repeated event cursor")
            seen.add(cursor)
        raise UpstreamError("Market pagination limit reached")

    def trades_since(self, since):
        trades, seen = [], set()
        params = {
            "limit": self.settings.page_size,
            "taker_only": "true",
            "filter_type": "CASH",
            "filter_amount": self.settings.minimum_usd,
        }
        last_timestamp = None
        aliases = {
            "proxyWallet": "proxy_wallet",
            "conditionId": "condition_id",
            "asset": "token_id",
            "transactionHash": "transaction_hash",
        }
        for _ in range(1000):
            page = self.get(f"{DATA_API}/v2/trades", dict(params))
            if (
                not isinstance(page, dict)
                or not isinstance(page.get("data"), list)
                or not isinstance(page.get("pagination"), dict)
            ):
                raise UpstreamError("Invalid trades response")
            rows, pagination = page["data"], page["pagination"]
            try:
                timestamps = [int(row["timestamp"]) for row in rows]
            except (KeyError, TypeError, ValueError):
                raise UpstreamError("Invalid trade timestamp") from None
            if timestamps != sorted(timestamps, reverse=True) or (
                timestamps
                and last_timestamp is not None
                and timestamps[0] > last_timestamp
            ):
                raise UpstreamError("Trade feed is not ordered")
            cursor = pagination.get("next_cursor")
            if cursor is not None and (
                not isinstance(cursor, str) or not cursor or cursor in seen
            ):
                raise UpstreamError("Invalid or repeated trade cursor")
            if pagination.get("has_more") is not (cursor is not None):
                raise UpstreamError("Inconsistent trade pagination")
            for row, ts in zip(rows, timestamps):
                if ts >= since:
                    trades.append(
                        {
                            **row,
                            **{
                                target: row.get(source)
                                for target, source in aliases.items()
                            },
                        }
                    )
            if cursor is None or (timestamps and timestamps[-1] < since):
                return trades
            if not timestamps:
                raise UpstreamError("Empty trade page with continuation")
            seen.add(cursor)
            params["cursor"] = cursor
            last_timestamp = timestamps[-1]
        raise UpstreamError("Trade request budget exceeded; cursor was not advanced")

    def conditions(self, condition_ids):
        classified = {}
        for start in range(0, len(condition_ids), 50):
            chunk = condition_ids[start : start + 50]
            for closed in ("false", "true"):
                rows = self.get(
                    f"{GAMMA_API}/markets",
                    {
                        "condition_ids": chunk,
                        "closed": closed,
                        "include_tag": "true",
                        "limit": 100,
                    },
                )
                if not isinstance(rows, list):
                    raise UpstreamError("Invalid condition lookup response")
                for row in rows:
                    cid = row.get("conditionId")
                    if cid not in chunk:
                        raise UpstreamError("Unexpected condition lookup result")
                    events = row.get("events") or []
                    tags = list(row.get("tags") or [])
                    for event in events:
                        tags.extend(event.get("tags") or [])
                    slugs = {str(tag.get("slug") or "").lower() for tag in tags}
                    if "tags" not in row and not any(
                        "tags" in event for event in events
                    ):
                        continue
                    if slugs.intersection({"politics", "us-election"}):
                        slug = next(
                            (event["slug"] for event in events if event.get("slug")),
                            row.get("slug") or "",
                        )
                        classified[cid] = {
                            "question": str(row.get("question") or "Unknown market"),
                            "category": "Politics",
                            "link": f"https://polymarket.com/event/{slug}",
                        }
                    elif cid not in classified:
                        classified[cid] = None
        return classified

    def wallet_intel(self, wallet):
        result = {}
        try:
            profile = self.get(f"{GAMMA_API}/public-profile", {"address": wallet})
            if isinstance(profile, dict) and profile.get("createdAt"):
                result["account_created_ts"] = int(
                    datetime.fromisoformat(
                        profile["createdAt"].replace("Z", "+00:00")
                    ).timestamp()
                )
        except (UpstreamError, ValueError, TypeError):
            log.warning("Wallet profile unavailable")
        try:
            values = self.get(f"{DATA_API}/value", {"user": wallet})
            if not isinstance(values, list) or not values:
                raise ValueError("Invalid portfolio response")
            value = float(values[0]["value"])
            if not math.isfinite(value) or value < 0:
                raise ValueError("Invalid portfolio value")
            result["portfolio_value"] = value
        except (UpstreamError, ValueError, TypeError, KeyError):
            log.warning("Wallet valuation unavailable")
        return result
