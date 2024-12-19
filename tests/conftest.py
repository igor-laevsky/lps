from lps.utils.config import load_configuration, logging_config, get_config
import logging.config

load_configuration('dev')
logging.config.dictConfig(logging_config())

import pytest
import requests
from eth_defi.chain import install_retry_middleware
from eth_defi.event_reader.fast_json_rpc import patch_web3
from web3 import Web3

from lps.connectors import hl
from lps.utils.config import load_configuration, get_config


@pytest.fixture(scope="session", autouse=True)
def init():
    #load_configuration('dev')
    get_config().hyperliquid.use_testnet = True

@pytest.fixture(scope='session')
def base_w3(init):
    session = requests.Session()
    w3 = Web3(Web3.HTTPProvider(get_config().base_node_url, session=session))
    patch_web3(w3)

    w3.middleware_onion.clear()
    install_retry_middleware(w3)
    return w3

@pytest.fixture(scope='session')
def hl_connector(init):
    return hl.start()
