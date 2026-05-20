"""
txfetch — modules/btc.py
bitcoin adapter — extends utxo_base with mempool.space api.
"""

from modules.utxo_base import UTXOBase


class BTCAdapter(UTXOBase):
    NETWORK    = "BTC"
    API_BASE   = "https://mempool.space/api"
    COIN       = "BTC"
    SATOSHI    = 100_000_000   # 1 btc = 100_000_000 satoshi
    BLOCK_TIME = 600           # ~10 min per block
