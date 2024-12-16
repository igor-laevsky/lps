import signal
import time

from eth_defi.event_reader.csv_block_data_store import CSVDatasetBlockDataStore
from eth_defi.uniswap_v3.price import get_onchain_price

from lps.aerodrome import get_position_info
from lps.utils.config import load_configuration, logging_config, get_config, \
    resources_path, data_path
import sys
import logging.config

load_configuration(sys.argv[1])
logging.config.dictConfig(logging_config())

from functools import lru_cache

import attrs
import requests
import rich
from eth_defi.abi import get_contract, get_deployed_contract
from eth_defi.chain import install_chain_middleware, install_retry_middleware
from eth_defi.event_reader.block_time import measure_block_time
from eth_defi.event_reader.reorganisation_monitor import \
    JSONRPCReorganisationMonitor, create_reorganisation_monitor
from eth_defi.token import fetch_erc20_details, TokenDetails
from eth_defi.uniswap_v2.pair import fetch_pair_details
from eth_defi.uniswap_v3.deployment import fetch_deployment
from eth_defi.uniswap_v3.swap import swap_with_slippage_protection
from tqdm import tqdm

logger = logging.getLogger('main')

from web3 import Web3
from eth_defi.event_reader.fast_json_rpc import patch_web3

def main():
    conf = get_config()

    session = requests.Session()
    w3 = Web3(Web3.HTTPProvider(conf.base_node_url, session=session))
    patch_web3(w3)

    w3.middleware_onion.clear()
    install_retry_middleware(w3)

    block_time_sec = measure_block_time(w3)
    logger.info(f'Measured block time {block_time_sec}s')

    # Graceful shutdown
    is_running = True
    def stop(signum, frame):
        nonlocal is_running
        is_running = False
        logger.info(f'Received {signum}, exiting')
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    positions = (3899989,)
    for pos in positions:
        pos_info = get_position_info(w3, pos)
        rich.print(pos_info)

    while is_running:
        logger.info(f'Current block: ${w3.eth.get_block_number()}')

        time.sleep(block_time_sec)

    # aero_nft_manager = get_deployed_contract(
    #     w3,
    #     resources_path() / "abis" / "aerodrome_nft_manager.json",
    #     address=conf.aerodrome.nft_position_manager
    # )

    # position_info = NftPositionInfo(*aero_nft_manager.functions.positions(3899989).call())
    # # 3796958
    # rich.print(position_info)
    #
    # cl_factory = get_deployed_contract(
    #     w3,
    #     resources_path() / "abis" / "aerodrome_cl_factory.json",
    #     address=conf.aerodrome.cl_factory
    # )
    # pool_addr = cl_factory.functions.getPool(position_info.token0, position_info.token1, position_info.tickSpacing).call()
    # print(pool_addr)
    #
    # cl_pool = get_deployed_contract(
    #     w3,
    #     resources_path() / "abis" / "aerodrome_cl_pool.json",
    #     pool_addr
    # )
    # slot0 = CLPoolSlot0(*cl_pool.functions.slot0().call())
    # print(slot0)
    #
    # token0_details = fetch_erc20_details(w3, position_info.token0)
    # token1_details = fetch_erc20_details(w3, position_info.token1)
    # print('Token0: ', token0_details)
    # print('Token1: ', token1_details)
    # print('Current price: ', ((slot0.sqrtPriceX96 / 0x1000000000000000000000000) ** 2) / 10**(token1_details.decimals - token0_details.decimals))

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
