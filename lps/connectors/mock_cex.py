from collections import defaultdict

import attrs

from lps.connectors.abs import AssetPosition, ConnectorException
from decimal import Decimal

class MockConnectorError(ConnectorException):
    pass

@attrs.define
class MockCEX:
    usd_balance: Decimal
    position_sizes: defaultdict[str, Decimal] = attrs.field(factory=lambda: defaultdict(Decimal))
    mids: dict[str, Decimal] = attrs.field(factory=dict)

    def get_mid_prices(self, *names: str) -> dict[str, Decimal]:
        return {name: self.mids[name] for name in names}

    def set_mid_prices(self, new_mids: dict[str, Decimal]):
        self.mids = new_mids.copy()

    def get_user_positions(self) -> dict[str, AssetPosition]:
        return {
            name: AssetPosition(
                positionValue=size * self.mids[name],
                szi=size
            ) for name, size in self.position_sizes.items() if size != 0
        }

    def get_total_balance(self):
        """Returns total usd balance if all positions will be closed now"""
        total_pos = sum(
            [self.mids[name] * size
             for name, size in self.position_sizes.items()])
        return total_pos + self.usd_balance

    def market_order(self, name: str, size: Decimal):
        is_buy = True if size > 0 else False

        current_price = self.mids[name]
        rounded_size = abs(round(size, 4))

        order_value = rounded_size * current_price

        if is_buy:
            if self.usd_balance < order_value:
                raise MockConnectorError(f'Insufficient balance for buy order {name} {size} {current_price} {self.usd_balance}')

            self.usd_balance -= order_value
            self.position_sizes[name] += rounded_size
        else:
            self.usd_balance += order_value
            self.position_sizes[name] -= rounded_size

    def close_all_positions(self):
        for name, size in self.position_sizes.items():
            self.market_order(name, 0 - size)

def start(initial_usd: int):
    return MockCEX(Decimal(initial_usd))
