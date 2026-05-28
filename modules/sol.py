"""
txfetch — modules/solana.py
solana adapter for spl token transfers.

strategy:
  1. resolve token mint address from coin name
  2. fetch signatures for mint address via getSignaturesForAddress (public rpc or helius)
  3. filter signatures by blockTime within time window
  4. fetch full transaction details for each matching signature
  5. parse spl token transfer amounts, score and return candidates

memo: solana supports memo program — extracted if present.
helius api key from config improves rate limits significantly.
"""

from __future__ import annotations

import datetime
import time
from typing import Optional

import requests

from modules.models import TXQuery, TXCandidate
from modules.matcher import find_matches
from modules import config

# ── endpoints ─────────────────────────────────────────────────────────────────

PUBLIC_RPC  = "https://api.mainnet-beta.solana.com"
HELIUS_RPC  = "https://mainnet.helius-rpc.com/?api-key={key}"

# ── spl token mints ───────────────────────────────────────────────────────────

# primary mint addresses (Token program)
TOKEN_MINTS = {
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "RAY":  "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    "JUP":  "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "SOL":  None,   # native — handled separately
}

# token-2022 alternative mints — checked in parallel for dual-standard tokens
TOKEN_MINTS_2022 = {
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # same for now, placeholder for future
}

TOKEN_DECIMALS = {
    "USDC": 6,
    "USDT": 6,
    "RAY":  6,
    "JUP":  6,
    "SOL":  9,   # 1 SOL = 1_000_000_000 lamports
}

# ── token program addresses ───────────────────────────────────────────────────

SPL_TOKEN_PROGRAM     = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
SPL_TOKEN_2022        = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
MEMO_PROGRAM          = "Mem_oMoDT32neJCDXJaFi6uiUCt8f6FUXUcLv57297Bc"
MEMO_PROGRAM_V1       = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"

PAGE_LIMIT      = 100
MAX_PAGES       = 20
REQUEST_TIMEOUT = config.REQUEST_TIMEOUT
PAGE_DELAY      = 0.5


