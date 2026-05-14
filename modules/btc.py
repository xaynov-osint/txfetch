"""
txfetch — modules/btc.py
bitcoin adapter via mempool.space (free, no key required).

strategy:
  1. estimate block height from timestamp using tip_height - delta/600
  2. collect blocks whose timestamp falls within time_from..time_to
  3. paginate block txs via /api/block/:hash/txs/:start_index (25 tx per call)
  4. filter vout by amount locally, score each candidate

bitcoin does not support memo in standard p2pkh/p2wpkh transactions.
op_return may contain arbitrary data — extracted if present.
"""

from __future__ import annotations

import datetime
import time
from typing import Optional

import requests

from modules.models import TXQuery, TXCandidate, score_candidate

MEMPOOL_API   = "https://mempool.space/api"
SATOSHI       = 100_000_000   # 1 btc = 100_000_000 satoshi
TX_PER_PAGE   = 25            # mempool.space returns 25 tx per call
MAX_TX_PAGES  = 40            # guard: no more than 1000 tx per block
MAX_BLOCKS        = 10     # max blocks in range (btc ~10 min/block)

class BTCAdapter:

    def __init__(self, min_confidence: float = 0.3):
        self.session        = requests.Session()
        self.session.headers["User-Agent"] = "TXFetch/1.0"
        self.min_confidence = min_confidence

    def fetch_candidates(self, query: TXQuery) -> list[TXCandidate]:
        if query.coin.upper() != "BTC":
            print(f"  [BTC] only BTC is supported, got: {query.coin}")
            return []

        ts_from = int(query.time_from.timestamp())
        ts_to   = int(query.time_to.timestamp())

        print("  [BTC] estimating block height by timestamp...")
        tip_height = self._get_tip_height()
        if tip_height is None:
            print("  [BTC] could not get current tip height.")
            return []

        start_height = self._find_block_height_by_ts(ts_from, tip_height)
        if start_height is None:
            print("  [BTC] could not find block for given timestamp.")
            return []

        print(f"  [BTC] scanning blocks from height {start_height}...")
        blocks_in_range = self._collect_blocks_in_range(
            start_height, ts_from, ts_to
        )

        if not blocks_in_range:
            print("  [BTC] no blocks found in the given range.")
            return []

        print(f"  [BTC] blocks in range: {len(blocks_in_range)}")

        all_candidates: list[TXCandidate] = []
        for block in blocks_in_range:
            block_hash = block["id"]
            block_ts   = block["timestamp"]
            tx_count   = block.get("tx_count", 0)
            print(f"  [BTC] block {block['height']} ({tx_count} txs)...")

            txs = self._fetch_block_txs(block_hash)
            candidates = self._filter_and_score(txs, block_ts, query)
            all_candidates.extend(candidates)

        all_candidates.sort(key=lambda c: c.confidence, reverse=True)
        return all_candidates

    def _get_tip_height(self) -> Optional[int]:
        try:
            resp = self.session.get(
                f"{MEMPOOL_API}/blocks/tip/height", timeout=10
            )
            resp.raise_for_status()
            return int(resp.text.strip())
        except Exception as e:
            print(f"  [BTC] blocks/tip/height error: {e}")
            return None

    def _find_block_height_by_ts(self, target_ts: int,
                                  tip_height: int) -> Optional[int]:
        """
        estimate block height from timestamp.
        bitcoin produces ~1 block per 10 min (600 sec).
        """
        # estimated offset from tip
        now_ts    = int(datetime.datetime.utcnow().timestamp())
        delta_sec = now_ts - target_ts
        est_offset = delta_sec // 600         # ~600 sec per block
        est_height = max(0, tip_height - est_offset - 5)  # -5 blocks buffer

        return int(est_height)

    def _collect_blocks_in_range(self, start_height: int,
                                  ts_from: int, ts_to: int) -> list[dict]:
        """
        fetch blocks in batches of 10 from start_height.
        stops when block timestamp is older than ts_from.
        """
        in_range: list[dict] = []
        height   = start_height

        for _ in range(MAX_BLOCKS + 5):
            try:
                resp = self.session.get(
                    f"{MEMPOOL_API}/v1/blocks/{height}", timeout=15
                )
                resp.raise_for_status()
                blocks = resp.json()
            except Exception as e:
                print(f"  [BTC] /v1/blocks/{height} error: {e}")
                break

            if not blocks:
                break

            for block in blocks:
                bts = block.get("timestamp", 0)
                if bts < ts_from:
                    # blocks go newest to oldest — stop if older than ts_from
                    return in_range
                if ts_from <= bts <= ts_to:
                    in_range.append(block)
                if len(in_range) >= MAX_BLOCKS:
                    return in_range

            # next batch — height of last block in batch
            height = blocks[-1]["height"]
            time.sleep(0.3)

        return in_range

    def _fetch_block_txs(self, block_hash: str) -> list[dict]:
        all_txs: list[dict] = []

        for page in range(MAX_TX_PAGES):
            start_index = page * TX_PER_PAGE
            try:
                url  = f"{MEMPOOL_API}/block/{block_hash}/txs/{start_index}"
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
                txs  = resp.json()
            except Exception as e:
                print(f"  [BTC] block/txs/{start_index} error: {e}")
                break

            all_txs.extend(txs)

            if len(txs) < TX_PER_PAGE:
                break  # last page

            time.sleep(0.2)

        return all_txs

    def _search_mempool(self, query: TXQuery) -> list[TXCandidate]:
        """
        get all txids from mempool, batch-check first-seen timestamps,
        filter by time window, fetch full data for matching txs.
        """
        # 1. all txids in mempool
        try:
            resp = self.session.get(f"{MEMPOOL_API}/mempool/txids", timeout=20)
            resp.raise_for_status()
            all_txids: list[str] = resp.json()
        except Exception as e:
            print(f"  [BTC] mempool unavailable: {e}")
            return []

        print(f"  [BTC] txs in mempool: {len(all_txids)}, checking timestamps...")

        ts_from = int(query.time_from.timestamp())
        ts_to   = int(query.time_to.timestamp())

        # limit to avoid hanging forever
        all_txids = all_txids[:MEMPOOL_MAX_TXIDS]

        # 2. get first-seen timestamps in batches
        matching_txids: list[str] = []
        for i in range(0, len(all_txids), MEMPOOL_CHUNK):
            batch = all_txids[i:i + MEMPOOL_CHUNK]
            params = [("txId[]", txid) for txid in batch]
            try:
                resp = self.session.get(
                    f"{MEMPOOL_API}/v1/transaction-times",
                    params=params, timeout=15
                )
                resp.raise_for_status()
                times: list[int] = resp.json()
            except Exception as e:
                print(f"  [BTC] transaction-times error: {e}")
                continue

            for txid, ts in zip(batch, times):
                if ts and ts_from <= ts <= ts_to:
                    matching_txids.append(txid)

            time.sleep(0.3)

        if not matching_txids:
            print("  [BTC] no mempool txs matched the time window.")
            return []

        print(f"  [BTC] mempool candidates in time window: {len(matching_txids)}")

        # 3. fetch full data and score each
        candidates: list[TXCandidate] = []
        now_ts = int(datetime.datetime.utcnow().timestamp())

        for txid in matching_txids:
            try:
                resp = self.session.get(
                    f"{MEMPOOL_API}/tx/{txid}", timeout=15
                )
                resp.raise_for_status()
                tx = resp.json()
            except Exception as e:
                print(f"  [BTC] /tx/{txid[:16]}... error: {e}")
                continue

            # timestamp — use window center (tx not yet confirmed)
            event_ts = query.time_from.replace(
                second=(query.time_from.second + query.time_to.second) // 2
            )

            vout_list = tx.get("vout", [])
            total_sat = sum(
                v.get("value", 0) for v in vout_list
                if v.get("scriptpubkey_type") != "op_return"
            )
            amount_btc = total_sat / SATOSHI

            memo = None
            for vout in vout_list:
                if vout.get("scriptpubkey_type") == "op_return":
                    asm = vout.get("scriptpubkey_asm", "")
                    parts = asm.split()
                    if len(parts) >= 2:
                        try:
                            memo = bytes.fromhex(parts[-1]).decode(
                                "utf-8", errors="ignore").strip() or None
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

            confidence, detail = score_candidate(
                event_ts, amount_btc, memo, query
            )
            if confidence < self.min_confidence:
                continue

            candidates.append(TXCandidate(
                tx_id        = txid,
                timestamp    = event_ts,
                amount       = amount_btc,
                network      = "BTC",
                coin         = "BTC",
                from_address = from_address,
                to_address   = to_address,
                memo         = memo,
                confidence   = confidence,
                score_detail = {**detail, "source": "mempool"},
            ))

            time.sleep(0.1)

        return candidates

    def _filter_and_score(self, txs: list[dict], block_ts: int,
                          query: TXQuery) -> list[TXCandidate]:
        event_ts = datetime.datetime.utcfromtimestamp(block_ts).replace(
            tzinfo=datetime.timezone.utc
        )
        candidates: list[TXCandidate] = []

        for tx in txs:
            txid = tx.get("txid", "")

            vout_list = tx.get("vout", [])
            total_sat = sum(v.get("value", 0) for v in vout_list
                            if v.get("scriptpubkey_type") != "op_return")
            amount_btc = total_sat / SATOSHI

            memo = None
            for vout in vout_list:
                if vout.get("scriptpubkey_type") == "op_return":
                    asm = vout.get("scriptpubkey_asm", "")
                    # op_return <hex> → decode hex to utf-8 if possible
                    parts = asm.split()
                    if len(parts) >= 2:
                        try:
                            memo = bytes.fromhex(parts[-1]).decode("utf-8",
                                                                   errors="ignore")
                            memo = memo.strip() or None
                        except ValueError:
                            pass
                    break

            vin_list     = tx.get("vin", [])
            from_address = ""
            if vin_list and not vin_list[0].get("is_coinbase"):
                prevout = vin_list[0].get("prevout", {})
                from_address = prevout.get("scriptpubkey_address", "")

            # first non-op_return vout → recipient
            to_address = ""
            for vout in vout_list:
                if vout.get("scriptpubkey_type") != "op_return":
                    to_address = vout.get("scriptpubkey_address", "")
                    break

            confidence, detail = score_candidate(
                event_ts, amount_btc, memo, query
            )
            if confidence < self.min_confidence:
                continue

            candidates.append(TXCandidate(
                tx_id        = txid,
                timestamp    = event_ts,
                amount       = amount_btc,
                network      = "BTC",
                coin         = "BTC",
                from_address = from_address,
                to_address   = to_address,
                memo         = memo,
                confidence   = confidence,
                score_detail = detail,
            ))

        return candidates