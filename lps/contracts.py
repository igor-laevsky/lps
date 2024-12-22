from functools import lru_cache
from typing import Type

from eth_defi.abi import get_deployed_contract, get_contract
from eth_defi.token import TokenDetails, fetch_erc20_details
from web3 import Web3
from web3.contract import Contract

from lps.utils.config import resources_path, get_config

@lru_cache(maxsize=256)
def create_contract_cached(web3: Web3, abi_fname: str, address: str | None = None) -> Contract | Type[Contract]:
    if address is not None:
        return get_deployed_contract(
            web3,
            resources_path() / "abis" / abi_fname,
            address,
            register_for_tracing = False
        )
    return get_contract(
        web3,
        resources_path() / "abis" / abi_fname)
