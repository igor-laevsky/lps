import rich

from connectors.base import create_base_web3
from lps.utils.config import load_configuration, logging_config, get_config
import sys
import logging.config

load_configuration(sys.argv[1])
logging.config.dictConfig(logging_config())

import signal
import time

from lps.aerodrome import get_position_info_cached, clear_caches
from lps.connectors import hl
from lps import hl_hedger, erc20

from eth_defi.event_reader.block_time import measure_block_time

from lps.connectors import binance

logger = logging.getLogger('main')

def main():
    w3 = create_base_web3()
    a_hl = hl.start()
    #a_binance = binance.start()

    block_time_sec = measure_block_time(w3)
    logger.info(f'Measured block time {block_time_sec}s')

    # Graceful shutdown
    is_running = True
    def stop(_, __):
        nonlocal is_running
        is_running = False
        logger.info('Received signal, exiting')
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    # Load position info
    tracked_position_ids = (4516228,)
    tracked_positions = []
    for pos in tracked_position_ids:
        pos = get_position_info_cached(w3, pos)
        tracked_positions.append(pos)
        rich.print(pos)

    while is_running:
        # block = w3.eth.get_block('latest')
        # logger.info(f'Current block: {block["number"]} '
        #             f'delay {time.time() - block["timestamp"]:.2f}s')
        block_number = w3.eth.get_block_number()

        try:
            ticks = list(
                map(lambda pos: pos.pool.get_slot0(w3, block=block_number).tick,
                    tracked_positions))

            hedges = hl_hedger.compute_hedges(zip(tracked_positions, ticks, strict=True))
            adjustments = hl_hedger.compute_hedge_adjustments(a_hl, hedges)
            updated_cnt = hl_hedger.execute_hedge_adjustements(a_hl, adjustments)

            if len(adjustments) > 0:
                logger.info(f"{block_number} {ticks} {dict(hedges)} {dict(adjustments)} {updated_cnt}")
        except Exception:
            logger.exception('Failed somewhere')
            logger.warning('Re-creating all connections in 10 seconds')

            # Assume that one of the connections is malfunctioning
            # It will probably take some time until it recovers
            while is_running:
                try:
                    time.sleep(10)
                    w3 = create_base_web3()
                    a_hl = hl.start()
                    break
                except Exception:
                    logger.exception("Failed while re-creating connections")
                    logger.warning("Retrying in 10 seconds")
                    continue

        # CEX->DEX price diff
        # ticks = []
        # for pos in tracked_positions:
        #     slot0 = pos.pool.get_slot0(w3, block=block['number'])
        #     ticks.append(slot0.tick)
        #
        #     pool_price = pos.pool.human_price(slot0.sqrtPriceX96)
        #     logger.info(f'Pool price is {pool_price:.2f}')
        #     binance_price = binance.mid_price(
        #         a_binance,
        #         erc20.canonic_symbol(pos.base.symbol),
        #         erc20.canonic_symbol(pos.quote.symbol))
        #     diff = abs(pool_price - binance_price) / pool_price * 100
        #     logger.info(f'Binance mid price: {binance_price:.2f} diff vs dex {diff:.4f}%')
        #     if diff > pos.pool.fee_pips / 10000:
        #         logger.warning('CEX<->DEX price arbitrage possibility')

        time.sleep(block_time_sec)

    # aero_nft_manager = get_deployed_contract(
    #     w3,
    #     resources_path() / "abis" / "aerodrome_nft_manager.json",
    #     address=conf.aerodrome.nft_position_manager
    # )

    # position_info = NftPositionInfo(*aero_nft_manager.functions.positions(3899989).call())
    # # 3796958
    # rich.print(position_info)
    #
    # cl_factory = get_deployed_contract(
    #     w3,
    #     resources_path() / "abis" / "aerodrome_cl_factory.json",
    #     address=conf.aerodrome.cl_factory
    # )
    # pool_addr = cl_factory.functions.getPool(position_info.token0, position_info.token1, position_info.tickSpacing).call()
    # print(pool_addr)
    #
    # cl_pool = get_deployed_contract(
    #     w3,
    #     resources_path() / "abis" / "aerodrome_cl_pool.json",
    #     pool_addr
    # )
    # slot0 = CLPoolSlot0(*cl_pool.functions.slot0().call())
    # print(slot0)
    #
    # token0_details = fetch_erc20_details(w3, position_info.token0)
    # token1_details = fetch_erc20_details(w3, position_info.token1)
    # print('Token0: ', token0_details)
    # print('Token1: ', token1_details)
    # print('Current price: ', ((slot0.sqrtPriceX96 / 0x1000000000000000000000000) ** 2) / 10**(token1_details.decimals - token0_details.decimals))

    # aero_sugar = get_deployed_contract(
    #     w3,
    #     resources_path() / "abis" / "aerodrome_sugar.json",
    #     conf.aerodrome.sugar)

    # print(w3.eth.get_block_number())
    # fetch_deployment()
    # swap_with_slippage_protection()

    # print(aero_sugar.functions.positions(100, 0, Web3.to_checksum_address('0x84fcd2463483e8f8dc4190c65679592f2358c314')).call())
    # print(aero_sugar.functions.positions(100, 0, Web3.to_checksum_address('0x83106205dD989fd5cd953dAb514158B1E04ca557')).call())
    # positions = aero_sugar.functions.positionsByFactory(10000, 00,
    #                                               Web3.to_checksum_address('0xf33a96b5932d9e9b9a0eda447abd8c9d48d2e0c8'),
    #                                               '0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A').call()
    # print(len(positions))

    #print(aero_sugar.functions.all(_limit=10, _offset=0).call())

if __name__ == "__main__":
    main()
