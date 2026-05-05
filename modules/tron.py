"""
txfetch — modules/tron.py
tron / usdt-trc20 adapter.

strategy:
  1. query contract events with min/max_block_timestamp
  2. paginate via fingerprint cursor
  3. filter by amount locally, score each candidate
"""

from __future__ import annotations

import time
from typing import Optional

import requests

from modules.models import TXQuery, TXCandidate, score_candidate

CONTRACTS = {
    "USDT": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    "USDC": "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8",
}

TRONGRID_EVENTS = "https://api.trongrid.io/v1/contracts/{contract}/events"
DECIMALS = {"USDT": 6, "USDC": 6}
PAGE_LIMIT = 200
MAX_PAGES  = 50

class TronUSDTAdapter:

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

        min_ts = int(query.time_from.timestamp() * 1000)
        max_ts = int(query.time_to.timestamp() * 1000)

        print(f"  [TRON] fetching {query.coin} events for time range...")
        events = self._paginate(contract, min_ts, max_ts)
        print(f"  [TRON] events received: {len(events)}")
        if events:
            import datetime
            first_ts = events[0].get("block_timestamp", 0)
            last_ts  = events[-1].get("block_timestamp", 0)
            first_dt = datetime.datetime.utcfromtimestamp(first_ts / 1000).strftime("%H:%M:%S")
            last_dt  = datetime.datetime.utcfromtimestamp(last_ts  / 1000).strftime("%H:%M:%S")
            print(f"  [TRON] events span: {first_dt} UTC → {last_dt} UTC")
            # check if target tx is in the batch
            target = "6d2902a3ad3da3afe8aaae870dc1b3af54d12c504eb184a8bdebd8eb871c2f33"
            found = [e for e in events if e.get("transaction_id") == target]
            print(f"  [TRON] target tx in batch: {'YES' if found else 'NO'}")

        return self._filter_and_score(events, query, decimals)

    def _paginate(self, contract: str, min_ts: int, max_ts: int) -> list[dict]:
        url = TRONGRID_EVENTS.format(contract=contract)
        params = {
            "event_name":        "Transfer",
            "only_confirmed":    "true",
            "min_block_timestamp": min_ts,
            "max_block_timestamp": max_ts,
            "limit":             PAGE_LIMIT,
            "order_by":          "block_timestamp,asc",
        }

        all_events: list[dict] = []

        for page in range(MAX_PAGES):
            try:
                resp = self.session.get(url, params=params, timeout=15)
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"  [TRON] request error (page {page+1}): {e}")
                break

            body   = resp.json()
            events = body.get("data", [])
            all_events.extend(events)

            fingerprint = body.get("meta", {}).get("fingerprint")
            if not fingerprint or len(events) < PAGE_LIMIT:
                break

            params["fingerprint"] = fingerprint
            time.sleep(1.0)

        return all_events

    def _filter_and_score(self, events: list[dict], query: TXQuery,
                          decimals: int) -> list[TXCandidate]:
        import datetime

        candidates: list[TXCandidate] = []

        for ev in events:
            result    = ev.get("result", {})
            raw_value = result.get("value")
            if raw_value is None:
                continue

            amount    = int(raw_value) / 10 ** decimals
            ts_ms     = ev.get("block_timestamp", 0)
            event_ts  = datetime.datetime.utcfromtimestamp(ts_ms / 1000).replace(
                tzinfo=datetime.timezone.utc
            )
            event_memo = None  # tron transfer does not carry memo

            confidence, detail = score_candidate(event_ts, amount, event_memo, query)
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