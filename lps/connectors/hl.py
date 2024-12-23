import logging
import time
from operator import itemgetter
from typing import TypedDict, Iterator
from decimal import Decimal

import attrs
import eth_account
from eth_account.signers.local import LocalAccount
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from hyperliquid.utils.types import Meta

from lps.utils.config import get_config

logger = logging.getLogger('hl_connector')

_hl_info: Info | None = None
_hl_exchange: Exchange | None = None
_public_addr: str | None = None

@attrs.frozen
class HL:
    info: Info
    exchange: Exchange
    public_addr: str

    sz_decimals: dict[str, int] # cached szDecimals for perps only so far

class HLException(Exception):
    pass

def start() -> HL:
    logger.info('Starting')

    if get_config().hyperliquid.use_testnet:
        api_url = constants.TESTNET_API_URL
        public_addr = get_config().hyperliquid.testnet.wallet_address
        private_key = get_config().hyperliquid.testnet.private_key
    else:
        api_url = constants.MAINNET_API_URL
        public_addr = get_config().hyperliquid.main.wallet_address
        private_key = get_config().hyperliquid.main.private_key

    logger.info('Loading meta')
    info = Info(api_url, skip_ws=True)

    account: LocalAccount = eth_account.Account.from_key(private_key)
    exchange = Exchange(account,
                        api_url,
                        account_address=get_config().hyperliquid.testnet.wallet_address)

    logger.info('Loading sz decimals')
    sz_decimals = {m['name']: m['szDecimals'] for m in info.meta()['universe']}

    hl_connection = HL(
        info=info,
        sz_decimals=sz_decimals,
        exchange=exchange,
        public_addr=public_addr)

    logger.info('Updating leverages')
    for coin, leverage in get_config().hyperliquid.leverages.items():
        exchange.update_leverage(leverage, coin)

    logger.info('Started')

    return hl_connection

class HLPosition(TypedDict, total=False):
    positionValue: str
    szi: str

def get_user_positions(hl: HL) -> dict[str, HLPosition]:
    positions = hl.info.user_state(hl.public_addr)['assetPositions']

    ret: dict[str, HLPosition] = {}
    for pos in map(itemgetter('position'), positions):
        assert pos['coin'] not in ret, "duplicate positions on hl"
        ret[pos['coin']] = pos
    return ret

def get_mid_prices(hl: HL, *names: list[str]) -> dict[str, Decimal]:
    mids = hl.info.all_mids()
    return {name: Decimal(mids[name]) for name in names}

def round_sz(hl: HL, size: Decimal, name: str) -> Decimal:
    """
    Correctly round asset size according to the HL meta info
    """
    return round(size, hl.sz_decimals[name])

def _attempt_market_order(hl: HL, name: str, size: Decimal) -> Decimal:
    """
    Executes IoC order at best possible price. Returns actual executed size.
    Exception only when something malfunctions in the connection itself.
    """
    logger.info(f'Posting order {name} {size}')

    order = hl.exchange.market_open(
        name=name,
        is_buy=size > 0,
        sz=float(abs(size)),
        slippage=get_config().hyperliquid.market_order_slippage,
    )
    logger.info(f'Executed order: {order}')
    executed_size = Decimal(order['response']['data']['statuses'][0]['filled']['totalSz'])
    if executed_size != size:
        logger.warning(f'Failed to execute full order {order}')
    return executed_size

def market_order(hl: HL, name: str, size: Decimal):
    """
    Exhaustively executes order but no more than max_retries attempts.
    Exception if failed to execute.
    """

    retry_cnt = 0
    while abs(size) > 0 and retry_cnt < get_config().hyperliquid.max_retries:
        try:
            executed_size = _attempt_market_order(hl, name, size)
            if size < 0:
                executed_size = -executed_size
            size -= executed_size
        except Exception as e:
            logger.exception(f'Failed to execute order: {e} {retry_cnt}')
        retry_cnt += 1
    if size != 0:
        raise HLException("Failed to execute the order")

def adjust_position(hl: HL, name: str, from_size: Decimal, to_size: Decimal):
    """
    Note: from_size should equal to the current position size
    """
    assert name in hl.info.name_to_coin

    diff = round_sz(hl, to_size - from_size, name)
    if diff == 0:
        return
    market_order(hl, name, diff) # exception on failure
