"""
Unit tests for deterministic L3 Order Book data structures.
Verifies O(1) PriceLevel operations, FIFO queues, B-Tree ordering, and snapshots.
"""

import pytest
from core.models.types import Side, OrderType, TimeInForce, to_fixed_point
from core.models.order import Order
from core.models.price_level import PriceLevel
from core.engine.order_book import OrderBook


def test_price_level_fifo_and_cancellation():
    """Verifies that PriceLevel maintains exact FIFO order and O(1) removals from head, middle, tail."""
    px = to_fixed_point("100.00")
    level = PriceLevel(px)
    assert level.is_empty()

    o1 = Order("ord-1", "BTC-USDT", Side.BUY, OrderType.LIMIT, px, to_fixed_point("1.0"))
    o2 = Order("ord-2", "BTC-USDT", Side.BUY, OrderType.LIMIT, px, to_fixed_point("2.0"))
    o3 = Order("ord-3", "BTC-USDT", Side.BUY, OrderType.LIMIT, px, to_fixed_point("3.0"))

    level.append(o1)
    level.append(o2)
    level.append(o3)

    assert level.order_count == 3
    assert level.total_volume == to_fixed_point("6.0")

    # FIFO iteration
    orders = list(level)
    assert [o.order_id for o in orders] == ["ord-1", "ord-2", "ord-3"]

    # Remove middle order (o2) in O(1)
    level.remove(o2)
    assert level.order_count == 2
    assert level.total_volume == to_fixed_point("4.0")
    assert [o.order_id for o in level] == ["ord-1", "ord-3"]

    # Remove head order (o1) in O(1)
    level.remove(o1)
    assert level.order_count == 1
    assert level.total_volume == to_fixed_point("3.0")
    assert level.peek() is o3

    # Remove remaining tail order (o3)
    level.remove(o3)
    assert level.is_empty()
    assert level.order_count == 0
    assert level.total_volume == 0


def test_order_book_bbo_and_spread():
    """Verifies sorted price levels, best bid/ask, and spread calculations."""
    book = OrderBook("BTC-USDT")

    # Empty book
    assert book.best_bid is None
    assert book.best_ask is None
    assert book.spread is None

    bid1 = Order("b1", "BTC-USDT", Side.BUY, OrderType.LIMIT, to_fixed_point("50000.00"), to_fixed_point("1.0"))
    bid2 = Order("b2", "BTC-USDT", Side.BUY, OrderType.LIMIT, to_fixed_point("50010.00"), to_fixed_point("2.0"))
    ask1 = Order("a1", "BTC-USDT", Side.SELL, OrderType.LIMIT, to_fixed_point("50020.00"), to_fixed_point("1.5"))
    ask2 = Order("a2", "BTC-USDT", Side.SELL, OrderType.LIMIT, to_fixed_point("50030.00"), to_fixed_point("0.5"))

    book.add_order(bid1)
    book.add_order(bid2)
    book.add_order(ask1)
    book.add_order(ask2)

    # Best bid should be the highest bid: 50010
    assert book.best_bid == to_fixed_point("50010.00")
    # Best ask should be the lowest ask: 50020
    assert book.best_ask == to_fixed_point("50020.00")
    # Spread should be 50020 - 50010 = 10.00
    assert book.spread == to_fixed_point("10.00")
    # Mid price should be 50015.00
    assert book.mid_price == to_fixed_point("50015.00")


def test_order_book_cancellation_and_level_cleanup():
    """Verifies that removing orders cleans up empty levels from the SortedDict."""
    book = OrderBook("BTC-USDT")
    px = to_fixed_point("50000.00")
    o1 = Order("b1", "BTC-USDT", Side.BUY, OrderType.LIMIT, px, to_fixed_point("1.0"))
    book.add_order(o1)
    assert px in book.bids

    canceled = book.cancel_order("b1")
    assert canceled is not None
    assert canceled.order_id == "b1"
    assert px not in book.bids
    assert book.best_bid is None
    assert "b1" not in book.orders


def test_order_book_l2_and_l3_snapshots():
    """Verifies structure and fidelity of L2 aggregate and L3 granular snapshots."""
    book = OrderBook("BTC-USDT")
    px_bid = to_fixed_point("60000.00")
    px_ask = to_fixed_point("60005.00")

    book.add_order(Order("b1", "BTC-USDT", Side.BUY, OrderType.LIMIT, px_bid, to_fixed_point("1.0")))
    book.add_order(Order("b2", "BTC-USDT", Side.BUY, OrderType.LIMIT, px_bid, to_fixed_point("2.5")))
    book.add_order(Order("a1", "BTC-USDT", Side.SELL, OrderType.LIMIT, px_ask, to_fixed_point("4.0")))

    l2 = book.get_l2_snapshot(depth=5)
    assert len(l2["bids"]) == 1
    assert l2["bids"][0] == (px_bid, to_fixed_point("3.5"), 2)
    assert len(l2["asks"]) == 1
    assert l2["asks"][0] == (px_ask, to_fixed_point("4.0"), 1)

    l3 = book.get_l3_snapshot(depth_levels=5)
    assert len(l3["bids"][0]["orders"]) == 2
    assert l3["bids"][0]["orders"][0]["order_id"] == "b1"
    assert l3["bids"][0]["orders"][1]["order_id"] == "b2"
