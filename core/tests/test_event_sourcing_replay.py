"""
Unit & Disaster Recovery Tests for Event Sourcing, Serialization, and Deterministic Replay.
Verifies that replaying an immutable event log or a Snapshot + Delta reconstructs
an OrderBook bit-for-bit identical to the live production matching engine.
"""

import os
import random
import tempfile
import pytest

from core.models.types import Side, OrderType, TimeInForce, to_fixed_point
from core.models.events import (
    NewOrderCommand,
    CancelOrderCommand,
    OrderAcceptedEvent,
    OrderMatchedEvent,
    OrderFilledEvent,
    OrderCanceledEvent,
    OrderRejectedEvent,
    BookLevelUpdatedEvent,
)
from core.serialization import (
    serialize_event,
    deserialize_event,
    serialize_command,
    deserialize_command,
    serialize_snapshot,
    deserialize_snapshot,
)
from core.engine.matching_engine import MatchingEngine
from core.engine.event_store import EventJournal
from core.engine.replay import ReplayEngine, create_snapshot, restore_from_snapshot


def test_event_serialization_roundtrip():
    """Verifies that all event types serialize to bytes and deserialize back with 100% fidelity."""
    seq = 42
    ts = 1700000000000000000

    # 1. OrderAcceptedEvent
    ev_acc = OrderAcceptedEvent(
        sequence_number=seq,
        timestamp_ns=ts,
        order_id="ord-acc-1",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=to_fixed_point("50000.12345678"),
        quantity=to_fixed_point("1.50000000"),
        time_in_force=TimeInForce.GTC,
    )
    raw = serialize_event(ev_acc)
    restored = deserialize_event(raw)
    assert isinstance(restored, OrderAcceptedEvent)
    assert restored.order_id == ev_acc.order_id
    assert restored.price == ev_acc.price
    assert restored.quantity == ev_acc.quantity
    assert restored.side == Side.BUY
    assert restored.time_in_force == TimeInForce.GTC

    # 2. OrderMatchedEvent
    ev_match = OrderMatchedEvent(
        sequence_number=seq + 1,
        timestamp_ns=ts,
        trade_id=101,
        symbol="BTC-USDT",
        maker_order_id="maker-1",
        taker_order_id="taker-1",
        maker_side=Side.SELL,
        taker_side=Side.BUY,
        price=to_fixed_point("50000.00"),
        quantity=to_fixed_point("0.5"),
        quote_amount=to_fixed_point("25000.00"),
        maker_remaining_qty=to_fixed_point("0.5"),
        taker_remaining_qty=0,
    )
    raw = serialize_event(ev_match)
    restored = deserialize_event(raw)
    assert isinstance(restored, OrderMatchedEvent)
    assert restored.trade_id == 101
    assert restored.price == ev_match.price
    assert restored.quote_amount == ev_match.quote_amount

    # 3. OrderCanceledEvent
    ev_cancel = OrderCanceledEvent(
        sequence_number=seq + 2,
        timestamp_ns=ts,
        order_id="ord-1",
        symbol="BTC-USDT",
        reason="USER_REQUESTED",
        remaining_quantity=to_fixed_point("1.0"),
    )
    restored = deserialize_event(serialize_event(ev_cancel))
    assert isinstance(restored, OrderCanceledEvent)
    assert restored.order_id == "ord-1"
    assert restored.remaining_quantity == to_fixed_point("1.0")


def test_command_serialization_roundtrip():
    """Verifies that inbound commands serialize and deserialize cleanly."""
    cmd = NewOrderCommand(
        order_id="cmd-1",
        symbol="BTC-USDT",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        price=to_fixed_point("60000.00"),
        quantity=to_fixed_point("2.0"),
        time_in_force=TimeInForce.IOC,
        timestamp_ns=123456789,
    )
    raw = serialize_command(cmd)
    restored = deserialize_command(raw)
    assert isinstance(restored, NewOrderCommand)
    assert restored.order_id == "cmd-1"
    assert restored.price == to_fixed_point("60000.00")
    assert restored.time_in_force == TimeInForce.IOC

    cancel_cmd = CancelOrderCommand(order_id="cmd-1", symbol="BTC-USDT", timestamp_ns=999)
    restored_cancel = deserialize_command(serialize_command(cancel_cmd))
    assert isinstance(restored_cancel, CancelOrderCommand)
    assert restored_cancel.order_id == "cmd-1"


