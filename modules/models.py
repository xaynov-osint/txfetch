"""
txfetch — models.py
shared data types and scoring algorithm.
used by all adapters: tron.py, ton.py, eth.py, btc.py
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class TXQuery:
    """
    query object built from user input, passed to each adapter.

    time window:
      - time_from / time_to always in utc
      - if user entered HH:MM → time_from=HH:MM:00, time_to=HH:MM:59
      - if user entered HH:MM:SS → time_from=HH:MM:SS, time_to=HH:MM:SS
    """
    time_from:       datetime.datetime   # start of window (UTC, inclusive)
    time_to:         datetime.datetime   # end of window (UTC, inclusive)
    coin:            str                 # e.g. "USDT", "BTC", "TON"
    amount:          Optional[float] = None   # None = no filter
    amount_tolerance: float = 0.01       # tolerance: 0.01 = ±1%
    memo:            Optional[str] = None     # comment / memo

    @property
    def timestamp(self) -> datetime.datetime:
        """scoring anchor — always time_from. tx at 20:38:00 gets score=1.0."""
        return self.time_from

    @property
    def time_delta_sec(self) -> float:
        """window width in seconds for scoring."""
        return (self.time_to - self.time_from).total_seconds() or 1.0

@dataclass
class TXCandidate:
    """
    a single search result candidate.
    all adapters return list[TXCandidate].
    """
    tx_id:        str
    timestamp:    datetime.datetime
    amount:       float                  # in coin units (not wei/sun)
    network:      str                    # "TRON", "TON", "ETH", "BTC"
    coin:         str                    # "USDT", "BTC", ...
    from_address: str = ""
    to_address:   str = ""
    memo:         Optional[str] = None
    confidence:   float = 0.0
    score_detail: dict  = field(default_factory=dict)

    def __str__(self) -> str:
        ts  = self.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
        return (
            f"[{self.confidence:.0%}]  {self.tx_id}\n"
            f"  {ts}  |  {self.amount:.6f} {self.coin}\n"
            f"  From: {self.from_address or '-'}\n"
            f"  To:   {self.to_address or '-'}"
            + (f"\n  Memo: {self.memo}" if self.memo else "")
        )

def score_candidate(
    event_ts:     datetime.datetime,
    event_amount: float,
    event_memo:   Optional[str],
    query:        TXQuery,
) -> tuple[float, dict]:
    """
    computes confidence [0..1] and detail dict for one candidate.

    weights:
      - time:   0.5  linear within time_delta_sec
      - amount: 0.4  exact = 1.0, within tolerance — linear, else hard reject
      - memo:   0.1  case-insensitive substring match = 1.0, else 0

    if amount is not set — its weight is redistributed to time (0.9 / 0.1).
    if memo is not set — its weight is redistributed proportionally.
    """
    detail: dict = {}

    delta_sec = abs((event_ts - query.timestamp).total_seconds())
    time_score = max(0.0, 1.0 - delta_sec / query.time_delta_sec)
    detail["time_delta_sec"] = round(delta_sec, 1)
    detail["time_score"]     = round(time_score, 3)

    if query.amount is not None and query.amount > 0:
        rel_diff = abs(event_amount - query.amount) / query.amount
        if rel_diff == 0:
            amount_score = 1.0
        elif rel_diff <= query.amount_tolerance:
            amount_score = 1.0 - rel_diff / query.amount_tolerance
        else:
            # amount specified but out of tolerance — hard reject
            return 0.0, {"rejected": "amount_mismatch",
                         "amount_diff_pct": round(rel_diff * 100, 4)}
        detail["amount_diff_pct"] = round(rel_diff * 100, 4)
        detail["amount_score"]    = round(amount_score, 3)
        has_amount = True
    else:
        amount_score = None
        has_amount   = False

    if query.memo:
        q_memo = query.memo.lower().strip()
        e_memo = (event_memo or "").lower().strip()
        memo_score = 1.0 if q_memo in e_memo else 0.0
        detail["memo_score"] = memo_score
        has_memo = True
    else:
        memo_score = None
        has_memo   = False

    # base weights
    w_time   = 0.5
    w_amount = 0.4
    w_memo   = 0.1

    if not has_amount and not has_memo:
        confidence = time_score

    elif not has_amount:
        # no amount: time 0.9, memo 0.1
        confidence = 0.9 * time_score + 0.1 * memo_score

    elif not has_memo:
        # no memo: normalize weights 0.5 and 0.4 proportionally
        total = w_time + w_amount
        confidence = (w_time / total) * time_score + (w_amount / total) * amount_score

    else:
        confidence = w_time * time_score + w_amount * amount_score + w_memo * memo_score

    return round(confidence, 4), detail