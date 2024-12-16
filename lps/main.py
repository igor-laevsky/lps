from functools import lru_cache

import attrs
import requests
import rich
from eth_defi.abi import get_contract, get_deployed_contract
from eth_defi.chain import install_chain_middleware, install_retry_middleware
from eth_defi.token import fetch_erc20_details, TokenDetails
from eth_defi.uniswap_v2.pair import fetch_pair_details
from eth_defi.uniswap_v3.deployment import fetch_deployment
from eth_defi.uniswap_v3.swap import swap_with_slippage_protection

from lps.utils.config import load_configuration, logging_config, get_config, \
    resources_path
import sys
import logging.config

load_configuration(sys.argv[1])
logging.config.dictConfig(logging_config())

logger = logging.getLogger('main')

from web3 import Web3
from eth_defi.event_reader.fast_json_rpc import patch_web3

@attrs.frozen
class NftPositionInfo:
    nonce: int
    operator: str
    token0: str
    token1: str
    tickSpacing: int
    tickLower: int
    tickUpper: int
    liquidity: int
    feeGrowthInside0LastX128: int
    feeGrowthInside1LastX128: int
    tokensOwed0: int
    tokensOwed1: int

@attrs.frozen
class CLPoolSlot0:
    sqrtPriceX96: int
    tick: int
    observationIndex: int
    observationCardinality: int
    observationCardinalityNext: int
    unlocked: bool

@lru_cache(maxsize=256)
def fetch_pair_details_cached(web3: Web3, pair_address: str) -> TokenDetails:
    """In-process memory cache for getting pair data in decoded format."""
    return fetch_erc20_details(web3, pair_address)

def main():
    conf = get_config()

    session = requests.Session()
    w3 = Web3(Web3.HTTPProvider(conf.base_node_url, session=session))
    patch_web3(w3)

    w3.middleware_onion.clear()
    install_retry_middleware(w3)

    aero_nft_manager = get_deployed_contract(
        w3,
        resources_path() / "abis" / "aerodrome_nft_manager.json",
        address=conf.aerodrome.nft_position_manager
    )

    position_info = NftPositionInfo(*aero_nft_manager.functions.positions(3899989).call())
    # 3796958
    rich.print(position_info)

    cl_factory = get_deployed_contract(
        w3,
        resources_path() / "abis" / "aerodrome_cl_factory.json",
        address=conf.aerodrome.cl_factory
    )
    pool_addr = cl_factory.functions.getPool(position_info.token0, position_info.token1, position_info.tickSpacing).call()
    print(pool_addr)

    cl_pool = get_deployed_contract(
        w3,
        resources_path() / "abis" / "aerodrome_cl_pool.json",
        pool_addr
    )
    slot0 = CLPoolSlot0(*cl_pool.functions.slot0().call())
    print(slot0)

    token0_details = fetch_erc20_details(w3, position_info.token0)
    token1_details = fetch_erc20_details(w3, position_info.token1)
    print('Token0: ', token0_details)
    print('Token1: ', token1_details)
    print('Current price: ', ((slot0.sqrtPriceX96 / 0x1000000000000000000000000) ** 2) / 10**(token1_details.decimals - token0_details.decimals))


    # aero_sugar = get_deployed_contract(
    #     w3,
    #     resources_path() / "abis" / "aerodrome_sugar.json",
    #     conf.aerodrome.sugar)

    # print(w3.eth.get_block_number())
    # fetch_deployment()
    # swap_with_slippage_protection()

    # print(aero_sugar.functions.positions(100, 0, Web3.to_checksum_address('0x84fcd2463483e8f8dc4190c65679592f2358c314')).call())
    # print(aero_sugar.functions.positions(100, 0, Web3.to_checksum_address('0x83106205dD989fd5cd953dAb514158B1E04ca557')).call())
    # positions = aero_sugar.functions.positionsByFactory(10000, 00,
    #                                               Web3.to_checksum_address('0xf33a96b5932d9e9b9a0eda447abd8c9d48d2e0c8'),
    #                                               '0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A').call()
    # print(len(positions))

    #print(aero_sugar.functions.all(_limit=10, _offset=0).call())

if __name__ == "__main__":
    main()