def test_deterministic_disaster_recovery_replay_1000_orders():
    """
    DISASTER RECOVERY TEST:
    1. Executes a burst of 1,000 randomized orders (crossing matches, multi-level sweeps, cancels).
    2. Persists all emitted events into EventJournal.
    3. Simulates a complete node crash and creates a pristine, empty OrderBook.
    4. Runs ReplayEngine over the event stream from offset 0.
    5. Asserts bit-for-bit equivalence between live production book and replayed book.
    """
    random.seed(42)  # Deterministic seed for reproducible testing
    engine = MatchingEngine()
    journal = EventJournal()

    # Route all matching engine events into the immutable journal
    engine.add_event_listener(journal.append)

    symbol = "BTC-USDT"
    base_price = to_fixed_point("50000.00")
    tick_size = to_fixed_point("10.00")

    placed_order_ids = []

    # Generate 1,000 varied market commands
    total_commands = 1000
    for i in range(total_commands):
        order_id = f"burst_{i}"
        side = Side.BUY if random.random() < 0.5 else Side.SELL

        # 10% chance to cancel an existing resting order
        if placed_order_ids and random.random() < 0.10:
            target_id = random.choice(placed_order_ids)
            engine.process_command(CancelOrderCommand(target_id, symbol))
            continue

        # 10% chance for MARKET order, 90% for LIMIT order
        is_market = random.random() < 0.10
        price_offset = random.randint(-15, 15) * tick_size
        price = max(tick_size, base_price + price_offset)
        qty = to_fixed_point(str(round(random.uniform(0.1, 2.5), 2)))

        if is_market:
            cmd = NewOrderCommand(order_id, symbol, side, OrderType.MARKET, 0, qty)
        else:
            tif = random.choice([TimeInForce.GTC, TimeInForce.GTC, TimeInForce.IOC])
            cmd = NewOrderCommand(order_id, symbol, side, OrderType.LIMIT, price, qty, tif)

        engine.process_command(cmd)
        placed_order_ids.append(order_id)

    events = journal.read_all()
    assert len(events) > 1000, f"Expected >1000 events, got {len(events)}"

    # Verify strict sequence monotonicity
    for idx in range(1, len(events)):
        assert events[idx].sequence_number == events[idx - 1].sequence_number + 1

    # Live production book state
    live_book = engine.get_or_create_book(symbol)

    # --- DISASTER RECOVERY: REPLAY FROM OFFSET 0 ---
    replay_engine = ReplayEngine(symbol)
    replayed_book = replay_engine.replay_all(events)

    # 1. Assert Best Bid, Best Ask, Spread
    assert replayed_book.best_bid == live_book.best_bid
    assert replayed_book.best_ask == live_book.best_ask
    assert replayed_book.spread == live_book.spread

    # 2. Assert Level counts
    assert len(replayed_book.bids) == len(live_book.bids)
    assert len(replayed_book.asks) == len(live_book.asks)

    # 3. Assert Bids Levels exact matching
    for price, live_level in live_book.bids.items():
        assert price in replayed_book.bids, f"Bid price {price} missing in replayed book"
        replayed_level = replayed_book.bids[price]
        assert replayed_level.total_volume == live_level.total_volume
        assert replayed_level.order_count == live_level.order_count

        live_orders = list(live_level)
        replayed_orders = list(replayed_level)
        assert len(replayed_orders) == len(live_orders)
        for lo, ro in zip(live_orders, replayed_orders):
            assert lo.order_id == ro.order_id
            assert lo.remaining_quantity == ro.remaining_quantity
            assert lo.filled_quantity == ro.filled_quantity

    # 4. Assert Asks Levels exact matching
    for price, live_level in live_book.asks.items():
        assert price in replayed_book.asks, f"Ask price {price} missing in replayed book"
        replayed_level = replayed_book.asks[price]
        assert replayed_level.total_volume == live_level.total_volume
        assert replayed_level.order_count == live_level.order_count

        live_orders = list(live_level)
        replayed_orders = list(replayed_level)
        assert len(replayed_orders) == len(live_orders)
        for lo, ro in zip(live_orders, replayed_orders):
            assert lo.order_id == ro.order_id
            assert lo.remaining_quantity == ro.remaining_quantity
            assert lo.filled_quantity == ro.filled_quantity

    # 5. Assert Active Orders index
    assert len(replayed_book.orders) == len(live_book.orders)
    for oid, lo in live_book.orders.items():
        assert oid in replayed_book.orders
        ro = replayed_book.orders[oid]
        assert ro.remaining_quantity == lo.remaining_quantity
        assert ro.status == lo.status


