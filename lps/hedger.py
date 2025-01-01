import itertools
import logging
from collections import defaultdict
from itertools import groupby, chain
from operator import itemgetter
from typing import Sequence, Iterable, Tuple

import attrs
from decimal import Decimal

from eth_defi.token import TokenDetails

from lps import connectors
from lps.connectors.abs import HasAssetPositions, CanDoOrders
from lps import erc20
from lps.aerodrome import PositionInfo
from lps.connectors import hl
from lps.connectors.hl import HL
from lps.utils import v3_math
from lps.utils.config import get_config

logger = logging.getLogger('hl_hedger')

EPS = Decimal('0.01')
MIN_ORDER_USD = Decimal('10')

def _get_hedge_symbol_for_token(token: TokenDetails) -> str:
    # Potentially account for closely correlated coins if we don't have
    # exact coin traded on the given perps exchange.
    return erc20.canonical_symbol(token.symbol)

def compute_hedges(positions: Iterable[Tuple[PositionInfo, int]]) -> dict[str, Decimal]:
    """
    Given list of positions and their corresponding ticks (pos, tick)
    compute optimal set of perp shorts for hedging.
    Returns symbol->size mapping.
    """
    ret: dict[str, Decimal] = defaultdict(Decimal)
    for pos, tick in positions:
        (amount0, amount1) = v3_math.get_amounts_at_tick(
            pos.tick_lower, pos.tick_upper, pos.liquidity, tick)
        if not erc20.guess_is_stable_coin(pos.token0):
            ret[_get_hedge_symbol_for_token(pos.token0)] += \
                pos.token0.convert_to_decimals(amount0)
        if not erc20.guess_is_stable_coin(pos.token1):
            ret[_get_hedge_symbol_for_token(pos.token1)] += \
                pos.token1.convert_to_decimals(amount1)

    logger.debug(f'Optimal hedge sizes: {ret}')
    return ret

def compute_hedges_50_50(positions: Iterable[Tuple[PositionInfo, int]]) -> dict[str, Decimal]:
    """
    Always hedges 50/50
    """
    ret: dict[str, Decimal] = defaultdict(Decimal)
    for pos, tick in positions:
        middle_tick = (pos.tick_upper + pos.tick_lower) // 2
        (amount0, amount1) = v3_math.get_amounts_at_tick(
            pos.tick_lower, pos.tick_upper, pos.liquidity, middle_tick)
        if not erc20.guess_is_stable_coin(pos.token0):
            ret[_get_hedge_symbol_for_token(pos.token0)] += \
                pos.token0.convert_to_decimals(amount0)
        if not erc20.guess_is_stable_coin(pos.token1):
            ret[_get_hedge_symbol_for_token(pos.token1)] += \
                pos.token1.convert_to_decimals(amount1)

    logger.debug(f'Optimal hedge sizes: {ret}')
    return ret

def compute_hedges_fixed_step(positions: Iterable[Tuple[PositionInfo, int]], threshold: int = 0) -> dict[str, Decimal]:
    ret: dict[str, Decimal] = defaultdict(Decimal)
    for pos, tick in positions:
        width = pos.tick_upper - pos.tick_lower

        hedge_lines = [
            pos.tick_lower,
            pos.tick_lower + int(width / 2),
            pos.tick_upper
        ]

        boundaries = [
            pos.tick_lower,
            pos.tick_upper,
            ]

        i = 0
        while i < len(boundaries) and boundaries[i] < tick:
            i += 1

        # If we are on the edge, just do nothing
        # Not emiting anything for the hedge means that we will not check it at all
        if i >= 1 and abs(boundaries[i - 1] - tick) < threshold:
            continue
        if i < len(boundaries) and abs(boundaries[i] - tick) < threshold:
            continue

        cur_line = hedge_lines[i]

        (amount0, amount1) = v3_math.get_amounts_at_tick(
            pos.tick_lower, pos.tick_upper, pos.liquidity, cur_line)
        if not erc20.guess_is_stable_coin(pos.token0):
            ret[_get_hedge_symbol_for_token(pos.token0)] += \
                pos.token0.convert_to_decimals(amount0)
        if not erc20.guess_is_stable_coin(pos.token1):
            ret[_get_hedge_symbol_for_token(pos.token1)] += \
                pos.token1.convert_to_decimals(amount1)

    logger.debug(f'Optimal hedge sizes: {ret}')
    return ret

