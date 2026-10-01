import logging
from datetime import datetime
import math
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)
DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
KNOWN_WALLETS = {
    "0xa9d1e08c7793af67e9d92fe3028ac693eb80b7d0": "Coinbase",
    "0x503828976d22510aad0201ac7ec88293211d23da": "Coinbase",
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "Binance Hot Wallet",
    "0x12d66f87a04a9e220743712ce6d9bb1b5616b438": "Tornado Cash",
    "0x4a14347083b80e5216ca31350a2d21702ac3650d": "Wintermute",
}


class UpstreamError(RuntimeError):
    pass


class Client:
    def __init__(self, settings, session=None):
        self.settings = settings
        self.session = session or requests.Session()
        if session is None:
            retry = Retry(total=2, backoff_factor=.5, status_forcelist=(429, 500, 502, 503, 504),
                          allowed_methods=("GET",), respect_retry_after_header=False)
            self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def get(self, url, params=None):
        try:
            response = self.session.get(url, params=params, timeout=(5, 15))
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            raise UpstreamError("Upstream request failed") from None

    def markets(self):
        markets = {}
        for offset in range(0, self.settings.max_offset + 1, 100):
            events = self.get(f"{GAMMA_API}/events", {
                "active": "true", "closed": "false", "limit": 100, "offset": offset})
            if not isinstance(events, list):
                raise UpstreamError("Invalid events response")
            for event in events:
                tags = {str(t.get("slug") or "").lower() for t in event.get("tags", [])}
                political = bool(tags.intersection({"politics", "us-election"}))
                slug = str(event.get("slug") or "")
                for market in event.get("markets", []):
                    cid = market.get("conditionId")
                    if cid:
                        metadata = {"question": str(market.get("question") or "Unknown market"),
                                    "category": "Politics", "link": f"https://polymarket.com/event/{slug}"}
                        if political or cid not in markets:
                            markets[cid] = metadata if political else None
            if len(events) < 100:
                if not any(markets.values()):
                    raise UpstreamError("No political markets found; refusing to discard trades")
                return markets
        raise UpstreamError("Market pagination limit reached")

    def trades_since(self, since):
        return self._trade_window(max(1, since), int(time.time()), [0])

    def conditions(self, condition_ids):
        classified = {}
        for start in range(0, len(condition_ids), 50):
            chunk = condition_ids[start:start + 50]
            for closed in ("false", "true"):
                rows = self.get(f"{GAMMA_API}/markets", {
                    "condition_ids": chunk, "closed": closed, "include_tag": "true", "limit": 100})
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
                    if "tags" not in row and not any("tags" in event for event in events):
                        continue
                    if slugs.intersection({"politics", "us-election"}):
                        slug = next((event["slug"] for event in events if event.get("slug")), row.get("slug") or "")
                        classified[cid] = {"question": str(row.get("question") or "Unknown market"),
                                           "category": "Politics", "link": f"https://polymarket.com/event/{slug}"}
                    elif cid not in classified:
                        classified[cid] = None
        return classified

    def _trade_window(self, since, end, budget):
        trades = []
        step = max(1, self.settings.page_size // 2)
        for offset in range(0, self.settings.max_offset + 1, step):
            budget[0] += 1
            if budget[0] > 1000:
                raise UpstreamError("History request budget exceeded; cursor was not advanced")
            page = self.get(f"{DATA_API}/trades", {
                "limit": self.settings.page_size, "offset": offset, "takerOnly": "true",
                "start": since, "end": end, "filterType": "CASH", "filterAmount": self.settings.minimum_usd})
            if not isinstance(page, list):
                raise UpstreamError("Invalid trades response")
            try:
                timestamps = [int(t["timestamp"]) for t in page]
            except (KeyError, TypeError, ValueError):
                raise UpstreamError("Invalid trade timestamp") from None
            if any(ts < since or ts > end for ts in timestamps):
                raise UpstreamError("Upstream did not honor requested history window")
            trades.extend(page)
            if len(page) < self.settings.page_size:
                return trades
        if since >= end:
            raise UpstreamError("Too many trades in one second; cursor was not advanced")
        middle = (since + end) // 2
        return self._trade_window(since, middle, budget) + self._trade_window(middle + 1, end, budget)

    def wallet_intel(self, wallet):
        result = {}
        try:
            profile = self.get(f"{GAMMA_API}/public-profile", {"address": wallet})
            if isinstance(profile, dict) and profile.get("createdAt"):
                result["account_created_ts"] = int(datetime.fromisoformat(
                    profile["createdAt"].replace("Z", "+00:00")).timestamp())
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
        if self.settings.etherscan_key:
            try:
                response = self.get("https://api.etherscan.io/v2/api", {
                    "chainid": 137, "module": "account", "action": "txlist", "address": wallet,
                    "startblock": 0, "endblock": 99999999, "page": 1, "offset": 10,
                    "sort": "asc", "apikey": self.settings.etherscan_key})
                if not isinstance(response, dict) or response.get("status") != "1":
                    raise ValueError("Funding response unavailable")
                incoming = [t for t in response["result"] if t.get("to", "").lower() == wallet
                            and t.get("isError") == "0" and int(t.get("value", 0)) > 0]
                if incoming:
                    sender = incoming[0]["from"].lower()
                    result["funding_source"] = "Observed sender: " + KNOWN_WALLETS.get(sender, sender)
            except (UpstreamError, ValueError, TypeError, KeyError):
                log.warning("Funding lookup unavailable")
        return result