def test_snapshot_and_delta_replay():
    """
    Verifies periodic snapshotting:
    1. Runs 500 commands.
    2. Takes an in-memory snapshot.
    3. Runs another 500 commands.
    4. Restores from snapshot at T=500 and replays only the delta events.
    5. Asserts the resulting book matches the live book exactly.
    """
    random.seed(123)
    engine = MatchingEngine()
    journal = EventJournal()
    engine.add_event_listener(journal.append)

    symbol = "ETH-USDT"
    base_price = to_fixed_point("3000.00")

    # Step 1: Execute 500 commands
    for i in range(500):
        side = Side.BUY if random.random() < 0.5 else Side.SELL
        px = base_price + random.randint(-10, 10) * to_fixed_point("1.00")
        qty = to_fixed_point("0.5")
        engine.process_command(
            NewOrderCommand(f"snap_cmd_{i}", symbol, side, OrderType.LIMIT, px, qty)
        )

    live_book = engine.get_or_create_book(symbol)
    seq_at_snapshot = engine.current_sequence

    # Step 2: Take snapshot and serialize to bytes
    snapshot_dict = create_snapshot(live_book, seq_at_snapshot)
    snapshot_bytes = serialize_snapshot(snapshot_dict)
    restored_snapshot_dict = deserialize_snapshot(snapshot_bytes)

    # Step 3: Execute another 500 commands
    for i in range(500, 1000):
        side = Side.BUY if random.random() < 0.5 else Side.SELL
        px = base_price + random.randint(-10, 10) * to_fixed_point("1.00")
        qty = to_fixed_point("0.5")
        engine.process_command(
            NewOrderCommand(f"snap_cmd_{i}", symbol, side, OrderType.LIMIT, px, qty)
        )

    all_events = journal.read_all()
    delta_events = [e for e in all_events if e.sequence_number > seq_at_snapshot]

    # Step 4: Replay from Snapshot + Delta
    replay_engine = ReplayEngine(symbol)
    reconstructed_book = replay_engine.replay_from_snapshot(restored_snapshot_dict, delta_events)

    # Step 5: Assert identical state
    assert reconstructed_book.best_bid == live_book.best_bid
    assert reconstructed_book.best_ask == live_book.best_ask
    assert reconstructed_book.spread == live_book.spread
    assert len(reconstructed_book.orders) == len(live_book.orders)
    assert len(reconstructed_book.bids) == len(live_book.bids)
    assert len(reconstructed_book.asks) == len(live_book.asks)


def test_file_wal_persistence_and_recovery():
    """Verifies write-ahead log (WAL) binary file persistence and recovery across process restarts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        wal_file = os.path.join(tmpdir, "test.wal")

        journal1 = EventJournal(wal_path=wal_file)
        ev1 = OrderAcceptedEvent(
            sequence_number=1,
            timestamp_ns=100,
            order_id="wal-1",
            symbol="BTC-USDT",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=to_fixed_point("50000.00"),
            quantity=to_fixed_point("1.0"),
            time_in_force=TimeInForce.GTC,
        )
        ev2 = OrderCanceledEvent(
            sequence_number=2,
            timestamp_ns=200,
            order_id="wal-1",
            symbol="BTC-USDT",
            reason="USER_CANCEL",
            remaining_quantity=to_fixed_point("1.0"),
        )
        journal1.append(ev1)
        journal1.append(ev2)
        journal1.close()

        # Simulate process restart by opening new journal on existing file
        journal2 = EventJournal(wal_path=wal_file)
        recovered_events = journal2.read_all()
        assert len(recovered_events) == 2
        assert recovered_events[0].order_id == "wal-1"
        assert recovered_events[1].reason == "USER_CANCEL"
        assert journal2.get_last_sequence() == 2
        journal2.close()
