"""
txfetch — modules/config.py
reads api keys from .env file in project root.
falls back to None if key is missing or empty — adapters then use public access.
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


# load .env from project root (two levels up from this file)
_env_path = Path(__file__).parent.parent / ".env"
_env      = _load_env(_env_path)


def get(key: str) -> str | None:
    """return api key from .env or environment variable, None if not set."""
    return _env.get(key) or os.environ.get(key) or None


# named accessors for each service
TRONGRID_API_KEY  = get("TRONGRID_API_KEY")
ETHERSCAN_API_KEY = get("ETHERSCAN_API_KEY")
BSCSCAN_API_KEY   = get("BSCSCAN_API_KEY")
TONAPI_KEY        = get("TONAPI_KEY")
