from collections import defaultdict
from datetime import datetime
from operator import attrgetter
from typing import Iterator, Tuple, Iterable

import attrs
import rich
from eth_defi.abi import get_contract
from eth_typing import AnyAddress
from web3.types import LogReceipt, TxData
import humanize

import aerodrome
import connectors
import hedger
from connectors.abs import CanDoOrders, HasAssetPositions
from connectors.base import create_base_web3
from contracts import create_contract_cached
from lps.utils.config import load_configuration, logging_config, get_config, \
    resources_path
import sys
import logging.config

load_configuration('dev')
logging.config.dictConfig(logging_config())

import signal
import time

from lps.aerodrome import get_position_info_cached, clear_caches, PositionInfo, CLPoolInfo
from lps.connectors import hl
from lps.utils import v3_math
from lps import erc20

import requests
from decimal import Decimal

from eth_defi.chain import install_retry_middleware
from eth_defi.event_reader.block_time import measure_block_time

from web3 import Web3
from eth_defi.event_reader.fast_json_rpc import patch_web3

from lps.connectors import binance
from lps.connectors import mock_cex

logger = logging.getLogger('main')

w3 = create_base_web3()
mock_cex = mock_cex.start(2000)

pos = PositionInfo(
    tick_lower=-194200,
    tick_upper=-192600,
    liquidity=180540158377974,
    nft_id=3899989,
    pool=CLPoolInfo(
        token0=erc20.fetch_erc20_details_cached(w3, '0x4200000000000000000000000000000000000006'),
        token1=erc20.fetch_erc20_details_cached(w3, '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'),
        tick_spacing=100,
        fee_pips=400,
        contract=create_contract_cached(
            w3,
            address=str('0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59'),
            abi_fname="aerodrome_cl_pool.json",
        )
    ),
)

def position_value_usd(conn: HasAssetPositions, pos: PositionInfo, current_tick: int) -> Decimal:
    (amount0, amount1) = v3_math.get_amounts_at_tick(
        pos.tick_lower, pos.tick_upper, pos.liquidity, current_tick)

    token0_symbol = erc20.canonical_symbol(pos.token0.symbol)
    token1_symbol = erc20.canonical_symbol(pos.token1.symbol)

    if erc20.guess_is_stable_coin(pos.token0):
        price0 = 1
    else:
        price0 = conn.get_mid_prices(token0_symbol)[token0_symbol]

    if erc20.guess_is_stable_coin(pos.token1):
        price1 = 1
    else:
        price1 = conn.get_mid_prices(token1_symbol)[token1_symbol]

    amount0_usd = pos.pool.token0.convert_to_decimals(amount0) * price0
    amount1_usd = pos.pool.token1.convert_to_decimals(amount1) * price1
    return amount0_usd + amount1_usd

def step(tick: int):
    hedges = hedger.compute_hedges([(pos, tick)])
    updates = hedger.compute_hedge_adjustments(mock_cex, hedges)
    updated_cnt = hedger.execute_hedge_adjustements(mock_cex, updates)
    return updated_cnt

middle_tick = -193400

current_tick = -193400
mock_cex.set_mid_prices({'ETH': v3_math.tick_to_price(current_tick) * 10**12})
print(f'Starting position value: {position_value_usd(mock_cex, pos, current_tick)}')
print(f'Starting hedge value: {mock_cex.usd_balance}')
step(current_tick)

for i in range(10):
    for current_tick in range(middle_tick, pos.tick_upper + 1000, 10):
        mock_cex.set_mid_prices({'ETH': v3_math.tick_to_price(current_tick) * 10**12})
        step(current_tick)

    for current_tick in range(pos.tick_upper + 1000, pos.tick_lower - 1000, -10):
        mock_cex.set_mid_prices({'ETH': v3_math.tick_to_price(current_tick) * 10**12})
        step(current_tick)

    for current_tick in range(pos.tick_lower - 1000, middle_tick, 10):
        mock_cex.set_mid_prices({'ETH': v3_math.tick_to_price(current_tick) * 10**12})
        step(current_tick)

# Exit
mock_cex.close_all_positions()
print(f'Final position value: {position_value_usd(mock_cex, pos, current_tick)}')
print(f'Final hedge value: {mock_cex.usd_balance}')
