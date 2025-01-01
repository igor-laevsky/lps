import functools
import math
from collections import defaultdict
from datetime import datetime
from operator import attrgetter
from typing import Iterator, Tuple, Iterable

import attrs
import numpy as np
import pandas as pd
import rich
from eth_defi.abi import get_contract
from eth_typing import AnyAddress
from web3.types import LogReceipt, TxData
import humanize

from lps import hedger
from lps.connectors.abs import CanDoOrders, HasAssetPositions
from lps.connectors.base import create_base_web3
from lps.contracts import create_contract_cached
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

NUM_DAYS = 30
STEP_LEN_SEC = 24
SECS_PER_HOUR = 60 * 60
SECS_PER_DAY = 24 * SECS_PER_HOUR
SAMPLES_PER_DAY = SECS_PER_DAY // STEP_LEN_SEC
SAMPLES_PER_HOUR = SECS_PER_HOUR // STEP_LEN_SEC
def get_price_path(starting_price, sigma_per_day, num_sims):
    np.random.seed(123) # make it repeatable
    mu = 0.0   # assume delta neutral behavior
    T = NUM_DAYS
    n = T * SAMPLES_PER_DAY
    # calc each time step
    dt = T/n
    # simulation using numpy arrays
    St = np.exp(
        (mu - sigma_per_day ** 2 / 2) * dt
        + sigma_per_day * np.random.normal(0, np.sqrt(dt), size=(num_sims, n-1)).T
    )
    # include array of 1's
    St = np.vstack([np.ones(num_sims), St])
    # multiply through by S0 and return the cumulative product of elements along a given simulation path (axis=0).
    St = float(starting_price) * St.cumprod(axis=0)
    return St

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

def step(tick: int, hedge_computer: any):
    #hedges = hedger.compute_hedges([(pos, tick)])
    #hedges = hedger.compute_hedges_50_50([(pos, tick)])
    #hedges = hedger.compute_hedges_fixed_step([(pos, tick)])
    hedges = hedge_computer([(pos, tick)])

    updates = hedger.compute_hedge_adjustments(mock_cex, hedges)
    updated_cnt = hedger.execute_hedge_adjustements(mock_cex, updates)
    # if updated_cnt > 0:
    #     print(f'Updated hedge {tick} {v3_math.tick_to_price(tick) * 10**12:.4f} {updates}')
    return updated_cnt

def scenario1(hedge_computer):
    # Enter position at 50/50
    # Price goes up, down then back to the middle
    # Total PnL should be zero
    # Basically the cost of hedging excluding fees
    middle_tick = (pos.tick_upper + pos.tick_lower) // 2
    mock_cex.usd_balance = Decimal(2000)
    mock_cex.set_mid_prices({'ETH': v3_math.tick_to_price(middle_tick) * 10**12})

    starting_pos_value = position_value_usd(mock_cex, pos, middle_tick)
    starting_hedge_value = mock_cex.usd_balance
    print(f'Starting position value: {starting_pos_value:.4f}')
    print(f'Starting hedge value: {starting_hedge_value:.4f}')

    current_tick = middle_tick

    out_of_range_by_ticks = 100

    # Go up out of range, down out of range and back to the middle
    for i in range(10):
        for current_tick in range(middle_tick, pos.tick_upper + out_of_range_by_ticks, 1):
            mock_cex.set_mid_prices({'ETH': v3_math.tick_to_price(current_tick) * 10**12})
            step(current_tick, hedge_computer)

        for current_tick in range(pos.tick_upper + out_of_range_by_ticks, pos.tick_lower - out_of_range_by_ticks, -1):
            mock_cex.set_mid_prices({'ETH': v3_math.tick_to_price(current_tick) * 10**12})
            step(current_tick, hedge_computer)

        for current_tick in range(pos.tick_lower - out_of_range_by_ticks, middle_tick, 1):
            mock_cex.set_mid_prices({'ETH': v3_math.tick_to_price(current_tick) * 10**12})
            step(current_tick, hedge_computer)

    # Exit
    mock_cex.close_all_positions()
    final_pos_value = position_value_usd(mock_cex, pos, current_tick)
    final_hedge_value = mock_cex.usd_balance
    print(f'Final position value: {final_pos_value:.4f}')
    print(f'Final hedge value: {final_hedge_value:.4f}')

    total_change = (final_pos_value + final_hedge_value) - (starting_pos_value + starting_hedge_value)
    print(f'Total PnL: {total_change:.4f}')

