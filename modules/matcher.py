"""
txfetch — modules/matcher.py
universal filter and scorer for raw api results.
each adapter passes its events through here instead of implementing _filter_and_score locally.
"""

from __future__ import annotations

import datetime
from typing import Callable

from modules.models import TXQuery, TXCandidate, score_candidate, amount_matches


# parser signature: raw event dict → (timestamp, amount, memo, from_addr, to_addr, tx_id)
# returns None if the event should be skipped (missing required fields)
EventParser = Callable[
    [dict],
    tuple[datetime.datetime, float, str | None, str, str, str] | None
]


def find_matches(
    events:         list[dict],
    query:          TXQuery,
    parser:         EventParser,
    network:        str,
    min_confidence: float = 0.3,
) -> list[TXCandidate]:
    """
    filter and score a list of raw api events.

    args:
        events         — raw list of dicts from the api
        query          — search parameters
        parser         — function that extracts fields from a raw event
        network        — network name for TXCandidate (e.g. "TRON")
        min_confidence — discard candidates below this threshold

    returns:
        list of TXCandidate sorted by confidence descending
    """
    candidates: list[TXCandidate] = []

    for ev in events:
        parsed = parser(ev)
        if parsed is None:
            continue

        event_ts, amount, memo, from_addr, to_addr, tx_id = parsed

        confidence, detail = score_candidate(event_ts, amount, memo, query)
        if confidence < min_confidence:
            continue

        candidates.append(TXCandidate(
            tx_id        = tx_id,
            timestamp    = event_ts,
            amount       = amount,
            network      = network,
            coin         = query.coin.upper(),
            from_address = from_addr,
            to_address   = to_addr,
            memo         = memo,
            confidence   = confidence,
            score_detail = detail,
        ))

    # deduplicate by tx_id — keep highest confidence for each
    seen: dict = {}
    for c in candidates:
        if c.tx_id not in seen or c.confidence > seen[c.tx_id].confidence:
            seen[c.tx_id] = c
    candidates = list(seen.values())

    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates