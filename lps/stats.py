import rich
from eth_defi.abi import get_contract
from eth_defi.event_reader.reader import prepare_filter, read_events
from web3._utils.filters import construct_event_filter_params

from contracts import create_contract_cached
from lps.utils.config import load_configuration, logging_config, get_config, \
    resources_path
import sys
import logging.config

load_configuration('dev')
logging.config.dictConfig(logging_config())

import signal
import time

from lps.aerodrome import get_position_info_cached, clear_caches
from lps.connectors import hl
from lps.utils import v3_math
from lps import hl_hedger, erc20

import requests
from decimal import Decimal

from eth_defi.chain import install_retry_middleware
from eth_defi.event_reader.block_time import measure_block_time

from web3 import Web3
from eth_defi.event_reader.fast_json_rpc import patch_web3

from lps.connectors import binance

logger = logging.getLogger('main')


def create_base_web3() -> Web3:
    session = requests.Session()
    w3 = Web3(Web3.HTTPProvider(get_config().base_node_url, session=session))
    patch_web3(w3)

    w3.middleware_onion.clear()
    install_retry_middleware(w3)
    return w3

w3 = create_base_web3()

# aero_nft_manager = create_contract_cached(
#     w3,
#     address=get_config().aerodrome.nft_position_manager,
#     abi_fname="aerodrome_nft_manager.json",
# )

# aero_nft_manager = get_contract(
#     w3,
#     resources_path() / "abis" / "aerodrome_nft_manager.json"
# )


# logs = aero_nft_manager.events.IncreaseLiquidity.get_logs(
#     fromBlock="23533310",
#     toBlock='finalized',
#     argument_filters={
#         'tokenId': 3899989
#     }
# )
#
# print(logs)

# filter = aero_nft_manager.events.IncreaseLiquidity.create_filter(
#     fromBlock="23533310",
#     argument_filters={
#         'tokenId': 3899989
#     }
# )

aero_pool = get_contract(
    w3,
    resources_path() / "abis" / "aerodrome_cl_pool.json"
)

filter =  aero_pool.events.Mint.create_filter(
    fromBlock="23533310",
    argument_filters={
        'owner': Web3.to_checksum_address('0x827922686190790b37229fd06084350e74485b72')
    }
)

print(filter.get_all_entries())