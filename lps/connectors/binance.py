import logging

import attrs
import ccxt.binance
from decimal import Decimal

from eth_defi.token import TokenDetails

import erc20
from lps.utils.config import get_config

logger = logging.getLogger('binance')

class BinanceException(Exception):
    pass

@attrs.frozen
class Binance:
    exchange: ccxt.binance

def start() -> Binance:
    logger.info('Starting')
    e = ccxt.binance({
            'apiKey': get_config().binance.main.api_key,
            'secret': get_config().binance.main.api_secret,
        })
    e.load_markets()
    logger.info('Started')
    return Binance(
        exchange=e
    )

def mid_price(client: Binance, base: str, quote: str) -> Decimal:
    orderbook = client.exchange.fetch_order_book(f'{base}/{quote}')
    bid = orderbook['bids'][0][0] if len (orderbook['bids']) > 0 else None
    ask = orderbook['asks'][0][0] if len (orderbook['asks']) > 0 else None
    if bid is None and ask is None:
        raise BinanceException(f"Unable to get mid price for {name}")
    if bid is None:
        return Decimal(ask)
    if ask is None:
        return Decimal(bid)
    return Decimal(bid) + (Decimal(ask) - Decimal(bid)) / 2

def usd_price_at_time(client: Binance, base: str, timestamp_sec: int) -> Decimal:
    """
    Note: not super precise but good for user interface
    """

    timestamp_ms = timestamp_sec * 1000
    response = client.exchange.fetch_ohlcv(f'{base}/USDT', '1m', timestamp_ms, 1)

    return Decimal(response[0][3]) # lowest value in one minute

def token_value_in_usd_at_time(
        client: Binance,
        token: TokenDetails,
        raw_amount: int,
        timestamp_sec: int) -> Decimal:
    """
    Just a helper for the `usd_price_at_time`.
    `raw_amount` is in WEI (or less depending on decimals)
    """
    if erc20.guess_is_stable_coin(token):
        price = Decimal(1) # Not always true, but good enough
    else:
        price = usd_price_at_time(
            client, erc20.canonical_symbol(token.symbol), timestamp_sec)
    return token.convert_to_decimals(raw_amount) * price
