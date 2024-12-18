import itertools
import logging
from itertools import groupby, chain
from operator import itemgetter

import attrs
from decimal import Decimal

from lps.aerodrome import PositionInfo
from lps.connectors import hl
from lps.utils import v3_math
from lps.utils.config import get_config

logger = logging.getLogger('hl_hedger')

_CORRS = {
    'WETH': 'ETH',
    'cbBTC': 'BTC',
    'tBTC': 'BTC'
}

# TODO: Min order in HL is 10 USD, but this is in asset size
MIN_ORDER = Decimal('0.001')

def _get_hedge_coin_name(pos: PositionInfo) -> str:
    if pos.base.symbol in _CORRS:
        return _CORRS[pos.base.symbol]
    return pos.base.symbol

def _compute_optimal_hedge(pos: PositionInfo, current_tick: int) -> Decimal:
    (amount0, amount1) = v3_math.get_amounts_at_tick(
        pos.tick_lower, pos.tick_upper, pos.liquidity, current_tick)

    (base_amount, quote_amount) = pos.match_base_quote(amount0, amount1)

    return pos.base.convert_to_decimals(base_amount)

def adjust_hedge(pos: PositionInfo, current_tick: int):
    hedge_coin = _get_hedge_coin_name(pos)
    positions = hl.get_user_positions()

    current_hedge_size_sign = Decimal(positions[hedge_coin]['szi']) \
            if hedge_coin in positions \
            else 0
    current_hedge_size = abs(current_hedge_size_sign)
    optimal_hedge_size = hl.round_sz(
        _compute_optimal_hedge(pos, current_tick), hedge_coin)

    logger.info(f'Optimal hedge: {optimal_hedge_size} '
                f'current_hedge: {current_hedge_size} '
                f'in {hedge_coin}')

    # TODO: Consider computing this in USD instead
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
        logger.info('Decided not to update hedge position')
        return

    logger.info('Updating hedge position')

    new_position_size = -optimal_hedge_size
    old_position_size =  current_hedge_size_sign
    assert old_position_size <= 0, 'always shorting'
    assert new_position_size <= 0, 'always shorting'
    try:
        hl.adjust_position(hedge_coin, old_position_size, new_position_size)
        logger.info('Successfully updated hedge position')
    except hl.HLException:
        logger.warning('Failed to execute hedge rebalancing, will try next time')
