from web3 import Web3
from decimal import Decimal

from lps import erc20, hl_hedger
from lps.aerodrome import PositionInfo, CLPoolInfo
from lps.connectors import hl
from lps.connectors.hl import HL
from lps.contracts import create_contract_cached
from lps.utils.config import get_config


def test_hedge_single_pos_not_inverse(base_w3: Web3, hl_connector: HL):
    pos = PositionInfo(
        tick_lower=-194200,
        tick_upper=-192600,
        liquidity=180540158377974,
        nft_id=3899989,
        pool=CLPoolInfo(
            token0=erc20.fetch_erc20_details_cached(base_w3, '0x4200000000000000000000000000000000000006'),
            token1=erc20.fetch_erc20_details_cached(base_w3, '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'),
            tick_spacing=100,
            fee_pips=400,
            contract=create_contract_cached(
                base_w3,
                address=str('0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59'),
                abi_fname="aerodrome_cl_pool.json",
            )
        ),
    )

    # TODO: this is no good, but I'm too lazy to mock HL
    def do(tick):
        hedges = hl_hedger.compute_hedges([(pos, tick)])
        updates = hl_hedger.compute_hedge_adjustements(hl_connector, hedges)
        hl_hedger.execute_hedge_adjustements(hl_connector, updates)
        return len(updates)

    # Start in the middle
    do(-193400)
    assert hl.get_user_positions(hl_connector)['ETH']['szi'] == '-0.112'

    # Outside lower bound
    cnt = do(-194500)
    assert hl.get_user_positions(hl_connector)['ETH']['szi'] == '-0.2287'
    assert cnt == 1

    # Still outside
    cnt = do(-194300)
    assert cnt == 0

    # On the lower edge
    cnt = do(-194200)
    assert cnt == 0

    # In the middle
    cnt = do(-193400)
    assert hl.get_user_positions(hl_connector)['ETH']['szi'] == '-0.112'
    assert cnt == 1

    # Small change (no update)
    cnt = do(-193410)
    assert hl.get_user_positions(hl_connector)['ETH']['szi'] == '-0.112'
    assert cnt == 0

    # Larger change update
    cnt = do(-193500)
    assert hl.get_user_positions(hl_connector)['ETH']['szi'] == '-0.1264'
    assert cnt == 1

    # Close to the upper edge
    cnt = do(-192700)
    assert hl.get_user_positions(hl_connector)['ETH']['szi'] == '-0.0138'
    assert cnt == 1

    # On the upper edge
    cnt = do(-192600)
    assert hl.get_user_positions(hl_connector).get('ETH', {'szi': '0'})['szi'] == '0'
    assert cnt == 1

    # Upper overflow
    cnt = do(-192600)
    assert cnt == 0