class SolanaAdapter:

    def __init__(self, min_confidence: float = 0.3):
        self.min_confidence = min_confidence
        self.session        = requests.Session()
        self.session.headers["Content-Type"] = "application/json"

        # use helius if key available, else public rpc
        key = config.get("HELIUS_API_KEY")
        self.rpc_url = HELIUS_RPC.format(key=key) if key else PUBLIC_RPC
        self.has_key = bool(key)

    def _get_mint_decimals(self, mint: str) -> int:
        """
        fetch decimals for unknown mint via getMintInfo rpc call.
        falls back to 6 if request fails — logs a warning.
        """
        resp = self._rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        if resp:
            try:
                decimals = (resp["result"]["value"]["data"]
                               ["parsed"]["info"]["decimals"])
                return int(decimals)
            except (KeyError, TypeError):
                pass
        print(f"  [SOL] could not fetch decimals for {mint[:8]}... — using 6 as fallback")
        return 6

    def fetch_candidates(self, query: TXQuery) -> list[TXCandidate]:
        coin = query.coin.upper()

        if coin not in TOKEN_MINTS:
            print(f"  [SOL] coin {coin} not supported. available: {list(TOKEN_MINTS)}")
            return []

        decimals = TOKEN_DECIMALS.get(coin)
        mint     = TOKEN_MINTS[coin]

        # fetch decimals dynamically if not hardcoded
        if decimals is None:
            decimals = self._get_mint_decimals(mint)

        ts_from = int(query.time_from.timestamp())
        ts_to   = int(query.time_to.timestamp())

        if coin == "SOL":
            return self._fetch_native_sol(query, ts_from, ts_to, decimals)

        print(f"  [SOL] fetching {coin} signatures for mint {mint[:8]}...")
        sigs = self._get_signatures_in_range(mint, ts_from, ts_to)

        # dual mint: check token-2022 address if available
        mint_2022 = TOKEN_MINTS_2022.get(coin)
        if mint_2022 and mint_2022 != mint:
            print(f"  [SOL] also checking token-2022 mint...")
            sigs_2022 = self._get_signatures_in_range(mint_2022, ts_from, ts_to)
            # merge deduplicating by signature
            seen = set(sigs)
            sigs += [s for s in sigs_2022 if s not in seen]

        print(f"  [SOL] signatures in range: {len(sigs)}")

        if not sigs:
            return []

        print(f"  [SOL] fetching transaction details...")
        txs = self._fetch_transactions(sigs, coin, mint, decimals)
        print(f"  [SOL] transactions parsed: {len(txs)}")

        return find_matches(txs, query, lambda t: t, "SOL", self.min_confidence)

    # ── signatures ────────────────────────────────────────────────────────────

    def _get_signatures_in_range(self, address: str,
                                  ts_from: int, ts_to: int) -> list[str]:
        """
        fetch signatures for address, stop when blockTime < ts_from.
        returns list of signatures within the time window.
        """
        all_sigs: list[str] = []
        before   = None

        for page in range(MAX_PAGES):
            params: dict = {
                "limit":      PAGE_LIMIT,
                "commitment": "finalized",
            }
            if before:
                params["before"] = before

            resp = self._rpc("getSignaturesForAddress", [address, params])
            if resp is None:
                break

            sigs = resp.get("result", [])
            if not sigs:
                break

            for s in sigs:
                bt = s.get("blockTime", 0)
                if bt < ts_from:
                    # older than window — stop
                    return all_sigs
                if ts_from <= bt <= ts_to:
                    if not s.get("err"):   # skip failed txs
                        all_sigs.append(s["signature"])

            before = sigs[-1]["signature"]
            time.sleep(PAGE_DELAY)

        return all_sigs

    # ── transaction details ───────────────────────────────────────────────────

    def _fetch_transactions(self, signatures: list[str], coin: str,
                            mint: str, decimals: int) -> list[tuple]:
        """
        fetch full tx details and parse spl token transfer amount.
        if helius key available — uses enhanced transactions api (faster, pre-parsed).
        otherwise falls back to standard rpc getTransaction.
        """
        if self.has_key:
            return self._fetch_helius_enhanced(signatures, mint, decimals)
        return self._fetch_rpc_transactions(signatures, mint, decimals)

    def _fetch_helius_enhanced(self, signatures: list[str],
                               mint: str, decimals: int) -> list[tuple]:
        """
        helius enhanced transactions api — returns pre-parsed transfer data.
        much faster than standard rpc: tokenAmount, fromUser, toUser, memo included.
        """
        key     = config.get("HELIUS_API_KEY")
        url     = f"https://api.helius.xyz/v0/transactions?api-key={key}"
        results = []

        # helius accepts up to 100 signatures per request
        chunk_size = 100
        for i in range(0, len(signatures), chunk_size):
            chunk = signatures[i:i + chunk_size]
            try:
                resp = self.session.post(url, json={"transactions": chunk},
                                         timeout=config.REQUEST_TIMEOUT)
                resp.raise_for_status()
                txs = resp.json()
            except Exception as e:
                print(f"  [SOL] helius enhanced error: {e}")
                continue

            for tx in txs:
                parsed = self._parse_helius_transfer(tx, mint)
                if parsed:
                    results.append(parsed)

            time.sleep(0.3)

        return results

    def _parse_helius_transfer(self, tx: dict, mint: str) -> tuple | None:
        """parse helius enhanced transaction format."""
        block_time = tx.get("timestamp")
        if not block_time:
            return None

        event_ts = datetime.datetime.utcfromtimestamp(block_time).replace(
            tzinfo=datetime.timezone.utc
        )

        # find token transfer matching our mint
        for transfer in tx.get("tokenTransfers", []):
            if transfer.get("mint") != mint:
                continue
            amount       = float(transfer.get("tokenAmount", 0))
            from_address = transfer.get("fromUserAccount", "")
            to_address   = transfer.get("toUserAccount", "")
            memo         = tx.get("memo") or None
            sig          = tx.get("signature", "")
            return event_ts, amount, memo, from_address, to_address, sig

        return None

    def _fetch_rpc_transactions(self, signatures: list[str],
                                mint: str, decimals: int) -> list[tuple]:
        """standard rpc fallback — getTransaction for each signature."""
        results = []

        for sig in signatures:
            resp = self._rpc("getTransaction", [sig, {
                "encoding":                       "jsonParsed",
                "maxSupportedTransactionVersion": 0,
            }])
            if resp is None:
                continue

            tx = resp.get("result")
            if not tx:
                continue

            parsed = self._parse_spl_transfer(tx, sig, mint, decimals)
            if parsed:
                results.append(parsed)

            time.sleep(0.2)

        return results

    def _parse_spl_transfer(self, tx: dict, sig: str,
                            mint: str, decimals: int) -> Optional[tuple]:
        """
        extract transfer fields from parsed transaction.
        returns (event_ts, amount, memo, from_addr, to_addr, tx_id) or None.
        """
        block_time = tx.get("blockTime")
        if not block_time:
            return None

        event_ts = datetime.datetime.utcfromtimestamp(block_time).replace(
            tzinfo=datetime.timezone.utc
        )

        meta    = tx.get("meta", {}) or {}
        pre     = {b["accountIndex"]: b for b in meta.get("preTokenBalances",  [])}
        post    = {b["accountIndex"]: b for b in meta.get("postTokenBalances", [])}

        # find the largest positive balance change for our mint
        # covers both direct transfers and DEX inner transfers
        amount       = 0.0
        from_address = ""
        to_address   = ""

        for idx, post_bal in post.items():
            if post_bal.get("mint") != mint:
                continue
            pre_bal  = pre.get(idx, {})
            pre_amt  = float(pre_bal.get("uiTokenAmount", {}).get("uiAmount") or 0)
            post_amt = float(post_bal.get("uiTokenAmount", {}).get("uiAmount") or 0)
            delta    = post_amt - pre_amt

            if delta > amount:
                amount     = delta
                to_address = post_bal.get("owner", "")
            if delta < 0 and not from_address:
                from_address = post_bal.get("owner", "")

        if amount == 0:
            return None

        # memo — check main instructions and innerInstructions
        # dual check: exact memo program id + fuzzy "memo" match as fallback
        memo = None
        memo_programs = {MEMO_PROGRAM, MEMO_PROGRAM_V1}

        def _extract_memo(instructions):
            for ix in instructions:
                program_id = ix.get("programId", "")
                program    = ix.get("program", "")
                is_memo    = program_id in memo_programs or "memo" in program.lower()
                if is_memo:
                    parsed_data = ix.get("parsed")
                    if isinstance(parsed_data, str) and parsed_data.strip():
                        return parsed_data.strip()
            return None

        # check top-level instructions first
        instructions = (tx.get("transaction", {})
                          .get("message", {})
                          .get("instructions", []))
        memo = _extract_memo(instructions)

        # if not found — check innerInstructions (DEX wraps, etc.)
        if not memo:
            inner_groups = (tx.get("meta") or {}).get("innerInstructions", [])
            for group in inner_groups:
                memo = _extract_memo(group.get("instructions", []))
                if memo:
                    break

        return event_ts, amount, memo, from_address, to_address, sig

    # ── native SOL ────────────────────────────────────────────────────────────

    def _fetch_native_sol(self, query: TXQuery, ts_from: int,
                          ts_to: int, decimals: int) -> list[TXCandidate]:
        """
        native sol transfers via system program address.
        uses the same signature approach but parses lamport deltas.
        """
        SYSTEM_PROGRAM = "11111111111111111111111111111111"
        print(f"  [SOL] fetching native SOL transactions...")
        sigs = self._get_signatures_in_range(SYSTEM_PROGRAM, ts_from, ts_to)
        print(f"  [SOL] signatures in range: {len(sigs)}")

        if not sigs:
            return []

        results = []
        for sig in sigs:
            resp = self._rpc("getTransaction", [sig, {
                "encoding":                       "jsonParsed",
                "maxSupportedTransactionVersion": 0,
            }])
            if not resp:
                continue
            tx = resp.get("result")
            if not tx:
                continue

            block_time = tx.get("blockTime")
            if not block_time:
                continue

            event_ts = datetime.datetime.utcfromtimestamp(block_time).replace(
                tzinfo=datetime.timezone.utc
            )

            meta      = tx.get("meta", {}) or {}
            pre_bals  = meta.get("preBalances",  [])
            post_bals = meta.get("postBalances", [])
            accounts  = (tx.get("transaction", {})
                           .get("message", {})
                           .get("accountKeys", []))

            # find largest lamport increase (recipient)
            amount       = 0.0
            from_address = ""
            to_address   = ""

            for i, (pre, post) in enumerate(zip(pre_bals, post_bals)):
                delta_sol = (post - pre) / 10 ** decimals
                if delta_sol > amount:
                    amount     = delta_sol
                    to_address = accounts[i] if i < len(accounts) else ""
                if delta_sol < 0 and not from_address:
                    from_address = accounts[i] if i < len(accounts) else ""

            if amount == 0:
                continue

            results.append((event_ts, amount, None, from_address, to_address, sig))
            time.sleep(0.1)

        return find_matches(results, query, lambda t: t, "SOL", self.min_confidence)

    # ── rpc helper ────────────────────────────────────────────────────────────

    def _rpc(self, method: str, params: list) -> Optional[dict]:
        """send a jsonrpc request to solana rpc."""
        payload = {
            "jsonrpc": "2.0",
            "id":      1,
            "method":  method,
            "params":  params,
        }
        try:
            resp = self.session.post(
                self.rpc_url, json=payload, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"  [SOL] rpc error ({method}): {e}")
            return None
