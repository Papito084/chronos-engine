"""
ChronosEngine - Doubly-Linked List Price Level Implementation.
Provides strictly O(1) insertion, O(1) cancellation, and deterministic FIFO traversal.
"""

from typing import Optional, Iterator
from core.models.order import Order
from core.models.types import from_fixed_point, fixed_to_str


class PriceLevel:
    __slots__ = ("price", "head", "tail", "total_volume", "order_count")

    def __init__(self, price: int) -> None:
        self.price: int = price
        self.head: Optional[Order] = None
        self.tail: Optional[Order] = None
        self.total_volume: int = 0
        self.order_count: int = 0

    def append(self, order: Order) -> None:
        """Appends an order to the tail of the level (Price-Time Priority FIFO) in O(1)."""
        order.parent_level = self
        order.prev = self.tail
        order.next = None

        if self.tail is not None:
            self.tail.next = order
        else:
            self.head = order

        self.tail = order
        self.total_volume += order.remaining_quantity
        self.order_count += 1

    def remove(self, order: Order) -> None:
        """Removes an order from anywhere in the level in O(1)."""
        if order.parent_level is not self:
            raise ValueError("Order does not belong to this PriceLevel")

        if order.prev is not None:
            order.prev.next = order.next
        else:
            self.head = order.next

        if order.next is not None:
            order.next.prev = order.prev
        else:
            self.tail = order.prev

        self.total_volume -= order.remaining_quantity
        self.order_count -= 1

        order.prev = None
        order.next = None
        order.parent_level = None

    def reduce_volume(self, quantity: int) -> None:
        """Adjusts cached aggregate volume when an order at this level is partially filled."""
        self.total_volume -= quantity

    def peek(self) -> Optional[Order]:
        """Returns the oldest (FIFO head) order at this price level without removing it."""
        return self.head

    def is_empty(self) -> bool:
        return self.order_count == 0

    def __iter__(self) -> Iterator[Order]:
        curr = self.head
        while curr is not None:
            yield curr
            curr = curr.next

    def to_dict(self) -> dict:
        return {
            "price": self.price,
            "price_str": fixed_to_str(self.price),
            "price_float": from_fixed_point(self.price),
            "total_volume": self.total_volume,
            "total_volume_str": fixed_to_str(self.total_volume),
            "total_volume_float": from_fixed_point(self.total_volume),
            "order_count": self.order_count,
        }

    def __repr__(self) -> str:
        return f"PriceLevel(px={fixed_to_str(self.price)}, count={self.order_count}, vol={fixed_to_str(self.total_volume)})"
