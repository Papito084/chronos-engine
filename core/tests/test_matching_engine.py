"""
Unit tests for deterministic Matching Engine.
Verifies FIFO order, price priority, partial/full fills, market orders, TIF (GTC, IOC, FOK), and cancels.
"""

import pytest
from core.models.types import (
    Side,
    OrderType,
    TimeInForce,
    RejectReason,
    to_fixed_point,
    from_fixed_point,
)
from core.models.events import (
    NewOrderCommand,
    CancelOrderCommand,
    OrderAcceptedEvent,
    OrderRejectedEvent,
    OrderMatchedEvent,
    OrderFilledEvent,
    OrderCanceledEvent,
    BookLevelUpdatedEvent,
)
from core.engine.matching_engine import MatchingEngine


def test_passive_limit_order_rests_on_book():
    """A non-crossing limit order should be accepted and placed in the order book."""
    engine = MatchingEngine()
    cmd = NewOrderCommand(
        order_id="b1",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=to_fixed_point("50000.00"),
        quantity=to_fixed_point("1.5"),
        time_in_force=TimeInForce.GTC,
    )
    events = engine.process_command(cmd)

    assert len(events) == 2
    assert isinstance(events[0], OrderAcceptedEvent)
    assert isinstance(events[1], BookLevelUpdatedEvent)

    book = engine.get_or_create_book("BTC-USDT")
    assert book.best_bid == to_fixed_point("50000.00")
    assert book.orders["b1"].remaining_quantity == to_fixed_point("1.5")


def test_price_time_priority_fifo():
    """
    Two maker sell orders at the same price.
    An incoming buy order must match against the FIRST seller (FIFO time priority).
    """
    engine = MatchingEngine()
    px = to_fixed_point("50000.00")

    # Maker 1: Seller 1 arrives first
    engine.process_command(
        NewOrderCommand("s1", "BTC-USDT", Side.SELL, OrderType.LIMIT, px, to_fixed_point("1.0"))
    )
    # Maker 2: Seller 2 arrives second at identical price
    engine.process_command(
        NewOrderCommand("s2", "BTC-USDT", Side.SELL, OrderType.LIMIT, px, to_fixed_point("2.0"))
    )

    # Taker: Buyer takes 1.5 units
    taker_events = engine.process_command(
        NewOrderCommand("b1", "BTC-USDT", Side.BUY, OrderType.LIMIT, px, to_fixed_point("1.5"))
    )

    matched_events = [e for e in taker_events if isinstance(e, OrderMatchedEvent)]
    assert len(matched_events) == 2

    # First match must be against s1 for full 1.0
    assert matched_events[0].maker_order_id == "s1"
    assert matched_events[0].quantity == to_fixed_point("1.0")
    assert matched_events[0].maker_remaining_qty == 0

    # Second match must be against s2 for 0.5
    assert matched_events[1].maker_order_id == "s2"
    assert matched_events[1].quantity == to_fixed_point("0.5")
    assert matched_events[1].maker_remaining_qty == to_fixed_point("1.5")

    book = engine.get_or_create_book("BTC-USDT")
    assert "s1" not in book.orders
    assert book.orders["s2"].remaining_quantity == to_fixed_point("1.5")


def test_maker_sets_execution_price():
    """
    When an aggressive limit order crosses the spread, the match price
    must be the resting maker's price.
    """
    engine = MatchingEngine()
    # Maker sells at 50,000
    engine.process_command(
        NewOrderCommand("s1", "BTC-USDT", Side.SELL, OrderType.LIMIT, to_fixed_point("50000.00"), to_fixed_point("1.0"))
    )

    # Aggressive Buyer willing to pay up to 50,100
    events = engine.process_command(
        NewOrderCommand("b1", "BTC-USDT", Side.BUY, OrderType.LIMIT, to_fixed_point("50100.00"), to_fixed_point("1.0"))
    )

    match = [e for e in events if isinstance(e, OrderMatchedEvent)][0]
    # Trade must execute at 50,000 (resting maker's price), NOT 50,100!
    assert match.price == to_fixed_point("50000.00")
    assert match.quantity == to_fixed_point("1.0")


