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
from lps import hedger, erc20

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
        address=get_config().aerodrome.nft_position_manager,
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
class BurnInfo:
    token_id: int
    block_number: int

def get_all_position_burns(w3: Web3, user_addr: str) -> Iterator[BurnInfo]:
    """
    Returns list of position burns for the given user
    """
    aero_nft_manager = create_contract_cached(
        w3, "aerodrome_nft_manager.json")

    # Transfer from zero is a mint
    filter = aero_nft_manager.events.Transfer.create_filter(
        fromBlock="earliest",
        address=get_config().aerodrome.nft_position_manager,
        argument_filters={
            'from': Web3.to_checksum_address(user_addr),
            'to': Web3.to_checksum_address('0x0000000000000000000000000000000000000000')
        }
    )

    yield from map(
        lambda log: BurnInfo(token_id=log['args']['tokenId'],
                             block_number=log['blockNumber']),
        filter.get_all_entries())

@attrs.frozen
class ClaimInfo:
    timestamp_sec: int
    amount_usd: Decimal
    token_id: int

def _get_token_id_from_harvest_transaction(w3: Web3, tr: TxData) -> int:
    nft_farm_strategy_v2 = create_contract_cached(w3, "vfat_nft_farm_strategy_v2.json")
    nft_farm_strategy_v1 = create_contract_cached(w3, "vfat_nft_farm_strategy_v1.json")
    aero_cl_gauge = create_contract_cached(w3, "aerodrome_cl_gauge.json")

    for contract in (nft_farm_strategy_v2, nft_farm_strategy_v1, aero_cl_gauge):
        try:
            (func, args) = contract.decode_function_input(tr['input'])
        except ValueError:
            continue

        if func.fn_name in ('harvest', 'exit'):
            return args['position']['tokenId']
        elif func.fn_name in ('getReward', 'withdraw'):
            return args['tokenId']
        else:
            assert False, f"unrecognized func name shouldn't happen {tr['hash'].hex()} {func.fn_name}"
    raise Exception(f"Unrecognized claim rewards transaction {tr['hash'].hex()}")

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
            token_id = _get_token_id_from_harvest_transaction(w3, tr),
            amount_usd = amount_usd,
            timestamp_sec = int(block['timestamp'])
        )

    yield from map(from_log_recp, filter.get_all_entries())

