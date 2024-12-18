import logging
from operator import itemgetter
from typing import TypedDict
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
class _HLConnection:
    info: Info
    exchange: Exchange
    public_addr: str

    sz_decimals: dict[str, int] # cached szDecimals for perps only so far

_hl_connection: _HLConnection | None = None

class HLException(Exception):
    pass

def start():
    global _hl_connection
    assert _hl_connection is None

    logger.info('Starting')

    if get_config().hyperliquid.use_testnet:
        api_url = constants.TESTNET_API_URL
        public_addr = get_config().hyperliquid.testnet.wallet_address
        private_key = get_config().hyperliquid.testnet.private_key
    else:
        api_url = constants.MAINNET_API_URL
        public_addr = get_config().hyperliquid.main.wallet_address
        private_key = get_config().hyperliquid.main.private_key

    info = Info(api_url, skip_ws=True)

    account: LocalAccount = eth_account.Account.from_key(private_key)
    exchange = Exchange(account,
                        api_url,
                        account_address=get_config().hyperliquid.testnet.wallet_address)

    sz_decimals = {m['name']: m['szDecimals'] for m in info.meta()['universe']}

    _hl_connection = _HLConnection(
        info=info,
        sz_decimals=sz_decimals,
        exchange=exchange,
        public_addr=public_addr)

    for coin, leverage in get_config().hyperliquid.leverages.items():
        exchange.update_leverage(leverage, coin)

    logger.info('Started')

class HLPosition(TypedDict, total=False):
    positionValue: str
    szi: str

def get_user_positions() -> dict[str, HLPosition]:
    assert _hl_connection is not None
    positions = _hl_connection.info.user_state(_hl_connection.public_addr)['assetPositions']

    ret: dict[str, HLPosition] = {}
    for pos in map(itemgetter('position'), positions):
        assert pos['coin'] not in ret, "duplicate positions on hl"
        ret[pos['coin']] = pos
    return ret

def round_sz(size: Decimal, name: str) -> Decimal:
    """
    Correctly round asset size according to the HL meta info
    """
    return round(size, _hl_connection.sz_decimals[name])

def adjust_position(name: str, from_size: Decimal, to_size: Decimal):
    """
    Note: from_size should equal to the current position size
    """
    assert name in _hl_connection.info.name_to_coin

    diff = round_sz(to_size - from_size, name)
    if diff == 0:
        return

    # TODO: Use exchange.order is it's going to be faster and cheaper
    retry_cnt = 0
    while retry_cnt < get_config().hyperliquid.max_retries:
        try:
            sz = float(abs(diff))
            logger.info(f'Posting order {name} {diff} {sz}')
            order = _hl_connection.exchange.market_open(
                name=name,
                is_buy=diff > 0,
                sz=sz,
                slippage=get_config().hyperliquid.market_order_slippage,
            )
            logger.info(f'Executed order: {order}')
            if order['response']['data']['statuses'][0]['filled']['totalSz'] != str(sz):
                logger.info(f'Retrying {retry_cnt}')
                retry_cnt += 1
                continue
            return
        except Exception as e:
            logger.exception(f'Failed to execute order: {e} {retry_cnt}')
            retry_cnt += 1
            continue
    raise HLException("Failed to execute the order")
