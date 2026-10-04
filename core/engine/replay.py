"""
ChronosEngine - Deterministic Replay Engine & Snapshotting.
Reconstructs exact L3 OrderBook state from an immutable event log or from a Snapshot + Delta events.
Never emits duplicate output events or side-effects during replay.
"""

from typing import Dict, List, Optional, Tuple, Iterable, Any
from core.models.types import Side, OrderType, TimeInForce, OrderStatus
from core.models.order import Order
from core.models.price_level import PriceLevel
from core.models.events import (
    EngineEvent,
    OrderAcceptedEvent,
    OrderMatchedEvent,
    OrderFilledEvent,
    OrderCanceledEvent,
    BookLevelUpdatedEvent,
    OrderRejectedEvent,
)
from core.engine.order_book import OrderBook


def create_snapshot(book: OrderBook, sequence_number: int) -> Dict[str, Any]:
    """
    Creates an exact deterministic snapshot of the in-memory OrderBook state at sequence T.
    Captures resting orders in strict FIFO sequence per price level.
    """
    bids_snapshot = []
    for price, level in book.bids.items():
        level_data = {
            "price": price,
            "orders": [
                {
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "side": o.side.value,
                    "order_type": o.order_type.value,
                    "price": o.price,
                    "initial_quantity": o.initial_quantity,
                    "remaining_quantity": o.remaining_quantity,
                    "filled_quantity": o.filled_quantity,
                    "time_in_force": o.time_in_force.value,
                    "status": o.status.value,
                    "timestamp_ns": o.timestamp_ns,
                    "sequence_number": o.sequence_number,
                }
                for o in level
            ],
        }
        bids_snapshot.append(level_data)

    asks_snapshot = []
    for price, level in book.asks.items():
        level_data = {
            "price": price,
            "orders": [
                {
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "side": o.side.value,
                    "order_type": o.order_type.value,
                    "price": o.price,
                    "initial_quantity": o.initial_quantity,
                    "remaining_quantity": o.remaining_quantity,
                    "filled_quantity": o.filled_quantity,
                    "time_in_force": o.time_in_force.value,
                    "status": o.status.value,
                    "timestamp_ns": o.timestamp_ns,
                    "sequence_number": o.sequence_number,
                }
                for o in level
            ],
        }
        asks_snapshot.append(level_data)

    return {
        "symbol": book.symbol,
        "sequence_number": sequence_number,
        "bids": bids_snapshot,
        "asks": asks_snapshot,
    }


def restore_from_snapshot(snapshot: Dict[str, Any]) -> Tuple[OrderBook, int]:
    """
    Restores a fully functional, bit-identical OrderBook from a snapshot dictionary.
    Returns (book, snapshot_sequence_number).
    """
    book = OrderBook(snapshot["symbol"])
    seq_num = snapshot.get("sequence_number", 0)

    # Restore Bids
    for lvl in snapshot.get("bids", []):
        for o_dict in lvl["orders"]:
            order = Order(
                order_id=o_dict["order_id"],
                symbol=o_dict["symbol"],
                side=Side(o_dict["side"]),
                order_type=OrderType(o_dict["order_type"]),
                price=o_dict["price"],
                quantity=o_dict["initial_quantity"],
                time_in_force=TimeInForce(o_dict["time_in_force"]),
                timestamp_ns=o_dict["timestamp_ns"],
                sequence_number=o_dict["sequence_number"],
            )
            order.remaining_quantity = o_dict["remaining_quantity"]
            order.filled_quantity = o_dict["filled_quantity"]
            order.status = OrderStatus(o_dict["status"])
            book.add_order(order)

    # Restore Asks
    for lvl in snapshot.get("asks", []):
        for o_dict in lvl["orders"]:
            order = Order(
                order_id=o_dict["order_id"],
                symbol=o_dict["symbol"],
                side=Side(o_dict["side"]),
                order_type=OrderType(o_dict["order_type"]),
                price=o_dict["price"],
                quantity=o_dict["initial_quantity"],
                time_in_force=TimeInForce(o_dict["time_in_force"]),
                timestamp_ns=o_dict["timestamp_ns"],
                sequence_number=o_dict["sequence_number"],
            )
            order.remaining_quantity = o_dict["remaining_quantity"]
            order.filled_quantity = o_dict["filled_quantity"]
            order.status = OrderStatus(o_dict["status"])
            book.add_order(order)

    return book, seq_num


