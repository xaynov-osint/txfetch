"""
txfetch — modules/ltc.py
litecoin adapter via litecoinspace.org api.
"""

from modules.utxo_base import UTXOBase


class LTCAdapter(UTXOBase):
    NETWORK    = "LTC"
    API_BASE   = "https://litecoinspace.org/api"
    COIN       = "LTC"
    SATOSHI    = 100_000_000   # 1 ltc = 100_000_000 litoshis
    BLOCK_TIME = 150           # ~2.5 min per block