def test_multi_level_sweep():
    """An aggressive order sweeps through multiple resting price levels."""
    engine = MatchingEngine()
    # Three sell levels: 50010, 50020, 50030
    engine.process_command(
        NewOrderCommand("s1", "BTC-USDT", Side.SELL, OrderType.LIMIT, to_fixed_point("50010.00"), to_fixed_point("1.0"))
    )
    engine.process_command(
        NewOrderCommand("s2", "BTC-USDT", Side.SELL, OrderType.LIMIT, to_fixed_point("50020.00"), to_fixed_point("2.0"))
    )
    engine.process_command(
        NewOrderCommand("s3", "BTC-USDT", Side.SELL, OrderType.LIMIT, to_fixed_point("50030.00"), to_fixed_point("3.0"))
    )

    # Buyer sweeps up to 50025 for 2.5 units: fills all 1.0 of s1, and 1.5 of s2
    events = engine.process_command(
        NewOrderCommand("b1", "BTC-USDT", Side.BUY, OrderType.LIMIT, to_fixed_point("50025.00"), to_fixed_point("2.5"))
    )

    matches = [e for e in events if isinstance(e, OrderMatchedEvent)]
    assert len(matches) == 2
    assert matches[0].maker_order_id == "s1"
    assert matches[0].price == to_fixed_point("50010.00")
    assert matches[0].quantity == to_fixed_point("1.0")

    assert matches[1].maker_order_id == "s2"
    assert matches[1].price == to_fixed_point("50020.00")
    assert matches[1].quantity == to_fixed_point("1.5")

    book = engine.get_or_create_book("BTC-USDT")
    assert book.best_ask == to_fixed_point("50020.00")
    assert book.orders["s2"].remaining_quantity == to_fixed_point("0.5")
    assert book.orders["s3"].remaining_quantity == to_fixed_point("3.0")


def test_market_order_and_exhaustion():
    """Market order matches until book is exhausted, then cancels remainder."""
    engine = MatchingEngine()
    engine.process_command(
        NewOrderCommand("s1", "BTC-USDT", Side.SELL, OrderType.LIMIT, to_fixed_point("50000.00"), to_fixed_point("2.0"))
    )

    # Market buy for 5.0 (only 2.0 available)
    events = engine.process_command(
        NewOrderCommand("b_mkt", "BTC-USDT", Side.BUY, OrderType.MARKET, 0, to_fixed_point("5.0"))
    )

    matches = [e for e in events if isinstance(e, OrderMatchedEvent)]
    assert len(matches) == 1
    assert matches[0].quantity == to_fixed_point("2.0")

    cancels = [e for e in events if isinstance(e, OrderCanceledEvent)]
    assert len(cancels) == 1
    assert cancels[0].order_id == "b_mkt"
    assert cancels[0].remaining_quantity == to_fixed_point("3.0")

    book = engine.get_or_create_book("BTC-USDT")
    assert book.best_ask is None


def test_time_in_force_ioc():
    """IOC matches what it can immediately and cancels any remainder without resting."""
    engine = MatchingEngine()
    engine.process_command(
        NewOrderCommand("s1", "BTC-USDT", Side.SELL, OrderType.LIMIT, to_fixed_point("50000.00"), to_fixed_point("1.0"))
    )

    # Buy limit IOC for 3.0 at 50,000: fills 1.0, cancels 2.0
    events = engine.process_command(
        NewOrderCommand("b_ioc", "BTC-USDT", Side.BUY, OrderType.LIMIT, to_fixed_point("50000.00"), to_fixed_point("3.0"), TimeInForce.IOC)
    )

    matches = [e for e in events if isinstance(e, OrderMatchedEvent)]
    assert len(matches) == 1
    assert matches[0].quantity == to_fixed_point("1.0")

    cancels = [e for e in events if isinstance(e, OrderCanceledEvent)]
    assert len(cancels) == 1
    assert cancels[0].order_id == "b_ioc"
    assert cancels[0].remaining_quantity == to_fixed_point("2.0")

    book = engine.get_or_create_book("BTC-USDT")
    assert "b_ioc" not in book.orders


