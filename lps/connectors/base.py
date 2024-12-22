import logging

import requests
from eth_defi.chain import install_retry_middleware
from eth_defi.event_reader.fast_json_rpc import patch_web3
from web3 import Web3

from lps.utils.config import get_config

logger = logging.getLogger('base_w3')

def create_base_web3() -> Web3:
    logger.info('Starting')

    session = requests.Session()
    w3 = Web3(Web3.HTTPProvider(get_config().base_node_url, session=session))
    patch_web3(w3)

    w3.middleware_onion.clear()
    install_retry_middleware(w3)

    logger.info('Started')
    return w3
