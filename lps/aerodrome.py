import logging
from functools import lru_cache

import attrs
from eth_defi.token import TokenDetails
from web3 import Web3
from web3.contract import Contract
from web3.types import BlockIdentifier

from lps.contracts import create_contract_cached
from lps.erc20 import fetch_erc20_details_cached, guess_is_stable_coin
from lps.utils import v3_math
from lps.utils.config import resources_path, get_config

from decimal import Decimal

logger = logging.getLogger('aero')

@attrs.frozen
class CLPoolInfo:
    token0: TokenDetails
    token1: TokenDetails
    tick_spacing: int
    fee_pips: int
    contract: Contract

    @attrs.frozen
    class Slot0:
        """ Raw data from the pool slot0 """
        sqrtPriceX96: int
        tick: int
        observationIndex: int
        observationCardinality: int
        observationCardinalityNext: int
        unlocked: bool

    def get_slot0(self, _: Web3, block: BlockIdentifier = 'latest') -> Slot0:
        return self.Slot0(
            *self.contract.functions.slot0().call(block_identifier=block))

    def _is_price_inverted(self) -> bool:
        if guess_is_stable_coin(self.token1):
            return False
        if guess_is_stable_coin(self.token0):
            return True
        return False # Don't know really

    def match_base_quote(self, token0: any, token1: any) -> (any, any):
        """Reorders elements according to the base-quote guess"""
        if self._is_price_inverted():
            return token1, token0
        return token0, token1

    @property
    def base(self) -> TokenDetails:
        return self.match_base_quote(self.token0, self.token1)[0]

    @property
    def quote(self) -> TokenDetails:
        return self.match_base_quote(self.token0, self.token1)[1]

    def human_price(self, sqrtPriceX96: int) -> Decimal:
        p = v3_math.sqrtprice_to_human(
            sqrtPriceX96,
            self.token0.decimals,
            self.token1.decimals)
        if self._is_price_inverted():
            return 1 / p
        return p

@attrs.frozen
class PositionInfo:
    """Internal representation of the position, collected from multiple contracts"""
    tick_lower: int
    tick_upper: int
    liquidity: int

    nft_id: int
    pool: CLPoolInfo

    def match_base_quote(self, token0: any, token1: any) -> (any, any):
        """Reorders elements according to the base-quote guess"""
        return self.pool.match_base_quote(token0, token1)

    @property
    def token0(self):
        return self.pool.token0

    @property
    def token1(self):
        return self.pool.token1

    @property
    def base(self) -> TokenDetails:
        return self.pool.base

    @property
    def quote(self) -> TokenDetails:
        return self.pool.quote

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

@lru_cache(maxsize=256)
def _get_pool_info_cached(
        w3: Web3,
        token0: TokenDetails,
        token1: TokenDetails,
        tickSpacing: int) -> CLPoolInfo:

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

@lru_cache(maxsize=256)
def get_position_info_cached(
        w3: Web3, nft_id: int, block: BlockIdentifier = "latest") -> PositionInfo:

    aero_nft_manager = create_contract_cached(
        w3,
        address=get_config().aerodrome.nft_position_manager,
        abi_fname="aerodrome_nft_manager.json",
    )

    position_info = _RawNftPositionInfo(
        *aero_nft_manager.functions.positions(nft_id).call(block_identifier=block))

    token0_details = fetch_erc20_details_cached(w3, position_info.token0)
    token1_details = fetch_erc20_details_cached(w3, position_info.token1)

    pool = _get_pool_info_cached(
        w3,
        token0_details,
        token1_details,
        position_info.tickSpacing)

    return PositionInfo(
        tick_lower=position_info.tickLower,
        tick_upper=position_info.tickUpper,
        liquidity=position_info.liquidity,
        nft_id=nft_id,
        pool=pool,
    )

def all_user_positions(addr: str) -> list[PositionInfo]:
    """ Note: only accounts for the staked positions """
    # Needs indexing or can use alchemy_getAssetTransfers to see al nft transfers
    # Or query all gauges on-by-one. Easier to write nft id's by hand for now.
    raise Exception("Not implemented")

def clear_caches():
    get_position_info_cached.cache_clear()
    _get_pool_info_cached.cache_clear()
