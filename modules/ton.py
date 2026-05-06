"""
txfetch — modules/ton.py
ton / jetton adapter.

strategy:
  jetton (usdt, not, usdc): GET /v2/jettons/{id}/transfers — start_date/end_date, paginate via before_lt
  native ton: GET toncenter.com/api/v3/transactions — start_utime/end_utime, paginate via offset

memo (comment) is a native ton field stored in message_content.decoded.comment.
"""

from __future__ import annotations

import datetime
import time
from typing import Optional

import requests

from modules.models import TXQuery, TXCandidate, score_candidate

TONAPI_BASE    = "https://tonapi.io/v2"
TONCENTER_BASE = "https://toncenter.com/api/v3"

# jetton master addresses (extendable)
JETTON_MASTERS = {
    "USDT": "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id3bBH",
    "NOT":  "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM5MCi2",
    "USDC": "EQC61KHh0375V3vy9a8yKPjr_P3QxuBCGR3jTwIFTCCFmMRC",
}

# decimals per jetton
JETTON_DECIMALS = {
    "USDT": 6,
    "NOT":  9,
    "USDC": 6,
    "TON":  9,
}

PAGE_LIMIT = 100
MAX_PAGES  = 50

class TonAdapter:

    def __init__(self, api_key: Optional[str] = None,
                 min_confidence: float = 0.3):
        self.session = requests.Session()
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"
        self.min_confidence = min_confidence

    def fetch_candidates(self, query: TXQuery) -> list[TXCandidate]:
        coin = query.coin.upper()

        if coin == "TON":
            return self._fetch_native_ton(query)
        else:
            return self._fetch_jetton(query, coin)

    def _fetch_native_ton(self, query: TXQuery) -> list[TXCandidate]:
        """
        native ton via toncenter v3 /transactions.
        filters: start_utime / end_utime — no address required.
        """
        url = f"{TONCENTER_BASE}/transactions"
        params = {
            "start_utime": int(query.time_from.timestamp()),
            "end_utime":   int(query.time_to.timestamp()),
            "limit":       PAGE_LIMIT,
            "sort":        "asc",
            "offset":      0,
        }

        print(f"  [TON] fetching native ton transactions (toncenter v3)...")
        events = self._paginate_toncenter(url, params)
        print(f"  [TON] transactions received: {len(events)}")

        return self._score_transactions(events, query, decimals=9)

    def _fetch_jetton(self, query: TXQuery, coin: str) -> list[TXCandidate]:
        """
        Jetton: /v2/jettons/{jetton_id}/transfers
        jetton transfers via tonapi.
        params: start_date / end_date (unix seconds), paginate via before_lt.
        """
        jetton_id = JETTON_MASTERS.get(coin)
        if not jetton_id:
            print(f"  [TON] jetton {coin} not found. add its address to JETTON_MASTERS.")
            return []

        decimals = JETTON_DECIMALS.get(coin, 9)
        url = f"{TONAPI_BASE}/jettons/{jetton_id}/transfers"
        params = {
            "start_date": int(query.time_from.timestamp()),
            "end_date":   int(query.time_to.timestamp()),
            "limit":      PAGE_LIMIT,
            "direction":  "in",   # incoming transfers
        }

        print(f"  [TON] fetching {coin} jetton transfers...")
        transfers = self._paginate_jetton(url, params)
        print(f"  [TON] transfers received: {len(transfers)}")

        return self._score_jetton_transfers(transfers, query, coin, decimals)

    def _paginate_toncenter(self, url: str, params: dict) -> list[dict]:
        all_items: list[dict] = []

        for page in range(MAX_PAGES):
            try:
                resp = self.session.get(url, params=params, timeout=15)
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"  [TON] request error (page {page+1}): {e}")
                break

            body  = resp.json()
            items = body.get("transactions", [])
            all_items.extend(items)

            if len(items) < PAGE_LIMIT:
                break

            params["offset"] = params.get("offset", 0) + PAGE_LIMIT
            time.sleep(0.5)

        return all_items

    def _paginate_jetton(self, url: str, params: dict) -> list[dict]:
        all_transfers: list[dict] = []

        for page in range(MAX_PAGES):
            try:
                resp = self.session.get(url, params=params, timeout=15)
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"  [TON] request error (page {page+1}): {e}")
                break

            body      = resp.json()
            transfers = body.get("transfers", [])
            all_transfers.extend(transfers)

            # before_lt — logical time of last record → next page
            if len(transfers) < PAGE_LIMIT:
                break

            last_lt = transfers[-1].get("transaction_lt")
            if not last_lt:
                break

            params["before_lt"] = last_lt
            time.sleep(0.2)

        return all_transfers

    def _paginate_transactions(self, url: str, params: dict,
                               key: str) -> list[dict]:
        all_items: list[dict] = []

        for page in range(MAX_PAGES):
            try:
                resp = self.session.get(url, params=params, timeout=15)
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"  [TON] request error (page {page+1}): {e}")
                break

            body  = resp.json()
            items = body.get(key, [])
            all_items.extend(items)

            if len(items) < PAGE_LIMIT:
                break

            # cursor via before_lt of last record
            last_lt = items[-1].get("lt")
            if not last_lt:
                break

            params["before_lt"] = last_lt
            time.sleep(0.2)

        return all_items

    def _score_jetton_transfers(self, transfers: list[dict], query: TXQuery,
                                coin: str, decimals: int) -> list[TXCandidate]:
        candidates: list[TXCandidate] = []

        for t in transfers:
            # timestamp
            utime = t.get("timestamp") or t.get("utime")
            if not utime:
                continue
            event_ts = datetime.datetime.utcfromtimestamp(utime).replace(
                tzinfo=datetime.timezone.utc
            )

            # amount
            raw_amount = t.get("amount", "0")
            try:
                amount = int(raw_amount) / 10 ** decimals
            except (ValueError, TypeError):
                continue

            # memo / comment
            comment = t.get("comment") or None

            # sender / recipient
            sender    = _extract_address(t.get("sender"))
            recipient = _extract_address(t.get("recipient"))

            # tx hash
            tx_hash = t.get("transaction_hash") or t.get("hash", "")

            confidence, detail = score_candidate(event_ts, amount, comment, query)
            if confidence < self.min_confidence:
                continue

            candidates.append(TXCandidate(
                tx_id        = tx_hash,
                timestamp    = event_ts,
                amount       = amount,
                network      = "TON",
                coin         = coin,
                from_address = sender,
                to_address   = recipient,
                memo         = comment,
                confidence   = confidence,
                score_detail = detail,
            ))

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    def _score_transactions(self, txs: list[dict], query: TXQuery,
                            decimals: int) -> list[TXCandidate]:
        candidates: list[TXCandidate] = []

        for tx in txs:
            # toncenter v3: field now (unix time)
            utime = tx.get("now") or tx.get("utime")
            if not utime:
                continue
            event_ts = datetime.datetime.utcfromtimestamp(utime).replace(
                tzinfo=datetime.timezone.utc
            )

            # amount from in_msg.value (naneton)
            in_msg    = tx.get("in_msg") or {}
            raw_value = in_msg.get("value", 0)
            try:
                amount = int(raw_value) / 10 ** decimals
            except (ValueError, TypeError):
                continue

            # comment — toncenter v3: in_msg.message_content.decoded.comment
            comment = None
            msg_content = in_msg.get("message_content") or {}
            decoded     = msg_content.get("decoded") or {}
            comment     = decoded.get("comment") or decoded.get("text") or None

            tx_hash      = tx.get("hash", "")
            from_address = _extract_address(in_msg.get("source"))
            to_address   = _extract_address(tx.get("account"))

            confidence, detail = score_candidate(event_ts, amount, comment, query)
            if confidence < self.min_confidence:
                continue

            candidates.append(TXCandidate(
                tx_id        = tx_hash,
                timestamp    = event_ts,
                amount       = amount,
                network      = "TON",
                coin         = "TON",
                from_address = from_address,
                to_address   = to_address,
                memo         = comment,
                confidence   = confidence,
                score_detail = detail,
            ))

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

def _extract_address(obj) -> str:
    """extract address string from str or dict {address: ...}."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return obj.get("address") or obj.get("value") or ""
    return str(obj)