def scenario2(hedge_computer, rehedge_time_sec:int=0):
    """
    Generate random prices, enter positions at the start, exit at the end
    Compute the sum total PnL
    """
    num_sims = 10
    middle_tick = (pos.tick_upper + pos.tick_lower) // 2
    initial_price = v3_math.tick_to_price(middle_tick) * 10**12

    all_prices = get_price_path(initial_price, 0.05, num_sims)

    def price_to_tick(price: Decimal) -> int:
        return math.floor(math.log(price / 10**12, v3_math.TICK_BASE))

    total_pnl = 0
    total_pnl_no_hedge = 0

    sim_results = []

    rehedge_every_n = rehedge_time_sec // STEP_LEN_SEC
    print(f'Re-hedge every {rehedge_every_n} steps')

    for sim_idx in range(num_sims):
        prices = all_prices[:,sim_idx]

        # Entering position
        starting_tick = price_to_tick(Decimal(prices[0]))
        mock_cex.usd_balance = Decimal(2000)
        mock_cex.set_mid_prices({'ETH': Decimal(prices[0])})

        starting_pos_value = position_value_usd(mock_cex, pos, starting_tick)
        starting_hedge_value = mock_cex.get_total_balance()

        print(f'Starting tick: {starting_tick} {Decimal(prices[0])}')
        print(f'Starting pos value: {starting_pos_value}')
        print(f'Starting hedge value: {starting_hedge_value}')

        rows = []

        for i in range(0, len(prices)):
            price = prices[i]
            mock_cex.set_mid_prices({'ETH': Decimal(price)})
            tick = price_to_tick(Decimal(price))

            if rehedge_every_n == 0 or i % rehedge_every_n == 0:
                step(tick, hedge_computer)

            hedge_positions = mock_cex.get_user_positions()
            hedge_size = hedge_positions['ETH'].szi if 'ETH' in hedge_positions else 0
            new_row = {
                'price': price,
                'tick': tick,
                'pos_value': float(position_value_usd(mock_cex, pos, tick)),
                'hedge_value': float(mock_cex.get_total_balance()),
                'hedge_size': float(hedge_size)
            }
            rows.append(new_row)

        sim_results.append(rows)

        # Exit position
        mock_cex.set_mid_prices({'ETH': Decimal(prices[-1])})
        mock_cex.close_all_positions()
        last_tick = price_to_tick(prices[-1])
        final_pos_value = position_value_usd(mock_cex, pos, last_tick)
        final_hedge_value = mock_cex.get_total_balance()

        print(f'Finish tick: {last_tick} {prices[-1]:.4f}')
        print(f'Finish pos value: {final_pos_value}')
        print(f'Finish hedge value: {final_hedge_value}')

        pnl_no_hedge = final_pos_value - starting_pos_value
        pnl = pnl_no_hedge + (final_hedge_value - starting_hedge_value)
        total_pnl += pnl
        total_pnl_no_hedge += pnl_no_hedge

        print(f'Finished simulation {sim_idx} {pnl_no_hedge} {final_hedge_value - starting_hedge_value}\n')

    print(f'Avg PnL: {total_pnl / num_sims}')
    print(f'Avg PnL no hedge: {total_pnl_no_hedge / num_sims}')

    return [pd.DataFrame(sim_rows) for sim_rows in sim_results]


def main():
    t = time.time()
    # print("Dynamic hedger")
    # scenario1(hedger.compute_hedges)
    # print()
    #
    print("50/50 hedger")
    scenario1(functools.partial(hedger.compute_hedges_fixed_step, threshold=100))
    print()

    # print("Dynamic hedger scenario 2")
    # scenario2(hedger.compute_hedges)
    # print()

    # print("50/50 hedger scenario 2")
    # scenario2(hedger.compute_hedges_fixed_step)
    # print()

    print(f'Time: {time.time() - t}s')

if __name__ == "__main__":
    main()