def test_time_in_force_fok():
    """
    FOK (Fill-Or-Kill):
    - Rejects with zero fills if entire quantity cannot be satisfied.
    - Fills completely if entire quantity is satisfied.
    """
    engine = MatchingEngine()
    engine.process_command(
        NewOrderCommand("s1", "BTC-USDT", Side.SELL, OrderType.LIMIT, to_fixed_point("50000.00"), to_fixed_point("2.0"))
    )

    # Case 1: Try to buy 3.0 with FOK (only 2.0 available) -> Must reject, 0 fills
    fok_fail_events = engine.process_command(
        NewOrderCommand("fok_1", "BTC-USDT", Side.BUY, OrderType.LIMIT, to_fixed_point("50000.00"), to_fixed_point("3.0"), TimeInForce.FOK)
    )
    rejects = [e for e in fok_fail_events if isinstance(e, OrderRejectedEvent)]
    assert len(rejects) == 1
    assert rejects[0].reason == RejectReason.FOK_CANNOT_BE_FILLED

    # Check maker s1 was untouched
    book = engine.get_or_create_book("BTC-USDT")
    assert book.orders["s1"].remaining_quantity == to_fixed_point("2.0")

    # Case 2: Try to buy 2.0 with FOK (exact match) -> Must succeed completely
    fok_success_events = engine.process_command(
        NewOrderCommand("fok_2", "BTC-USDT", Side.BUY, OrderType.LIMIT, to_fixed_point("50000.00"), to_fixed_point("2.0"), TimeInForce.FOK)
    )
    matches = [e for e in fok_success_events if isinstance(e, OrderMatchedEvent)]
    assert len(matches) == 1
    assert matches[0].quantity == to_fixed_point("2.0")
    assert "s1" not in book.orders


def test_order_cancellation():
    """Valid order cancellation removes order from book and updates level volume."""
    engine = MatchingEngine()
    engine.process_command(
        NewOrderCommand("b1", "BTC-USDT", Side.BUY, OrderType.LIMIT, to_fixed_point("50000.00"), to_fixed_point("10.0"))
    )

    cancel_events = engine.process_command(CancelOrderCommand("b1", "BTC-USDT"))
    cancels = [e for e in cancel_events if isinstance(e, OrderCanceledEvent)]
    assert len(cancels) == 1
    assert cancels[0].order_id == "b1"
    assert cancels[0].remaining_quantity == to_fixed_point("10.0")

    book = engine.get_or_create_book("BTC-USDT")
    assert book.best_bid is None
    assert "b1" not in book.orders

    # Canceling non-existent or already canceled order should reject
    reject_events = engine.process_command(CancelOrderCommand("b1", "BTC-USDT"))
    rejects = [e for e in reject_events if isinstance(e, OrderRejectedEvent)]
    assert len(rejects) == 1
    assert rejects[0].reason == RejectReason.ORDER_NOT_FOUND


def test_validation_and_duplicate_rejection():
    """Verifies that invalid price, invalid quantity, and duplicate order IDs are cleanly rejected."""
    engine = MatchingEngine()

    # Negative quantity
    ev1 = engine.process_command(
        NewOrderCommand("bad1", "BTC-USDT", Side.BUY, OrderType.LIMIT, to_fixed_point("100"), 0)
    )
    assert any(isinstance(e, OrderRejectedEvent) and e.reason == RejectReason.INVALID_QUANTITY for e in ev1)

    # Zero limit price
    ev2 = engine.process_command(
        NewOrderCommand("bad2", "BTC-USDT", Side.BUY, OrderType.LIMIT, 0, to_fixed_point("1.0"))
    )
    assert any(isinstance(e, OrderRejectedEvent) and e.reason == RejectReason.INVALID_PRICE for e in ev2)

    # Duplicate order ID
    engine.process_command(
        NewOrderCommand("dup1", "BTC-USDT", Side.BUY, OrderType.LIMIT, to_fixed_point("100"), to_fixed_point("1.0"))
    )
    ev3 = engine.process_command(
        NewOrderCommand("dup1", "BTC-USDT", Side.BUY, OrderType.LIMIT, to_fixed_point("100"), to_fixed_point("1.0"))
    )
    assert any(isinstance(e, OrderRejectedEvent) and e.reason == RejectReason.DUPLICATE_ORDER_ID for e in ev3)
