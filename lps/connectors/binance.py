import logging

import attrs
import ccxt.binance
from decimal import Decimal

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

# exchange.load_markets()
# orderbook = exchange.fetch_order_book('ETH/USD')
# bid = orderbook['bids'][0][0] if len (orderbook['bids']) > 0 else None
# ask = orderbook['asks'][0][0] if len (orderbook['asks']) > 0 else None
# spread = (ask - bid) if (bid and ask) else None
# print (exchange.id, 'market price', { 'bid': bid, 'ask': ask, 'spread': spread })
