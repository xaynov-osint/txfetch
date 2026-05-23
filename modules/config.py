"""
txfetch — modules/config.py
reads api keys and runtime constants from .env file in project root.
falls back to defaults if not set.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_env(path: Path) -> dict[str, str]:
    """parse a .env file into a dict, ignoring comments and empty lines."""
    result = {}
    if not path.exists():
        return result
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key   = key.strip()
            value = value.strip()
            if value:
                result[key] = value
    return result


# load .env from project root
_env_path = Path(__file__).parent.parent / ".env"
_env      = _load_env(_env_path)


def get(key: str) -> str | None:
    """return value from .env or environment variable, None if not set."""
    return _env.get(key) or os.environ.get(key) or None


def get_int(key: str, default: int) -> int:
    """return integer value from .env, fallback to default."""
    val = get(key)
    try:
        return int(val) if val is not None else default
    except ValueError:
        return default


def get_float(key: str, default: float) -> float:
    """return float value from .env, fallback to default."""
    val = get(key)
    try:
        return float(val) if val is not None else default
    except ValueError:
        return default


# ── api keys ──────────────────────────────────────────────────────────────────

TRONGRID_API_KEY  = get("TRONGRID_API_KEY")
ETHERSCAN_API_KEY = get("ETHERSCAN_API_KEY")
BSCSCAN_API_KEY   = get("BSCSCAN_API_KEY")
TONAPI_KEY        = get("TONAPI_KEY")
HELIUS_API_KEY    = get("HELIUS_API_KEY")

# ── runtime constants ─────────────────────────────────────────────────────────

REQUEST_TIMEOUT = get_int("REQUEST_TIMEOUT", 15)
PAGE_LIMIT      = get_int("PAGE_LIMIT",      200)
MAX_PAGES       = get_int("MAX_PAGES",        50)
PAGE_DELAY      = get_float("PAGE_DELAY",     1.0)
MIN_CONFIDENCE  = get_float("MIN_CONFIDENCE", 0.3)
