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

from lps.aerodrome import get_position_info_cached, clear_caches
from lps.connectors import hl
from lps.utils import v3_math
from lps import hl_hedger, erc20

import requests
from decimal import Decimal

from eth_defi.chain import install_retry_middleware
from eth_defi.event_reader.block_time import measure_block_time

from web3 import Web3
from eth_defi.event_reader.fast_json_rpc import patch_web3

from lps.connectors import binance

logger = logging.getLogger('main')

w3 = create_base_web3()
a_binance = binance.start()

@attrs.frozen
class MintInfo:
    token_id: int
    block_number: int

def get_all_position_mints(w3: Web3, user_addr: str) -> Iterator[MintInfo]:
    """
    Returns list of position mint for the given user
    """
    aero_nft_manager = create_contract_cached(
        w3, "aerodrome_nft_manager.json")

    # Transfer from zero is a mint
    filter = aero_nft_manager.events.Transfer.create_filter(
        fromBlock="earliest",
        argument_filters={
            'from': Web3.to_checksum_address('0x0000000000000000000000000000000000000000'),
            'to': Web3.to_checksum_address(user_addr)
        }
    )

    yield from map(
        lambda log: MintInfo(token_id=log['args']['tokenId'],
                           block_number=log['blockNumber']),
        filter.get_all_entries())

@attrs.frozen
class ClaimInfo:
    timestamp_sec: int
    amount_usd: Decimal
    token_id: int

def get_token_id_from_vfat_harvest_transaction(w3: Web3, tr: TxData) -> int:
    nft_farm_strategy_v2 = create_contract_cached(w3, "vfat_nft_farm_strategy_v2.json")
    nft_farm_strategy_v1 = create_contract_cached(w3, "vfat_nft_farm_strategy_v1.json")

    try:
        (func, args) = nft_farm_strategy_v2.decode_function_input(tr['input'])
    except ValueError:
        (func, args) = nft_farm_strategy_v1.decode_function_input(tr['input'])

    assert func.fn_name in ('harvest', 'exit'), f"not a vfat transaction {tr['hash']}"

    return args['position']['tokenId']

def get_all_claim_rewards(w3: Web3, user_addr: str) -> Iterator[ClaimInfo]:
    """
    Returns all reward claims for the given user
    Note: this only supports vfat for now
    """
    cl_gauge = create_contract_cached(w3, "aerodrome_cl_gauge.json")

    filter = cl_gauge.events.ClaimRewards.create_filter(
        fromBlock="earliest",
        argument_filters={
            'from': Web3.to_checksum_address(user_addr),
        }
    )

    reward_token = erc20.fetch_erc20_details_cached(
        w3, get_config().aerodrome.aero_token)

    def from_log_recp(log: LogReceipt) -> ClaimInfo:
        tr = w3.eth.get_transaction(log['transactionHash'])
        block = w3.eth.get_block(log['blockNumber'])

        amount_usd = binance.token_value_in_usd_at_time(
            a_binance, reward_token, log['args']['amount'], block['timestamp'])

        return ClaimInfo(
            token_id = get_token_id_from_vfat_harvest_transaction(w3, tr),
            amount_usd = amount_usd,
            timestamp_sec = int(block['timestamp'])
        )

    yield from map(from_log_recp, filter.get_all_entries())

def print_position_info(
        w3: Web3,
        pos: aerodrome.PositionInfo,
        claims: Iterable[ClaimInfo],
        mint: MintInfo):

    minted_timestamp_sec = w3.eth.get_block(mint.block_number)['timestamp']
    age = \
        datetime.now() - datetime.fromtimestamp(minted_timestamp_sec)
    age_str = humanize.naturaldelta(age)

    total_rewards_usd = sum(map(attrgetter('amount_usd'), claims))

    def get_usd_value_at_tick(tick: int):
        (amount0, amount1) = v3_math.get_amounts_at_tick(
            pos.tick_lower, pos.tick_upper, pos.liquidity, tick)
        amount0_usd = binance.token_value_in_usd_at_time(
            a_binance, pos.pool.token0, amount0, minted_timestamp_sec)
        amount1_usd = binance.token_value_in_usd_at_time(
            a_binance, pos.pool.token1, amount1, minted_timestamp_sec)
        return amount0_usd + amount1_usd

    tick_at_mint = pos.pool.get_slot0(w3, block=mint.block_number).tick
    deposit_usd = get_usd_value_at_tick(tick_at_mint)

    print(
        f"ID: {pos.nft_id}\tPool: {pos.pool.token0.symbol}/{pos.pool.token1.symbol}\tAge: {age_str}\tFees:{total_rewards_usd:.2f}$\tDeposit {deposit_usd:.2f}$"
    )


mints = list(get_all_position_mints(w3, '0x84fcd2463483e8f8dc4190c65679592f2358c314'))
position_infos = list(map(
    lambda m: aerodrome.get_position_info_cached(w3, m.token_id, block=m.block_number),
    mints))

all_claims = list(get_all_claim_rewards(w3, '0x84fcd2463483e8f8dc4190c65679592f2358c314'))

claims_by_token_id = defaultdict(list)
for claim in all_claims:
    claims_by_token_id[claim.token_id].append(claim)

for pos, mint in zip(position_infos, mints):
    print_position_info(w3, pos, claims_by_token_id[pos.nft_id], mint)
