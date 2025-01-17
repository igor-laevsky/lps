import rich
from web3 import Web3
from decimal import Decimal

from connectors import mock_cex
from lps import erc20, hedger
from lps.aerodrome import PositionInfo, CLPoolInfo
from lps.connectors import hl
from lps.connectors.hl import HL
from lps.contracts import create_contract_cached
from lps.utils.config import get_config


def test_hedge_with_mock_cex(base_w3: Web3):
    conn = mock_cex.start(2000)
    conn.set_mid_prices({'ETH': Decimal(3500)})

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

    def do(tick):
        hedges = hedger.compute_hedges([(pos, tick)])
        updates = hedger.compute_hedge_adjustments(conn, hedges)
        updated_cnt = hedger.execute_hedge_adjustements(conn, updates)
        return updated_cnt

    # Start in the middle
    do(-193400)
    assert conn.get_user_positions()['ETH'].szi == Decimal('-0.112')

    # Outside lower bound
    cnt = do(-194500)
    assert conn.get_user_positions()['ETH'].szi == Decimal('-0.2287')
    assert cnt == 1

    assert conn.usd_balance == Decimal('2800.4500')

    # Still outside
    cnt = do(-194300)
    assert cnt == 0

    # On the lower edge
    cnt = do(-194200)
    assert cnt == 0

    # In the middle
    cnt = do(-193400)
    assert conn.get_user_positions()['ETH'].szi == Decimal('-0.112')
    assert cnt == 1

    # Small change (no update)
    cnt = do(-193410)
    assert conn.get_user_positions()['ETH'].szi == Decimal('-0.112')
    assert cnt == 0

    # Larger change update (success depends on USD price of ETH lol)
    cnt = do(-193650)
    assert cnt == 1

    # Close to the upper edge
    cnt = do(-192700)
    assert conn.get_user_positions()['ETH'].szi == Decimal('-0.0138')
    assert cnt == 1

    # On the upper edge
    cnt = do(-192600)
    assert 'ETH' not in conn.get_user_positions()
    assert cnt == 1

    # Upper overflow
    cnt = do(-192600)
    assert cnt == 0

    assert conn.usd_balance == Decimal('2000')


def test_hedge_single_pos_not_inverse(base_w3: Web3, hl_connector: HL):
    # TODO: this is not very stable, probably remove - mock hedger obove tests is the same

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

    def do(tick):
        hedges = hedger.compute_hedges([(pos, tick)])
        updates = hedger.compute_hedge_adjustments(hl_connector, hedges)
        updated_cnt = hedger.execute_hedge_adjustements(hl_connector, updates)
        return updated_cnt

    # Start in the middle
    do(-193400)
    assert hl_connector.get_user_positions()['ETH'].szi == Decimal('-0.112')

    # Outside lower bound
    cnt = do(-194500)
    assert hl_connector.get_user_positions()['ETH'].szi == Decimal('-0.2287')
    assert cnt == 1

    # Still outside
    cnt = do(-194300)
    assert cnt == 0

    # On the lower edge
    cnt = do(-194200)
    assert cnt == 0

    # In the middle
    cnt = do(-193400)
    assert hl_connector.get_user_positions()['ETH'].szi == Decimal('-0.112')
    assert cnt == 1

    # Small change (no update)
    cnt = do(-193410)
    assert hl_connector.get_user_positions()['ETH'].szi == Decimal('-0.112')
    assert cnt == 0

    # Larger change update (success depends on USD price of ETH lol)
    cnt = do(-193650)
    assert cnt == 1

    # Close to the upper edge
    cnt = do(-192700)
    assert hl_connector.get_user_positions()['ETH'].szi == Decimal('-0.0138')
    assert cnt == 1

    # On the upper edge
    cnt = do(-192600)
    assert 'ETH' not in hl_connector.get_user_positions()
    assert cnt == 1

    # Upper overflow
    cnt = do(-192600)
    assert cnt == 0

def test_hedge_single_pos_two_volatiles(base_w3: Web3, hl_connector: HL):
    # This doesn't work very good because there is no liquidity on the test net
    # Need to mock HL in order to properly test
    # VIRTUAL/WETH
    pos = PositionInfo(
        tick_lower=-73400,
        tick_upper=-72800,
        liquidity=596712693584385284352,
        nft_id=3899989,
        pool=CLPoolInfo(
            token0=erc20.fetch_erc20_details_cached(base_w3, '0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b'),
            token1=erc20.fetch_erc20_details_cached(base_w3, '0x4200000000000000000000000000000000000006'),
            tick_spacing=200,
            fee_pips=2700,
            contract=create_contract_cached(
                base_w3,
                address=str('0xc200f21efe67c7f41b81a854c26f9cda80593065'),
                abi_fname="aerodrome_cl_pool.json",
            )
        ),
    )

    # TODO: this is no good, but I'm too lazy to mock HL
    def do(tick):
        hedges = hedger.compute_hedges([(pos, tick)])
        rich.print(hedges)
        updates = hedger.compute_hedge_adjustments(hl_connector, hedges)
        rich.print(updates)

        updated_cnt = hedger.execute_hedge_adjustements(hl_connector, updates)
        return updated_cnt

    # In the middle
    print('middle')
    cnt = do(-73100)
    #assert hl.get_user_positions(hl_connector).get('ETH', {'szi': '0'})['szi'] == '-0.2298'
    #assert hl.get_user_positions(hl_connector).get('VIRTUAL', {'szi': '0'})['szi'] == '-343.4'
    #assert cnt == 2

    # Lower overflow
    print('lower')
    cnt = do(-73400)
    # assert cnt == 2
    # assert hl.get_user_positions(hl_connector).get('ETH', {'szi': '0'})['szi'] == '0'
    # assert hl.get_user_positions(hl_connector).get('VIRTUAL', {'szi': '0'})['szi'] == '-343.4'

    # Upper overflow
    print('upper')
    cnt = do(-72800)
    # assert cnt == 2
    # assert hl.get_user_positions(hl_connector).get('ETH', {'szi': '0'})['szi'] == '0'
    # assert hl.get_user_positions(hl_connector).get('VIRTUAL', {'szi': '0'})['szi'] == '--692.1'

def test_hedge_multi_pos_many_volatiles(base_w3: Web3, hl_connector: HL):
    pass # TODO
