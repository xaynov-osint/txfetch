"""
txfetch — modules/tron.py
tron adapter (usdt, usdc — trc20).

strategy:
  1. query contract events with min/max_block_timestamp
  2. paginate via fingerprint cursor
  3. filter by amount locally, score each candidate
"""

from __future__ import annotations

import datetime
import time
from typing import Optional

import requests

from modules.models import TXQuery, TXCandidate, score_candidate

CONTRACTS = {
    "USDT": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    "USDC": "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8",
}

TRONGRID_EVENTS = "https://api.trongrid.io/v1/contracts/{contract}/events"
DECIMALS        = {"USDT": 6, "USDC": 6}
PAGE_LIMIT      = 200
MAX_PAGES       = 50
REQUEST_TIMEOUT = 15
RETRY_ATTEMPTS  = 3
RETRY_DELAY     = 2.0
PAGE_DELAY      = 1.0


class TronAdapter:

    def __init__(self, api_key: Optional[str] = None,
                 min_confidence: float = 0.4):
        self.session = requests.Session()
        if api_key:
            self.session.headers["TRON-PRO-API-KEY"] = api_key
        self.min_confidence = min_confidence

    def fetch_candidates(self, query: TXQuery) -> list[TXCandidate]:
        contract = CONTRACTS.get(query.coin.upper())
        if not contract:
            print(f"  [TRON] coin {query.coin} is not supported.")
            return []

        decimals = DECIMALS.get(query.coin.upper(), 6)
        min_ts   = int(query.time_from.timestamp() * 1000)
        max_ts   = int(query.time_to.timestamp() * 1000)

        print(f"  [TRON] fetching {query.coin} events for time range...")
        events = self._paginate(contract, min_ts, max_ts)
        print(f"  [TRON] events received: {len(events)}")

        return self._filter_and_score(events, query, decimals)

    def _paginate(self, contract: str, min_ts: int, max_ts: int) -> list[dict]:
        url = TRONGRID_EVENTS.format(contract=contract)
        params = {
            "event_name":          "Transfer",
            "only_confirmed":      "true",
            "min_block_timestamp": min_ts,
            "max_block_timestamp": max_ts,
            "limit":               PAGE_LIMIT,
            "order_by":            "block_timestamp,asc",
        }

        all_events: list[dict] = []

        for page in range(MAX_PAGES):
            resp = self._get_with_retry(url, params, page + 1)
            if resp is None:
                print(f"  [TRON] stopping at page {page + 1} — results may be incomplete.")
                break

            body   = resp.json()
            events = body.get("data", [])
            all_events.extend(events)

            fingerprint = body.get("meta", {}).get("fingerprint")
            if not fingerprint or len(events) < PAGE_LIMIT:
                break

            params["fingerprint"] = fingerprint
            time.sleep(PAGE_DELAY)

        return all_events

    def _get_with_retry(self, url: str, params: dict,
                        page: int) -> requests.Response | None:
        """attempt request up to RETRY_ATTEMPTS times before giving up."""
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                resp = self.session.get(url, params=params,
                                        timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                print(f"  [TRON] error (page {page}, attempt {attempt}/{RETRY_ATTEMPTS}): {e}")
                if attempt < RETRY_ATTEMPTS:
                    time.sleep(RETRY_DELAY)
        return None

    def _filter_and_score(self, events: list[dict], query: TXQuery,
                          decimals: int) -> list[TXCandidate]:
        candidates: list[TXCandidate] = []

        for ev in events:
            result    = ev.get("result", {})
            raw_value = result.get("value")
            if raw_value is None:
                continue

            amount   = int(raw_value) / 10 ** decimals
            ts_ms    = ev.get("block_timestamp", 0)
            event_ts = datetime.datetime.utcfromtimestamp(ts_ms / 1000).replace(
                tzinfo=datetime.timezone.utc
            )

            confidence, detail = score_candidate(event_ts, amount, None, query)
            if confidence < self.min_confidence:
                continue

            candidates.append(TXCandidate(
                tx_id        = ev.get("transaction_id", ""),
                timestamp    = event_ts,
                amount       = amount,
                network      = "TRON",
                coin         = query.coin.upper(),
                from_address = result.get("from", ""),
                to_address   = result.get("to", ""),
                memo         = None,
                confidence   = confidence,
                score_detail = detail,
            ))

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates
