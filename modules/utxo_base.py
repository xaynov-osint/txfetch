"""
txfetch — modules/utxo_base.py
base class for utxo-based blockchain adapters (bitcoin, litecoin, dogecoin, etc).
contains shared logic: block height estimation, block fetching, tx pagination, scoring.
each network subclasses this with its own config.
"""

from __future__ import annotations

import datetime
import time
from typing import Optional

import requests

from modules.models import TXQuery, TXCandidate
from modules.matcher import find_matches
from modules import config

# default page size for block tx pagination
TX_PER_PAGE     = 25
MAX_TX_PAGES    = config.MAX_PAGES
MAX_BLOCKS      = 10
REQUEST_TIMEOUT = config.REQUEST_TIMEOUT


class UTXOBase:
    """
    base adapter for utxo networks.
    subclasses must define:
      NETWORK:       str   — display name (e.g. "LTC")
      API_BASE:      str   — mempool-compatible api base url
      COIN:          str   — coin ticker (e.g. "LTC")
      SATOSHI:       int   — smallest unit per coin (e.g. 100_000_000)
      BLOCK_TIME:    int   — average seconds per block (e.g. 150 for ltc, 60 for doge)
    """

    NETWORK:    str = ""
    API_BASE:   str = ""
    COIN:       str = ""
    SATOSHI:    int = 100_000_000
    BLOCK_TIME: int = 600   # seconds per block

    def __init__(self, min_confidence: float = 0.3):
        self.min_confidence = min_confidence
        self.session        = requests.Session()
        self.session.headers["User-Agent"] = "TXFetch/1.0"

    def fetch_candidates(self, query: TXQuery) -> list[TXCandidate]:
        if query.coin.upper() != self.COIN:
            print(f"  [{self.NETWORK}] only {self.COIN} is supported, got: {query.coin}")
            return []

        ts_from = int(query.time_from.timestamp())
        ts_to   = int(query.time_to.timestamp())

        print(f"  [{self.NETWORK}] estimating block height by timestamp...")
        tip_height = self._get_tip_height()
        if tip_height is None:
            print(f"  [{self.NETWORK}] could not get current tip height.")
            return []

        start_height = self._estimate_height(ts_from, tip_height)
        print(f"  [{self.NETWORK}] scanning blocks from height {start_height}...")

        blocks = self._collect_blocks_in_range(start_height, ts_from, ts_to)
        if not blocks:
            print(f"  [{self.NETWORK}] no blocks found in the given range.")
            return []

        print(f"  [{self.NETWORK}] blocks in range: {len(blocks)}")

        all_candidates: list[TXCandidate] = []
        for block in blocks:
            block_hash = block["id"]
            block_ts   = block["timestamp"]
            tx_count   = block.get("tx_count", 0)
            print(f"  [{self.NETWORK}] block {block['height']} ({tx_count} txs)...")
            txs        = self._fetch_block_txs(block_hash)
            candidates = self._filter_and_score(txs, block_ts, query)
            all_candidates.extend(candidates)

        all_candidates.sort(key=lambda c: c.confidence, reverse=True)
        return all_candidates

    def _get_tip_height(self) -> Optional[int]:
        try:
            resp = self.session.get(
                f"{self.API_BASE}/blocks/tip/height", timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            return int(resp.text.strip())
        except Exception as e:
            print(f"  [{self.NETWORK}] tip/height error: {e}")
            return None

    def _estimate_height(self, target_ts: int, tip_height: int) -> int:
        """estimate block height using average block time."""
        now_ts     = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        delta_sec  = now_ts - target_ts
        est_offset = delta_sec // self.BLOCK_TIME
        # start ABOVE the target (newer) with a buffer, then scan downwards
        return max(0, tip_height - est_offset + 5)

    def _collect_blocks_in_range(self, start_height: int,
                                  ts_from: int, ts_to: int) -> list[dict]:
        in_range: list[dict] = []
        height = start_height

        # correct the estimate: if the starting block is already older than
        # the window, climb up until we are above ts_to
        for _ in range(20):
            try:
                resp = self.session.get(
                    f"{self.API_BASE}/v1/blocks/{height}", timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
                probe = resp.json()
            except Exception:
                break
            if not probe:
                break
            newest_ts = probe[0].get("timestamp", 0)
            if newest_ts < ts_from:
                # estimate too low — climb up
                height = min(height + 10, probe[0]["height"] + 10)
                time.sleep(0.2)
            else:
                break

        for _ in range(MAX_BLOCKS + 15):
            try:
                resp = self.session.get(
                    f"{self.API_BASE}/v1/blocks/{height}", timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
                blocks = resp.json()
            except Exception as e:
                print(f"  [{self.NETWORK}] /v1/blocks/{height} error: {e}")
                break

            if not blocks:
                break

            for block in blocks:
                bts = block.get("timestamp", 0)
                if bts < ts_from:
                    return in_range
                if ts_from <= bts <= ts_to:
                    in_range.append(block)
                if len(in_range) >= MAX_BLOCKS:
                    return in_range

            height = blocks[-1]["height"]
            time.sleep(0.3)

        return in_range

    def _fetch_block_txs(self, block_hash: str) -> list[dict]:
        all_txs: list[dict] = []

        for page in range(MAX_TX_PAGES):
            start_index = page * TX_PER_PAGE
            try:
                url  = f"{self.API_BASE}/block/{block_hash}/txs/{start_index}"
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                txs  = resp.json()
            except Exception as e:
                print(f"  [{self.NETWORK}] block/txs/{start_index} error: {e}")
                break

            all_txs.extend(txs)
            if len(txs) < TX_PER_PAGE:
                break
            time.sleep(0.2)

        return all_txs

    def _filter_and_score(self, txs: list[dict], block_ts: int,
                          query: TXQuery) -> list[TXCandidate]:
        event_ts = datetime.datetime.utcfromtimestamp(block_ts).replace(
            tzinfo=datetime.timezone.utc
        )
        satoshi = self.SATOSHI

        def parser(tx):
            vout_list = tx.get("vout", [])
            total_sat = sum(
                v.get("value", 0) for v in vout_list
                if v.get("scriptpubkey_type") != "op_return"
            )
            amount = total_sat / satoshi

            # op_return → memo
            memo = None
            for vout in vout_list:
                if vout.get("scriptpubkey_type") == "op_return":
                    parts = vout.get("scriptpubkey_asm", "").split()
                    if len(parts) >= 2:
                        try:
                            memo = bytes.fromhex(parts[-1]).decode(
                                "utf-8", errors="ignore"
                            ).strip() or None
                        except ValueError:
                            pass
                    break

            vin_list     = tx.get("vin", [])
            from_address = ""
            if vin_list and not vin_list[0].get("is_coinbase"):
                from_address = vin_list[0].get("prevout", {}).get(
                    "scriptpubkey_address", ""
                )
            to_address = next(
                (v.get("scriptpubkey_address", "")
                 for v in vout_list
                 if v.get("scriptpubkey_type") != "op_return"),
                ""
            )
            return event_ts, amount, memo, from_address, to_address, tx.get("txid", "")

        return find_matches(txs, query, parser, self.NETWORK, self.min_confidence)