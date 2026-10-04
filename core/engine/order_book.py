"""
ChronosEngine - Deterministic L3 Order Book.
Combines SortedDict (B-Tree behavior for price levels) with PriceLevel Doubly-Linked Lists for O(1) FIFO operations.
"""

from typing import Optional, Dict, List, Tuple, Any
from sortedcontainers import SortedDict

from core.models.types import Side, OrderType, TimeInForce, OrderStatus
from core.models.order import Order
from core.models.price_level import PriceLevel


class OrderBook:
    __slots__ = ("symbol", "bids", "asks", "orders")

    def __init__(self, symbol: str) -> None:
        self.symbol: str = symbol
        # Bids: descending order by price (highest price first).
        # We negate the key so SortedDict orders from highest bid to lowest.
        self.bids: SortedDict = SortedDict(lambda p: -p)
        # Asks: ascending order by price (lowest price first).
        self.asks: SortedDict = SortedDict(lambda p: p)
        # Fast index for O(1) order lookup by order_id
        self.orders: Dict[str, Order] = {}

    @property
    def best_bid(self) -> Optional[int]:
        """Returns the highest bid price in the book, or None if no bids exist."""
        if not self.bids:
            return None
        # In SortedDict, keys()[0] is the top of the sorted tree
        return self.bids.keys()[0]

    @property
    def best_ask(self) -> Optional[int]:
        """Returns the lowest ask price in the book, or None if no asks exist."""
        if not self.asks:
            return None
        return self.asks.keys()[0]

    @property
    def spread(self) -> Optional[int]:
        """Calculates current bid-ask spread in fixed-point, or None if one side is empty."""
        bb = self.best_bid
        ba = self.best_ask
        if bb is not None and ba is not None:
            return ba - bb
        return None

    @property
    def mid_price(self) -> Optional[int]:
        """Calculates mid price in fixed-point, or None if one side is empty."""
        bb = self.best_bid
        ba = self.best_ask
        if bb is not None and ba is not None:
            return (bb + ba) // 2
        return None

    def add_order(self, order: Order) -> PriceLevel:
        """
        Inserts a resting order into the book in O(1) at its price level,
        or O(log N) if a new price level must be created.
        """
        price = order.price
        tree = self.bids if order.side == Side.BUY else self.asks

        level = tree.get(price)
        if level is None:
            level = PriceLevel(price)
            tree[price] = level

        level.append(order)
        self.orders[order.order_id] = order
        return level

    def remove_order(self, order_id: str) -> Optional[Order]:
        """
        Removes an order from its PriceLevel and the book index in strictly O(1) time.
        Does not mutate order status. Used when orders are filled or removed.
        """
        order = self.orders.get(order_id)
        if order is None:
            return None

        level = order.parent_level
        if level is not None:
            level.remove(order)
            if level.is_empty():
                tree = self.bids if order.side == Side.BUY else self.asks
                if order.price in tree:
                    del tree[order.price]

        del self.orders[order_id]
        return order

    def cancel_order(self, order_id: str) -> Optional[Order]:
        """
        Cancels and removes an active order from the book in strictly O(1) time.
        """
        order = self.orders.get(order_id)
        if order is None or not order.is_active:
            return None

        self.remove_order(order_id)
        order.status = OrderStatus.CANCELED
        return order

    def get_order(self, order_id: str) -> Optional[Order]:
        """Returns order by id if present in the book."""
        return self.orders.get(order_id)

    def check_fok_fillable(
        self,
        side: Side,
        quantity: int,
        limit_price: Optional[int] = None,
    ) -> bool:
        """
        Simulates whether an incoming FOK (Fill-Or-Kill) order can be 100% filled
        against the resting book without mutating the book state.
        """
        tree = self.asks if side == Side.BUY else self.bids
        remaining_to_fill = quantity

        for price, level in tree.items():
            if limit_price is not None:
                if side == Side.BUY and price > limit_price:
                    break
                if side == Side.SELL and price < limit_price:
                    break

            if level.total_volume >= remaining_to_fill:
                return True
            remaining_to_fill -= level.total_volume

        return False

    def get_l2_snapshot(self, depth: int = 50) -> Dict[str, List[Tuple[int, int, int]]]:
        """
        Returns L2 order book representation:
        bids: list of (price, total_volume, order_count)
        asks: list of (price, total_volume, order_count)
        """
        bids_l2 = []
        for i, (price, level) in enumerate(self.bids.items()):
            if i >= depth:
                break
            bids_l2.append((price, level.total_volume, level.order_count))

        asks_l2 = []
        for i, (price, level) in enumerate(self.asks.items()):
            if i >= depth:
                break
            asks_l2.append((price, level.total_volume, level.order_count))

        return {
            "symbol": self.symbol,
            "bids": bids_l2,
            "asks": asks_l2,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "spread": self.spread,
        }

    def get_l3_snapshot(self, depth_levels: int = 10) -> Dict[str, Any]:
        """
        Returns full L3 order book representation with individual order queues.
        """
        bids_l3 = []
        for i, (price, level) in enumerate(self.bids.items()):
            if i >= depth_levels:
                break
            level_orders = [o.to_dict() for o in level]
            bids_l3.append({
                "price": price,
                "volume": level.total_volume,
                "orders": level_orders,
            })

        asks_l3 = []
        for i, (price, level) in enumerate(self.asks.items()):
            if i >= depth_levels:
                break
            level_orders = [o.to_dict() for o in level]
            asks_l3.append({
                "price": price,
                "volume": level.total_volume,
                "orders": level_orders,
            })

        return {
            "symbol": self.symbol,
            "bids": bids_l3,
            "asks": asks_l3,
        }

    def clear(self) -> None:
        """Resets the entire order book."""
        self.bids.clear()
        self.asks.clear()
        self.orders.clear()