def print_position_info(
        w3: Web3,
        pos: aerodrome.PositionInfo,
        claims: Iterable[ClaimInfo],
        mint: MintInfo,
        burn: BurnInfo | None):

    minted_block_number = mint.block_number
    burned_block_number = burn.block_number if burn else 'finalized'

    minted_timestamp_sec = w3.eth.get_block(minted_block_number)['timestamp']
    burned_timestamp_sec = w3.eth.get_block(burned_block_number)['timestamp']

    age = \
        datetime.now() - datetime.fromtimestamp(minted_timestamp_sec)
    age_sec = age.total_seconds()
    age_str = humanize.precisedelta(
        age, suppress=['minutes', 'seconds', 'milliseconds', 'microseconds'])

    total_rewards_usd = sum(map(attrgetter('amount_usd'), claims))

    def get_usd_value_at_tick(tick: int, timestamp_sec: int):
        (amount0, amount1) = v3_math.get_amounts_at_tick(
            pos.tick_lower, pos.tick_upper, pos.liquidity, tick)
        amount0_usd = binance.token_value_in_usd_at_time(
            a_binance, pos.pool.token0, amount0, timestamp_sec)
        amount1_usd = binance.token_value_in_usd_at_time(
            a_binance, pos.pool.token1, amount1, timestamp_sec)
        return amount0_usd + amount1_usd

    tick_at_mint = pos.pool.get_slot0(w3, block=minted_block_number).tick
    deposit_usd = get_usd_value_at_tick(tick_at_mint, minted_timestamp_sec)
    price_at_mint = v3_math.tick_to_price(tick_at_mint)

    tick_at_burn = pos.pool.get_slot0(w3, block=burned_block_number).tick
    burn_usd = get_usd_value_at_tick(tick_at_burn, burned_timestamp_sec)
    price_at_burn = v3_math.tick_to_price(tick_at_burn)

    (deposit0_raw, deposit1_raw) = v3_math.get_amounts_at_tick(
            pos.tick_lower, pos.tick_upper, pos.liquidity, tick_at_mint)
    deposit0 = pos.pool.token0.convert_to_decimals(deposit0_raw)
    deposit0_usd = binance.token_value_in_usd_at_time(
        a_binance, pos.pool.token0, deposit0_raw, minted_timestamp_sec)

    deposit1 = pos.pool.token0.convert_to_decimals(deposit1_raw)
    deposit1_usd = binance.token_value_in_usd_at_time(
        a_binance, pos.pool.token1, deposit1_raw, minted_timestamp_sec)

    deposit0_price_usd = binance.usd_price_at_time(
        a_binance, pos.pool.token0.symbol, minted_timestamp_sec)
    deposit1_price_usd = binance.usd_price_at_time(
        a_binance, pos.pool.token1.symbol, minted_timestamp_sec)

    (burn0_raw, burn1_raw) = v3_math.get_amounts_at_tick(
            pos.tick_lower, pos.tick_upper, pos.liquidity, tick_at_burn)
    burn0 = pos.pool.token0.convert_to_decimals(burn0_raw)
    burn0_usd = binance.token_value_in_usd_at_time(
        a_binance, pos.pool.token0, burn0_raw, burned_timestamp_sec)

    burn1 = pos.pool.token0.convert_to_decimals(burn1_raw)
    burn1_usd = binance.token_value_in_usd_at_time(
        a_binance, pos.pool.token1, burn1_raw, burned_timestamp_sec)

    burn0_price_usd = binance.usd_price_at_time(
        a_binance, pos.pool.token0.symbol, burned_timestamp_sec)
    burn1_price_usd = binance.usd_price_at_time(
        a_binance, pos.pool.token1.symbol, burned_timestamp_sec)

    avg_fees_per_day = (total_rewards_usd / Decimal(age_sec)) * (24 * 60 * 60)

    # Asset change in USD

    lower_price = v3_math.tick_to_price(pos.tick_lower)
    upper_price = v3_math.tick_to_price(pos.tick_upper)
    burned_price = v3_math.tick_to_price(tick_at_burn)
    width = Decimal(abs(pos.tick_lower - pos.tick_upper)) * v3_math.TICK_BASE / 100

    range_status = 'In range'
    if not pos.tick_lower <= tick_at_burn < pos.tick_upper:
        range_status = 'Out of range!'

    print(
        f"ID: {pos.nft_id}\tPool: {pos.pool.token0.symbol}/{pos.pool.token1.symbol}\tAge: {age_str}\tFees: {total_rewards_usd:.2f}$"
    )
    print(f'Range: ({lower_price:.6f}) <-- ({burned_price:.6f}) --> ({upper_price:.6f}) {width:.2f}% ({range_status})')
    print(f'Avg fees per day: {avg_fees_per_day:.2f}$ {(avg_fees_per_day / deposit_usd) * 100:.2f}%')
    print(f'Price at mint: {price_at_mint:.5f}')
    print(f'Price at burn: {price_at_burn:.5f}')
    print(f'Deposited: {deposit_usd:.2f}$ ({deposit0:.4f}, {deposit1:.4f}) ({deposit0_usd:.2f}$, {deposit1_usd:.2f}$) ({deposit0_price_usd:.2f}$ {deposit1_price_usd:.2f}$)')
    print(f'Withdrawn: {burn_usd:.2f}$ ({burn0:.4f}, {burn1:.4f}) ({burn0_usd:.2f}$, {burn1_usd:.2f}$) ({burn0_price_usd:.2f}$ {burn1_price_usd:.2f}$)')
    print('Closed' if burn else 'Opened')

def main():
    user_addr = sys.argv[1]

    mints = list(get_all_position_mints(w3, user_addr))
    burns = list(get_all_position_burns(w3, user_addr))
    all_claims = list(get_all_claim_rewards(w3, user_addr))

    print(burns)
    print(mints)

    position_infos = list(map(
        lambda m: aerodrome.get_position_info_cached(w3, m.token_id, block=m.block_number),
        mints))

    claims_by_token_id = defaultdict(list)
    for claim in all_claims:
        claims_by_token_id[claim.token_id].append(claim)

    burns_by_id = {}
    for burn in burns:
        assert burn.token_id not in burns_by_id
        burns_by_id[burn.token_id] = burn

    for pos, mint in zip(position_infos, mints):
        # if burns_by_id.get(pos.nft_id, None) is not None:
        #     continue # skip closed for now
        print_position_info(w3, pos, claims_by_token_id[pos.nft_id], mint, burns_by_id.get(pos.nft_id, None))
        print()

if __name__ == "__main__":
    main()
