"""
txfetch — modules/eth.py
evm networks adapter (ethereum, bsc, base, ...).

strategy:
  1. convert timestamps to block numbers via getblocknobytime
  2. fetch token transfers via tokentx?contractaddress=...&startblock=X&endblock=Y
  3. filter by amount locally, score each candidate

multi-chain support via CHAIN_CONFIGS dictionary.
"""

from __future__ import annotations

import datetime
import time
from typing import Optional

import requests

from modules.models import TXQuery, TXCandidate, score_candidate

CHAIN_CONFIGS = {
    "ETH": {
        "api_url":  "https://api.etherscan.io/api",
        "chain_id": 1,
        "tokens": {
            "USDT": {"address": "0xdAC17F958D2ee523a2206206994597C13D831ec7", "decimals": 6},
            "USDC": {"address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
            "ETH":  {"address": None, "decimals": 18},  # native
        },
    },
    "BSC": {
        "api_url":  "https://api.bscscan.com/api",
        "chain_id": 56,
        "tokens": {
            "USDT": {"address": "0x55d398326f99059fF775485246999027B3197955", "decimals": 18},
            "USDC": {"address": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", "decimals": 18},
            "BNB":  {"address": None, "decimals": 18},
        },
    },
    "BASE": {
        "api_url":  "https://api.basescan.org/api",
        "chain_id": 8453,
        "tokens": {
            "USDC": {"address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "decimals": 6},
            "ETH":  {"address": None, "decimals": 18},
        },
    },
}

PAGE_OFFSET = 1000   # max records per page in etherscan
MAX_PAGES   = 10

class EVMAdapter:

    def __init__(self, api_key: Optional[str] = None,
                 network: str = "ETH",
                 min_confidence: float = 0.3):
        self.api_key        = api_key or "YourApiKeyToken"
        self.network        = network.upper()
        self.min_confidence = min_confidence
        self.session        = requests.Session()

        cfg = CHAIN_CONFIGS.get(self.network)
        if not cfg:
            raise ValueError(f"network {self.network} is not supported. available: {list(CHAIN_CONFIGS)}")
        self.api_url = cfg["api_url"]
        self.tokens  = cfg["tokens"]

    def fetch_candidates(self, query: TXQuery) -> list[TXCandidate]:
        coin = query.coin.upper()
        token_cfg = self.tokens.get(coin)
        if not token_cfg:
            print(f"  [EVM/{self.network}] coin {coin} not found. available: {list(self.tokens)}")
            return []

        contract  = token_cfg["address"]
        decimals  = token_cfg["decimals"]

        print(f"  [EVM/{self.network}] converting timestamps to blocks...")
        start_block = self._ts_to_block(int(query.time_from.timestamp()), "after")
        end_block   = self._ts_to_block(int(query.time_to.timestamp()),   "before")

        if start_block is None or end_block is None:
            print(f"  [EVM/{self.network}] could not determine block range.")
            return []

        print(f"  [EVM/{self.network}] blocks: {start_block} → {end_block}")

        if contract is None:
            # native eth/bnb — use txlist
            txs = self._fetch_native(start_block, end_block)
        else:
            txs = self._fetch_tokentx(contract, start_block, end_block)

        print(f"  [EVM/{self.network}] transactions received: {len(txs)}")

        return self._filter_and_score(txs, query, coin, decimals)

    def _ts_to_block(self, timestamp: int, closest: str) -> Optional[int]:
        """
        closest = 'before' | 'after'
        returns block number closest to timestamp.
        """
        params = {
            "module":    "block",
            "action":    "getblocknobytime",
            "timestamp": timestamp,
            "closest":   closest,
            "apikey":    self.api_key,
        }
        try:
            resp = self.session.get(self.api_url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "1":
                return int(data["result"])
        except Exception as e:
            print(f"  [EVM] getblocknobytime error: {e}")
        return None

    def _fetch_tokentx(self, contract: str,
                       start_block: int, end_block: int) -> list[dict]:
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
                "apikey":          self.api_key,
            }
            try:
                resp = self.session.get(self.api_url, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  [EVM] tokentx error (page {page}): {e}")
                break

            if data.get("status") != "1":
                # status=0 may mean "no results" — not an error
                break

            txs = data.get("result", [])
            all_txs.extend(txs)

            if len(txs) < PAGE_OFFSET:
                break  # last page

            time.sleep(0.25)   # rate limit: 5 req/sec on free key

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
                "apikey":     self.api_key,
            }
            try:
                resp = self.session.get(self.api_url, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  [EVM] txlist error (page {page}): {e}")
                break

            if data.get("status") != "1":
                break

            txs = data.get("result", [])
            # keep only successful txs
            txs = [t for t in txs if t.get("isError") == "0"]
            all_txs.extend(txs)

            if len(txs) < PAGE_OFFSET:
                break

            time.sleep(0.25)

        return all_txs

    def _filter_and_score(self, txs: list[dict], query: TXQuery,
                          coin: str, decimals: int) -> list[TXCandidate]:
        candidates: list[TXCandidate] = []

        for tx in txs:
            # timestamp
            ts = tx.get("timeStamp")
            if not ts:
                continue
            event_ts = datetime.datetime.utcfromtimestamp(int(ts)).replace(
                tzinfo=datetime.timezone.utc
            )

            # amount
            raw_value = tx.get("value", "0")
            try:
                amount = int(raw_value) / 10 ** decimals
            except (ValueError, TypeError):
                continue

            # evm does not support memo in standard transfer
            # input field may contain data but it is not human-readable text
            memo = None

            tx_hash      = tx.get("hash", "")
            from_address = tx.get("from", "")
            to_address   = tx.get("to", "")

            confidence, detail = score_candidate(event_ts, amount, memo, query)
            if confidence < self.min_confidence:
                continue

            candidates.append(TXCandidate(
                tx_id        = tx_hash,
                timestamp    = event_ts,
                amount       = amount,
                network      = self.network,
                coin         = coin,
                from_address = from_address,
                to_address   = to_address,
                memo         = None,
                confidence   = confidence,
                score_detail = detail,
            ))

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates