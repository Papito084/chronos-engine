"""
ChronosEngine - High Performance Order Model.
Uses slots and intrusive doubly-linked list pointers for zero-allocation O(1) book manipulation.
"""

from typing import Optional, TYPE_CHECKING
from core.models.types import (
    Side,
    OrderType,
    TimeInForce,
    OrderStatus,
    from_fixed_point,
    fixed_to_str,
)

if TYPE_CHECKING:
    from core.models.price_level import PriceLevel


class Order:
    __slots__ = (
        "order_id",
        "symbol",
        "side",
        "order_type",
        "price",
        "initial_quantity",
        "remaining_quantity",
        "filled_quantity",
        "time_in_force",
        "status",
        "timestamp_ns",
        "sequence_number",
        "prev",
        "next",
        "parent_level",
    )

    def __init__(
        self,
        order_id: str,
        symbol: str,
        side: Side,
        order_type: OrderType,
        price: int,
        quantity: int,
        time_in_force: TimeInForce = TimeInForce.GTC,
        timestamp_ns: int = 0,
        sequence_number: int = 0,
    ) -> None:
        self.order_id: str = order_id
        self.symbol: str = symbol
        self.side: Side = side
        self.order_type: OrderType = order_type
        self.price: int = price
        self.initial_quantity: int = quantity
        self.remaining_quantity: int = quantity
        self.filled_quantity: int = 0
        self.time_in_force: TimeInForce = time_in_force
        self.status: OrderStatus = OrderStatus.NEW
        self.timestamp_ns: int = timestamp_ns
        self.sequence_number: int = sequence_number

        # Intrusive Doubly-Linked List pointers
        self.prev: Optional["Order"] = None
        self.next: Optional["Order"] = None
        self.parent_level: Optional["PriceLevel"] = None

    @property
    def is_filled(self) -> bool:
        return self.remaining_quantity == 0

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED)

    def fill(self, fill_qty: int) -> None:
        """Executes a partial or full fill against this order."""
        if fill_qty > self.remaining_quantity:
            raise ValueError(f"Fill quantity {fill_qty} exceeds remaining quantity {self.remaining_quantity}")
        self.remaining_quantity -= fill_qty
        self.filled_quantity += fill_qty
        if self.remaining_quantity == 0:
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIALLY_FILLED

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "price": self.price,
            "price_str": fixed_to_str(self.price),
            "price_float": from_fixed_point(self.price),
            "initial_quantity": self.initial_quantity,
            "initial_quantity_str": fixed_to_str(self.initial_quantity),
            "initial_quantity_float": from_fixed_point(self.initial_quantity),
            "remaining_quantity": self.remaining_quantity,
            "remaining_quantity_str": fixed_to_str(self.remaining_quantity),
            "remaining_quantity_float": from_fixed_point(self.remaining_quantity),
            "filled_quantity": self.filled_quantity,
            "filled_quantity_str": fixed_to_str(self.filled_quantity),
            "filled_quantity_float": from_fixed_point(self.filled_quantity),
            "time_in_force": self.time_in_force.value,
            "status": self.status.value,
            "timestamp_ns": self.timestamp_ns,
            "sequence_number": self.sequence_number,
        }

    def __repr__(self) -> str:
        return (
            f"Order(id={self.order_id}, side={self.side.value}, type={self.order_type.value}, "
            f"px={fixed_to_str(self.price)}, rem_qty={fixed_to_str(self.remaining_quantity)}, "
            f"status={self.status.value})"
        )
