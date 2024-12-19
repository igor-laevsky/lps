from lps.utils.config import get_config, load_configuration, logging_config
import logging.config

load_configuration('dev')
logging.config.dictConfig(logging_config())

from web3 import Web3

from lps import erc20, hl_hedger
from lps.aerodrome import PositionInfo, CLPoolInfo

import os
import sys
from pprint import pprint

import ccxt  # noqa: E402
import eth_account
from eth_account.signers.local import LocalAccount
from hyperliquid.utils.types import Cloid
from decimal import Decimal


from hyperliquid.info import Info
from hyperliquid.utils import constants
from hyperliquid.exchange import Exchange

from lps.connectors import hl

# hl.start()
# w3 = Web3(Web3.HTTPProvider(get_config().base_node_url))


# How to get market price from binance
exchange = ccxt.binance({
    'apiKey': get_config().binance.main.api_key,
    'secret': get_config().binance.main.api_secret,
})

exchange.load_markets()
orderbook = exchange.fetch_order_book('ETH/USD')
bid = orderbook['bids'][0][0] if len (orderbook['bids']) > 0 else None
ask = orderbook['asks'][0][0] if len (orderbook['asks']) > 0 else None
spread = (ask - bid) if (bid and ask) else None
print (exchange.id, 'market price', { 'bid': bid, 'ask': ask, 'spread': spread })


# TODO: This should be unit test
#
# pos = PositionInfo(
#     token0=erc20.fetch_erc20_details_cached(w3, '0x4200000000000000000000000000000000000006'),
#     token1=erc20.fetch_erc20_details_cached(w3, '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'),
#     tick_lower=-194200,
#     tick_upper=-192600,
#     liquidity=180540158377974,
#     nft_id=3899989,
#     pool=CLPoolInfo(
#         token0=erc20.fetch_erc20_details_cached(w3, '0x4200000000000000000000000000000000000006'),
#         token1=erc20.fetch_erc20_details_cached(w3, '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'),
#         tick_spacing=100,
#         fee_pips=400,
#         contract=None
#     ),
# )

# print('Start in the middle')
# hl_hedger.adjust_hedge(pos, -193400)
# input()
#
# print('Outside lower bound')
# hl_hedger.adjust_hedge(pos, -194500)
# input()
#
# print('Still outside')
# hl_hedger.adjust_hedge(pos, -194300)
# input()
#
# print('On the lower endge')
# hl_hedger.adjust_hedge(pos, -194200)
# input()
#
# print('In the middle')
# hl_hedger.adjust_hedge(pos, -193400)
# input()
#
# print('Small change')
# hl_hedger.adjust_hedge(pos, -193410)
# input()
#
# print('Some change')
# hl_hedger.adjust_hedge(pos, -193500)
# input()
#
# print('Close to the upper edge')
# hl_hedger.adjust_hedge(pos, -192500)
# input()
#
# print('On the upper edge')
# hl_hedger.adjust_hedge(pos, -192600)
# input()
#
# print('Upper overflow')
# hl_hedger.adjust_hedge(pos, -19300)
# input()


# info = Info(constants.MAINNET_API_URL, skip_ws=True)
# user_state = info.user_state(get_config().hyperliquid.testnet.wallet_address)
# print(user_state)
#
# account: LocalAccount = eth_account.Account.from_key(
#     get_config().hyperliquid.testnet.private_key)
#
# exchange = Exchange(account,
#                     constants.TESTNET_API_URL,
#                     account_address=get_config().hyperliquid.testnet.wallet_address)
#
# pprint(info.user_state(get_config().hyperliquid.testnet.wallet_address))

# Don't forget to set up leverage
# order = exchange.market_open('ETH', True, 0.01, None, 0.02, Cloid.from_int(1))
# pprint(order)

# res = exchange.market_close('ETH', cloid=Cloid.from_int(1))
# pprint(res)

# How to get market price from binance
# exchange = ccxt.binance({
#     'apiKey': get_config().binance.main.api_key,
#     'secret': get_config().binance.main.api_secret,
# })
#
# exchange.load_markets()
# orderbook = exchange.fetch_order_book('ETH/USD')
# bid = orderbook['bids'][0][0] if len (orderbook['bids']) > 0 else None
# ask = orderbook['asks'][0][0] if len (orderbook['asks']) > 0 else None
# spread = (ask - bid) if (bid and ask) else None
# print (exchange.id, 'market price', { 'bid': bid, 'ask': ask, 'spread': spread })


# test_exchange = ccxt.hyperliquid({
#     'walletAddress': '',
#     'privateKey': '',
#     'options': {
#         'defaultType': 'future',
#     },
# })
#
# markets = test_exchange.load_markets()
#
# test_exchange.set_sandbox_mode(True)
# test_exchange.verbose = True
# pprint(test_exchange.fetch_balance())
#
# request: dict = {
#     'type': 'allMids',
# }
# all_mids = test_exchange.publicPostInfo(request)
#
# order = test_exchange.create_order(
#     symbol='ETH/USDC:USDC',
#     type='market',
#     side='buy',
#     amount=0.01,
#     price=all_mids['ETH'],
#     params={
#         'slippage': 0.05
#     }
# )
# pprint(order)

#
# exchange = ccxt.hyperliquid({
#     #'walletAddress': '',
#     'walletAddress': '',
#     'privateKey': '',
#     'options': {
#         'defaultType': 'future',
#     },
# })

#exchange.set_sandbox_mode(True)  # comment if you're not using the testnet
# markets = exchange.load_markets()
# pprint(markets)
# exchange.verbose = True  # debug output
#
# balance = exchange.fetch_balance()
# pprint(balance)

# positions = exchange.fetch_positions()
# pprint(positions)