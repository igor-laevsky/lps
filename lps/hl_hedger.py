import itertools
import logging
from collections import defaultdict
from itertools import groupby, chain
from operator import itemgetter
from typing import Sequence, Iterable, Tuple

import attrs
from decimal import Decimal

from eth_defi.token import TokenDetails

from lps import erc20
from lps.aerodrome import PositionInfo
from lps.connectors import hl
from lps.connectors.hl import HL
from lps.utils import v3_math
from lps.utils.config import get_config

logger = logging.getLogger('hl_hedger')

# TODO: Min order in HL is 10 USD, but this is in asset size
MIN_ORDER = Decimal('0.001')

def _get_volatile_coin_name(pos: PositionInfo) -> str:
    # Potentially account for closely correlated coins if we don't have
    # exact coin traded on the given perps exchange.
    return erc20.canonic_symbol(pos.base.symbol)

def _compute_optimal_hedge(pos: PositionInfo, current_tick: int) -> Decimal:
    (amount0, amount1) = v3_math.get_amounts_at_tick(
        pos.tick_lower, pos.tick_upper, pos.liquidity, current_tick)

    (base_amount, quote_amount) = pos.match_base_quote(amount0, amount1)

    return pos.base.convert_to_decimals(base_amount)

def adjust_hedge(a_hl: HL, pos: PositionInfo, current_tick: int):
    hedge_coin = _get_volatile_coin_name(pos)
    positions = hl.get_user_positions(a_hl)

    current_hedge_size_sign = Decimal(positions[hedge_coin]['szi']) \
            if hedge_coin in positions \
            else 0
    current_hedge_size = abs(current_hedge_size_sign)
    optimal_hedge_size = hl.round_sz(a_hl,
        _compute_optimal_hedge(pos, current_tick), hedge_coin)

    diff = optimal_hedge_size - current_hedge_size
    if abs(diff) < MIN_ORDER:
        # Almost zero diff, should keep things as they are
        should_update_hedge = False
    else:
        if optimal_hedge_size < MIN_ORDER:
            # Basically closes the position, use MIN_ORDER as epsilon really
            should_update_hedge = True
        else:
            diff_ratio = diff / optimal_hedge_size
            should_update_hedge = \
                abs(diff_ratio) > Decimal(get_config().hl_hedger.rebalance_threshold) / 100

    if not should_update_hedge:
        logger.debug('Decided not to update hedge position')
        return

    logger.info('Updating hedge position')

    logger.info(f'Optimal hedge: {optimal_hedge_size} '
                f'current_hedge: {current_hedge_size} '
                f'in {hedge_coin}')

    new_position_size = -optimal_hedge_size
    old_position_size =  current_hedge_size_sign
    assert old_position_size <= 0, 'always shorting'
    assert new_position_size <= 0, 'always shorting'
    try:
        hl.adjust_position(a_hl, hedge_coin, old_position_size, new_position_size)
        logger.info('Successfully updated hedge position')
    except hl.HLException:
        logger.warning('Failed to execute hedge rebalancing, will try next time')

def is_hedgable(positions: list[PositionInfo]) -> bool:
    """
    Checks that we can hedge all the positions together.
    At the moment this means we can only support one volatile currency per position.
    And each volatile currency must be unique.
    These limitations are going to be lifted with time.
    """
    seen_base = set()
    for pos in positions:
        if not erc20.guess_is_stable_coin(pos.token0) and not erc20.guess_is_stable_coin(pos.token0):
            logger.warning(f"Can't hedge position {pos.nft_id} because both currencies are volatile")
            return False
        if pos.base in seen_base:
            logger.warning(f"Can't hedge position {pos.nft_id} because there is duplicate base currency")
            return False
        seen_base.add(pos.base)
    return True

def _get_hedge_symbol_for_token(token: TokenDetails) -> str:
    # Potentially account for closely correlated coins if we don't have
    # exact coin traded on the given perps exchange.
    return erc20.canonic_symbol(token.symbol)

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

def compute_hedge_adjustments(a_hl: HL, optimal_hedges: dict[(str, Decimal)]) -> dict[str, (Decimal, Decimal)]:
    """
    Given map symbol -> optimal hedge size, compute map:
        symbol -> (old position size, new position size)
    Remove positions that don't need to be updated.
    TODO: Better to remove dependency on hl_connector and just accept plain data
    """
    positions = hl.get_user_positions(a_hl)

    ret: dict[str, (Decimal, Decimal)] = {}
    for symbol, optimal_hedge_size in optimal_hedges.items():
        current_hedge_size_sign = Decimal(positions[symbol]['szi']) \
                if symbol in positions \
                else 0
        current_hedge_size = abs(current_hedge_size_sign)

        diff = optimal_hedge_size - current_hedge_size
        if abs(diff) < MIN_ORDER:
            # Almost zero diff, should keep things as they are
            should_update_hedge = False
        else:
            if optimal_hedge_size < MIN_ORDER:
                # Basically closes the position, use MIN_ORDER as epsilon really
                should_update_hedge = True
            else:
                diff_ratio = diff / optimal_hedge_size
                should_update_hedge = \
                    abs(diff_ratio) > Decimal(get_config().hl_hedger.rebalance_threshold) / 100

        if should_update_hedge:
            old_position_size =  current_hedge_size_sign
            new_position_size = -optimal_hedge_size
            ret[symbol] = (old_position_size, new_position_size)

    return ret

def execute_hedge_adjustements(a_hl: HL, hedge_adjustements: dict[str, (Decimal, Decimal)]):
    """
    Executes orders to adjust hedges according to the input map:
        symbol -> (old position size, new position size)
    TODO: This move into connextor `adjust_positions`
    """

    if len(hedge_adjustements) > 0:
        logger.info(f'Adjusting hedge positions: {hedge_adjustements}')

    updated_count = 0
    for symbol, sz in hedge_adjustements.items():
        (old_position_size, new_position_size) = sz
        assert old_position_size <= 0, 'always shorting'
        assert new_position_size <= 0, 'always shorting'
        try:
            hl.adjust_position(a_hl, symbol, old_position_size, new_position_size)
            updated_count += 1
        except hl.HLException:
            logger.warning(f'Failed to update hedge position {symbol, old_position_size, new_position_size}')
            continue

    if len(hedge_adjustements) > 0:
        logger.info(f'Updated {updated_count} hedges')
