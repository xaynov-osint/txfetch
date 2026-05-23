"""
txfetch — modules/evm_base.py
base class for all evm-compatible network adapters.
contains shared logic: timestamp→block conversion, tokentx/txlist fetching, scoring.
each network (eth, bsc, base) subclasses this with its own config.
"""

from __future__ import annotations

import datetime
import time
from typing import Optional

import requests

from modules.models import TXQuery, TXCandidate
from modules.matcher import find_matches
from modules import config

PAGE_OFFSET     = 1000
MAX_PAGES       = 10
REQUEST_TIMEOUT = config.REQUEST_TIMEOUT
PAGE_DELAY      = config.PAGE_DELAY


class EVMBase:
    """
    base evm adapter. subclasses must define:
      - NETWORK:  str        — display name (e.g. "ETH")
      - API_URL:  str        — block explorer api base url
      - TOKENS:   dict       — {coin: {address, decimals}}
      - API_KEY:  str | None — api key from config
    """

    NETWORK: str       = ""
    API_URL: str       = ""
    TOKENS:  dict      = {}
    API_KEY: str | None = None

    def __init__(self, min_confidence: float = 0.3):
        self.min_confidence = min_confidence
        self.session        = requests.Session()

    def fetch_candidates(self, query: TXQuery) -> list[TXCandidate]:
        coin      = query.coin.upper()
        token_cfg = self.TOKENS.get(coin)
        if not token_cfg:
            print(f"  [{self.NETWORK}] coin {coin} not found. available: {list(self.TOKENS)}")
            return []

        contract = token_cfg["address"]
        decimals = token_cfg["decimals"]

        print(f"  [{self.NETWORK}] converting timestamps to blocks...")
        start_block = self._ts_to_block(int(query.time_from.timestamp()), "after")
        end_block   = self._ts_to_block(int(query.time_to.timestamp()),   "before")

        if start_block is None or end_block is None:
            print(f"  [{self.NETWORK}] could not determine block range.")
            return []

        print(f"  [{self.NETWORK}] blocks: {start_block} → {end_block}")

        if contract is None:
            txs = self._fetch_native(start_block, end_block)
        else:
            txs = self._fetch_tokentx(contract, start_block, end_block)

        print(f"  [{self.NETWORK}] transactions received: {len(txs)}")
        return self._filter_and_score(txs, query, coin, decimals)

    def _ts_to_block(self, timestamp: int, closest: str) -> Optional[int]:
        params = {
            "module":    "block",
            "action":    "getblocknobytime",
            "timestamp": timestamp,
            "closest":   closest,
            "apikey":    self.API_KEY or "YourApiKeyToken",
        }
        try:
            resp = self.session.get(self.API_URL, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "1":
                return int(data["result"])
        except Exception as e:
            print(f"  [{self.NETWORK}] getblocknobytime error: {e}")
        return None

    def _fetch_tokentx(self, contract: str, start_block: int, end_block: int) -> list[dict]:
        all_txs: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            params = {
                "module":          "account",
                "action":          "tokentx",
                "contractaddress": contract,
                "startblock":      start_block,
                "endblock":        end_block,
                "page":            page,
                "offset":          PAGE_OFFSET,
                "sort":            "asc",
                "apikey":          self.API_KEY or "YourApiKeyToken",
            }
            try:
                resp = self.session.get(self.API_URL, params=params, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  [{self.NETWORK}] tokentx error (page {page}): {e}")
                break
            if data.get("status") != "1":
                break
            txs = data.get("result", [])
            all_txs.extend(txs)
            if len(txs) < PAGE_OFFSET:
                break
            time.sleep(PAGE_DELAY)
        return all_txs

    def _fetch_native(self, start_block: int, end_block: int) -> list[dict]:
        all_txs: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            params = {
                "module":     "account",
                "action":     "txlist",
                "startblock": start_block,
                "endblock":   end_block,
                "page":       page,
                "offset":     PAGE_OFFSET,
                "sort":       "asc",
                "apikey":     self.API_KEY or "YourApiKeyToken",
            }
            try:
                resp = self.session.get(self.API_URL, params=params, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  [{self.NETWORK}] txlist error (page {page}): {e}")
                break
            if data.get("status") != "1":
                break
            txs = [t for t in data.get("result", []) if t.get("isError") == "0"]
            all_txs.extend(txs)
            if len(txs) < PAGE_OFFSET:
                break
            time.sleep(PAGE_DELAY)
        return all_txs

    def _filter_and_score(self, txs: list[dict], query: TXQuery,
                          coin: str, decimals: int) -> list[TXCandidate]:
        def parser(tx):
            ts = tx.get("timeStamp")
            if not ts:
                return None
            event_ts = datetime.datetime.utcfromtimestamp(int(ts)).replace(
                tzinfo=datetime.timezone.utc
            )
            try:
                amount = int(tx.get("value", "0")) / 10 ** decimals
            except (ValueError, TypeError):
                return None
            return event_ts, amount, None, tx.get("from", ""), tx.get("to", ""), tx.get("hash", "")

        return find_matches(txs, query, parser, self.NETWORK, self.min_confidence)