class ReplayEngine:
    """
    State-Machine Replay Processor.
    Consumes recorded market.events to reconstruct the exact OrderBook state.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol: str = symbol
        self.book: OrderBook = OrderBook(symbol)
        self.orders: Dict[str, Order] = {}
        self._current_taker: Optional[Order] = None
        self.last_replayed_sequence: int = 0

    def replay_event(self, event: EngineEvent) -> None:
        """Applies a single event state transition."""
        self.last_replayed_sequence = max(self.last_replayed_sequence, event.sequence_number)

        if isinstance(event, OrderAcceptedEvent):
            order = Order(
                order_id=event.order_id,
                symbol=event.symbol,
                side=event.side,
                order_type=event.order_type,
                price=event.price,
                quantity=event.quantity,
                time_in_force=event.time_in_force,
                timestamp_ns=event.timestamp_ns,
                sequence_number=event.sequence_number,
            )
            self.orders[event.order_id] = order
            self._current_taker = order

        elif isinstance(event, OrderMatchedEvent):
            maker = self.orders.get(event.maker_order_id)
            if maker is not None:
                maker.fill(event.quantity)
                if maker.parent_level is not None:
                    maker.parent_level.reduce_volume(event.quantity)

            if self._current_taker is not None and self._current_taker.order_id == event.taker_order_id:
                self._current_taker.fill(event.quantity)
            elif event.taker_order_id in self.orders:
                self.orders[event.taker_order_id].fill(event.quantity)

        elif isinstance(event, OrderFilledEvent):
            if self._current_taker is not None and self._current_taker.order_id == event.order_id:
                # Taker order completely filled in aggressive pass; will not rest
                self._current_taker = None
            else:
                # Resting maker order completed; remove from book in O(1)
                self.book.remove_order(event.order_id)

        elif isinstance(event, OrderCanceledEvent):
            if self._current_taker is not None and self._current_taker.order_id == event.order_id:
                # Taker order remainder canceled (e.g. IOC or Market); will not rest
                self._current_taker.status = OrderStatus.CANCELED
                self._current_taker = None
            else:
                # Resting order canceled
                self.book.cancel_order(event.order_id)
                if event.order_id in self.orders:
                    self.orders[event.order_id].status = OrderStatus.CANCELED

        elif isinstance(event, BookLevelUpdatedEvent):
            # Check if current taker is resting into the book
            if (
                self._current_taker is not None
                and self._current_taker.side == event.side
                and self._current_taker.price == event.price
                and self._current_taker.is_active
            ):
                self.book.add_order(self._current_taker)
                self._current_taker = None

        elif isinstance(event, OrderRejectedEvent):
            # No state change in book
            pass

    def replay_all(self, events: Iterable[EngineEvent], from_sequence: int = 0) -> OrderBook:
        """Replays an event stream sequentially from a given sequence threshold."""
        for event in events:
            if event.sequence_number > from_sequence:
                self.replay_event(event)
        return self.book

    def replay_from_snapshot(
        self,
        snapshot: Dict[str, Any],
        delta_events: Iterable[EngineEvent],
    ) -> OrderBook:
        """Restores from snapshot and continues replaying subsequent delta events."""
        self.book, snapshot_seq = restore_from_snapshot(snapshot)
        # Re-register resting orders into self.orders index
        for order_id, order in self.book.orders.items():
            self.orders[order_id] = order
        self.last_replayed_sequence = snapshot_seq

        return self.replay_all(delta_events, from_sequence=snapshot_seq)
