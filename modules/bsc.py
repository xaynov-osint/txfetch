"""
txfetch — modules/bsc.py
bnb smart chain adapter.
"""

from modules.evm_base import EVMBase
from modules import config


class BSCAdapter(EVMBase):
    NETWORK = "BSC"
    API_URL  = "https://api.bscscan.com/v2/api"
    CHAIN_ID = "56"
    API_KEY = config.BSCSCAN_API_KEY
    TOKENS  = {
        "USDT": {"address": "0x55d398326f99059fF775485246999027B3197955", "decimals": 18},
        "USDC": {"address": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", "decimals": 18},
    }