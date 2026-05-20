"""
txfetch — modules/base_chain.py
base (coinbase l2) adapter.
note: named base_chain.py to avoid conflict with python built-in 'base'.
"""

from modules.evm_base import EVMBase
from modules import config


class BaseAdapter(EVMBase):
    NETWORK = "BASE"
    API_URL = "https://api.basescan.org/api"
    API_KEY = config.ETHERSCAN_API_KEY   # basescan accepts etherscan key
    TOKENS  = {
        "USDC": {"address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "decimals": 6},
        "ETH":  {"address": None, "decimals": 18},
    }