def compute_hedges_4_step(positions: Iterable[Tuple[PositionInfo, int]]) -> dict[str, Decimal]:
    ret: dict[str, Decimal] = defaultdict(Decimal)
    for pos, tick in positions:
        width = pos.tick_upper - pos.tick_lower

        hedge_lines = [
            pos.tick_lower,
            pos.tick_lower + 1 * int(width / 4),
            pos.tick_lower + 2 * int(width / 4),
            pos.tick_lower + 3 * int(width / 4),
            pos.tick_upper
        ]

        boundaries = [
            pos.tick_lower,
            pos.tick_lower + int(width / 3),
            pos.tick_lower + 2 * int(width / 3),
            pos.tick_upper,
            ]

        i = 0
        while i < len(boundaries) and boundaries[i] < tick:
            i += 1
        cur_line = hedge_lines[i]

        (amount0, amount1) = v3_math.get_amounts_at_tick(
            pos.tick_lower, pos.tick_upper, pos.liquidity, cur_line)
        if not erc20.guess_is_stable_coin(pos.token0):
            ret[_get_hedge_symbol_for_token(pos.token0)] += \
                pos.token0.convert_to_decimals(amount0)
        if not erc20.guess_is_stable_coin(pos.token1):
            ret[_get_hedge_symbol_for_token(pos.token1)] += \
                pos.token1.convert_to_decimals(amount1)

    logger.debug(f'Optimal hedge sizes: {ret}')
    return ret


def compute_hedge_adjustments(
        conn: HasAssetPositions,
        optimal_hedges: dict[str, Decimal]) -> dict[str, (Decimal, Decimal)]:
    """
    Given map (symbol -> optimal hedge size), compute map:
        symbol -> (old position size, new position size)
    Remove positions that don't need to be updated.
    """
    positions = conn.get_user_positions()
    mids = conn.get_mid_prices(*optimal_hedges.keys())

    ret: dict[str, (Decimal, Decimal)] = {}
    for symbol, optimal_hedge_size in optimal_hedges.items():
        current_hedge_size_sign = positions[symbol].szi \
                if symbol in positions \
                else 0
        current_hedge_size = abs(current_hedge_size_sign)

        current_hedge_value = current_hedge_size * mids[symbol]
        optimal_hedge_value = optimal_hedge_size * mids[symbol]
        logger.debug(f'{symbol}: {current_hedge_value:.2f}$ cur {optimal_hedge_value:.2f}$ opt')

        diff = abs(optimal_hedge_value - current_hedge_value)
        if diff < MIN_ORDER_USD:
            # Almost zero diff, should keep things as they are
            should_update_hedge = False
        else:
            if optimal_hedge_value < EPS:
                # Always close a position if we can
                # I don't think this is necessary but keeps cleaner positions
                should_update_hedge = True
            else:
                should_update_hedge = \
                    diff > Decimal(get_config().hl_hedger.max_unhedged_value)

        if should_update_hedge:
            old_position_size =  current_hedge_size_sign
            new_position_size = -optimal_hedge_size
            assert symbol not in ret, "should have unique symbols"
            ret[symbol] = (old_position_size, new_position_size)

    return ret

def execute_hedge_adjustements(
        conn: CanDoOrders, hedge_adjustements: dict[str, (Decimal, Decimal)]) -> int:
    """
    Executes orders to adjust hedges according to the input map:
        symbol -> (old position size, new position size)
    TODO: Move this into connector.abs
    """

    if len(hedge_adjustements) > 0:
        logger.info(f'Adjusting hedge positions: {hedge_adjustements}')

    updated_count = 0
    for symbol, sz in hedge_adjustements.items():
        (old_position_size, new_position_size) = sz
        assert old_position_size <= 0, 'always shorting'
        assert new_position_size <= 0, 'always shorting'
        try:
            connectors.abs.adjust_position(
                conn, symbol, old_position_size, new_position_size)
            updated_count += 1
        except hl.HLException:
            logger.warning(f'Failed to update hedge position {symbol, old_position_size, new_position_size}')
            continue

    if len(hedge_adjustements) > 0:
        logger.info(f'Updated {updated_count} hedges')
    return updated_count
