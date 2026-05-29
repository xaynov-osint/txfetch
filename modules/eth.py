"""
txfetch — modules/eth.py
ethereum mainnet adapter.
"""

from modules.evm_base import EVMBase
from modules import config


class ETHAdapter(EVMBase):
    NETWORK = "ETH"
    API_URL  = "https://api.etherscan.io/v2/api"
    CHAIN_ID = "1"
    API_KEY = config.ETHERSCAN_API_KEY
    TOKENS  = {
        "USDT": {"address": "0xdAC17F958D2ee523a2206206994597C13D831ec7", "decimals": 6},
        "USDC": {"address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
    }