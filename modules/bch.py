"""
txfetch — modules/bch.py
bitcoin cash adapter via blockchair api.
"""

from modules.utxo_base import UTXOBase


class BCHAdapter(UTXOBase):
    NETWORK    = "BCH"
    API_BASE   = "https://api.blockchair.com/bitcoin-cash"
    COIN       = "BCH"
    SATOSHI    = 100_000_000   # 1 bch = 100_000_000 satoshi
    BLOCK_TIME = 600           # ~10 min per block
