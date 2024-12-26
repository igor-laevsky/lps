from abc import ABC
from decimal import Decimal
from typing import Protocol

import attrs

class ConnectorException(Exception):
    pass

@attrs.frozen
class AssetPosition:
    positionValue: Decimal
    szi: Decimal

class CanDoOrders(Protocol):
    def market_order(self, name: str, size: Decimal):
        ...

class HasAssetPositions(Protocol):
    def get_mid_prices(self, *names: str) -> dict[str, Decimal]:
        ...

    def get_user_positions(self) -> dict[str, AssetPosition]:
        ...


def adjust_position(
        orderer: CanDoOrders, name: str, from_size: Decimal, to_size: Decimal):
    """
    Note: from_size should be equal to the current position size
    """
    diff = to_size - from_size
    if diff == 0:
        return
    orderer.market_order(name, diff) # exception on failure
