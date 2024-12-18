from functools import lru_cache

from eth_defi.token import TokenDetails, fetch_erc20_details
from web3 import Web3

@lru_cache(maxsize=256)
def fetch_erc20_details_cached(web3: Web3, pair_address: str) -> TokenDetails:
    """In-process memory cache for getting pair data in decoded format."""
    return fetch_erc20_details(web3, pair_address)

def guess_is_stable_coin(token: TokenDetails) -> bool:
    """Best guess if this is a stable coin"""
    return token.symbol in ('USDC', 'USDT', 'DAI', 'USDe', 'USDS', 'PYUSD')
