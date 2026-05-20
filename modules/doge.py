"""
txfetch — modules/doge.py
dogecoin adapter via dogechain api.
note: dogechain uses a different api structure — block fetching may vary.
"""

from modules.utxo_base import UTXOBase


class DOGEAdapter(UTXOBase):
    NETWORK    = "DOGE"
    API_BASE   = "https://dogechain.info/api/v1"
    COIN       = "DOGE"
    SATOSHI    = 100_000_000   # 1 doge = 100_000_000 koinu
    BLOCK_TIME = 60            # ~1 min per block
