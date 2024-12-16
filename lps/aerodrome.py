import logging
from functools import lru_cache

import attrs
from eth_defi.token import TokenDetails
from web3 import Web3
from web3.contract import Contract

from lps.contracts import create_contract_cached
from lps.erc20 import fetch_erc20_details_cached, guess_is_stable_coin
from lps.utils.config import resources_path, get_config

logger = logging.getLogger('aero')

@attrs.frozen
class CLPoolInfo:
    token0: TokenDetails
    token1: TokenDetails
    tick_spacing: int
    fee_pips: int
    contract: Contract

@attrs.frozen
class PositionInfo:
    """Internal representation of the position, collected from multiple contracts"""

    # We try to resolve quote to stable coin and base to volatile when possible
    base: TokenDetails
    quote: TokenDetails

    tick_lower: int
    tick_upper: int

    pool: CLPoolInfo
    nft_manager: Contract

@attrs.frozen
class _RawNftPositionInfo:
    """This is raw data returned from nft position manager"""
    nonce: int
    operator: str
    token0: str
    token1: str
    tickSpacing: int
    tickLower: int
    tickUpper: int
    liquidity: int
    feeGrowthInside0LastX128: int
    feeGrowthInside1LastX128: int
    tokensOwed0: int
    tokensOwed1: int

@attrs.frozen
class _CLPoolSlot0:
    """Raw data from the pool slot"""
    sqrtPriceX96: int
    tick: int
    observationIndex: int
    observationCardinality: int
    observationCardinalityNext: int
    unlocked: bool

@lru_cache(maxsize=256)
def _get_pool_info_cached(w3: Web3, token0: TokenDetails, token1: TokenDetails, tickSpacing: int) -> CLPoolInfo:
    cl_factory = create_contract_cached(
        w3,
        address=get_config().aerodrome.cl_factory,
        abi_fname="aerodrome_cl_factory.json"
    )
    pool_addr = cl_factory.functions.getPool(
        token0.contract.address, token1.contract.address, tickSpacing).call()
    pool_contract = create_contract_cached(
        w3,
        address=pool_addr,
        abi_fname="aerodrome_cl_pool.json"
    )

    pool_fee = pool_contract.functions.fee().call()

    return CLPoolInfo(
        token0=token0,
        token1=token1,
        tick_spacing=tickSpacing,
        fee_pips=pool_fee,
        contract=pool_contract
    )

def get_position_info(w3: Web3, nft_id: int) -> PositionInfo:
    aero_nft_manager = create_contract_cached(
        w3,
        address=get_config().aerodrome.nft_position_manager,
        abi_fname="aerodrome_nft_manager.json",
    )

    position_info = _RawNftPositionInfo(
        *aero_nft_manager.functions.positions(nft_id).call())

    token0_details = fetch_erc20_details_cached(w3, position_info.token0)
    token1_details = fetch_erc20_details_cached(w3, position_info.token1)

    # Guess human-readable token order
    base = token0_details
    quote = token1_details
    if guess_is_stable_coin(token0_details):
        base = token1_details
        quote = token0_details

    pool = _get_pool_info_cached(
        w3,
        token0_details,
        token1_details,
        position_info.tickSpacing)

    return PositionInfo(
        base=base,
        quote=quote,
        tick_lower=position_info.tickLower,
        tick_upper=position_info.tickUpper,
        pool=pool,
        nft_manager=aero_nft_manager
    )
