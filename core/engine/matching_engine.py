"""
ChronosEngine - Deterministic Single-Threaded Matching Engine.
Features:
- Price-Time Priority (FIFO) matching.
- Limit, Market, Cancel order types.
- GTC, IOC, FOK Time-in-Force logic.
- Integer fixed-point math (8 decimal places).
- Complete Event Sourcing emission with monotonic sequence numbering.
"""

import time
from typing import Dict, List, Optional, Union

from core.models.types import (
    Side,
    OrderType,
    TimeInForce,
    OrderStatus,
    RejectReason,
    calculate_quote_amount,
)
from core.models.order import Order
from core.models.trade import Trade
from core.models.price_level import PriceLevel
from core.models.events import (
    NewOrderCommand,
    CancelOrderCommand,
    OrderAcceptedEvent,
    OrderRejectedEvent,
    OrderMatchedEvent,
    OrderCanceledEvent,
    OrderFilledEvent,
    BookLevelUpdatedEvent,
    EngineEvent,
)
from core.engine.order_book import OrderBook


class MatchingEngine:
    __slots__ = (
        "books",
        "_sequence_number",
        "_trade_id",
        "_processed_order_ids",
        "trades_history",
        "event_listeners",
    )

    def __init__(self) -> None:
        self.books: Dict[str, OrderBook] = {}
        self._sequence_number: int = 0
        self._trade_id: int = 0
        self._processed_order_ids: set[str] = set()
        self.trades_history: List[Trade] = []
        self.event_listeners: List[callable] = []

    def get_or_create_book(self, symbol: str) -> OrderBook:
        """Retrieves or instantiates an OrderBook for the given symbol."""
        if symbol not in self.books:
            self.books[symbol] = OrderBook(symbol)
        return self.books[symbol]

    def _next_sequence(self) -> int:
        self._sequence_number += 1
        return self._sequence_number

    def _next_trade_id(self) -> int:
        self._trade_id += 1
        return self._trade_id

    @property
    def current_sequence(self) -> int:
        return self._sequence_number

    def add_event_listener(self, listener: callable) -> None:
        """Subscribes an event listener (e.g. Kafka/Redpanda dispatcher, WebSocket broadcaster)."""
        self.event_listeners.append(listener)

    def _emit(self, event: EngineEvent, events: List[EngineEvent]) -> None:
        """Appends event to the command's result batch and dispatches to registered listeners."""
        events.append(event)
        for listener in self.event_listeners:
            listener(event)

    def process_command(
        self,
        command: Union[NewOrderCommand, CancelOrderCommand],
    ) -> List[EngineEvent]:
        """
        Deterministic, atomic single-threaded command handler.
        All state transitions and output events are strictly sequenced.
        """
        events: List[EngineEvent] = []
        if isinstance(command, NewOrderCommand):
            self._handle_new_order(command, events)
        elif isinstance(command, CancelOrderCommand):
            self._handle_cancel_order(command, events)
        return events

    def _handle_new_order(
        self,
        cmd: NewOrderCommand,
        events: List[EngineEvent],
    ) -> None:
        ts = cmd.timestamp_ns if cmd.timestamp_ns > 0 else time.time_ns()
        book = self.get_or_create_book(cmd.symbol)

        # 1. Validation Checks
        if cmd.order_id in self._processed_order_ids:
            self._emit(
                OrderRejectedEvent(
                    sequence_number=self._next_sequence(),
                    timestamp_ns=ts,
                    order_id=cmd.order_id,
                    symbol=cmd.symbol,
                    reason=RejectReason.DUPLICATE_ORDER_ID,
                    message=f"Order ID {cmd.order_id} already exists",
                ),
                events,
            )
            return

        if cmd.quantity <= 0:
            self._emit(
                OrderRejectedEvent(
                    sequence_number=self._next_sequence(),
                    timestamp_ns=ts,
                    order_id=cmd.order_id,
                    symbol=cmd.symbol,
                    reason=RejectReason.INVALID_QUANTITY,
                    message="Order quantity must be strictly positive",
                ),
                events,
            )
            return

        if cmd.order_type == OrderType.LIMIT and cmd.price <= 0:
            self._emit(
                OrderRejectedEvent(
                    sequence_number=self._next_sequence(),
                    timestamp_ns=ts,
                    order_id=cmd.order_id,
                    symbol=cmd.symbol,
                    reason=RejectReason.INVALID_PRICE,
                    message="Limit order price must be strictly positive",
                ),
                events,
            )
            return

        # 2. Check FOK (Fill-Or-Kill) pre-condition: must be 100% fillable immediately
        if cmd.time_in_force == TimeInForce.FOK:
            limit_price = cmd.price if cmd.order_type == OrderType.LIMIT else None
            can_fill = book.check_fok_fillable(cmd.side, cmd.quantity, limit_price)
            if not can_fill:
                self._emit(
                    OrderRejectedEvent(
                        sequence_number=self._next_sequence(),
                        timestamp_ns=ts,
                        order_id=cmd.order_id,
                        symbol=cmd.symbol,
                        reason=RejectReason.FOK_CANNOT_BE_FILLED,
                        message="FOK order cannot be filled immediately in its entirety",
                    ),
                    events,
                )
                return

        # 3. Order is officially Accepted into the engine
        self._processed_order_ids.add(cmd.order_id)
        self._emit(
            OrderAcceptedEvent(
                sequence_number=self._next_sequence(),
                timestamp_ns=ts,
                order_id=cmd.order_id,
                symbol=cmd.symbol,
                side=cmd.side,
                order_type=cmd.order_type,
                price=cmd.price,
                quantity=cmd.quantity,
                time_in_force=cmd.time_in_force,
            ),
            events,
        )

        taker = Order(
            order_id=cmd.order_id,
            symbol=cmd.symbol,
            side=cmd.side,
            order_type=cmd.order_type,
            price=cmd.price,
            quantity=cmd.quantity,
            time_in_force=cmd.time_in_force,
            timestamp_ns=ts,
            sequence_number=self._sequence_number,
        )

        # 4. Matching Loop: Aggress against opposing book
        opposing_tree = book.asks if cmd.side == Side.BUY else book.bids

        while taker.remaining_quantity > 0 and opposing_tree:
            # Inspect best opposing price level (keys()[0] is best bid/ask)
            best_opposing_price = opposing_tree.keys()[0]

            # Price crossing check:
            if cmd.order_type == OrderType.LIMIT:
                if cmd.side == Side.BUY and best_opposing_price > cmd.price:
                    # Best ask is higher than taker's buy limit -> no crossing
                    break
                if cmd.side == Side.SELL and best_opposing_price < cmd.price:
                    # Best bid is lower than taker's sell limit -> no crossing
                    break

            level: PriceLevel = opposing_tree[best_opposing_price]

            # Iterate through resting orders in this level (FIFO order)
            while taker.remaining_quantity > 0 and not level.is_empty():
                maker: Order = level.peek()
                match_price = maker.price
                match_qty = min(taker.remaining_quantity, maker.remaining_quantity)
                quote_amt = calculate_quote_amount(match_price, match_qty)

                # Execute fill
                maker.fill(match_qty)
                level.reduce_volume(match_qty)
                taker.fill(match_qty)

                trade = Trade.create(
                    trade_id=self._next_trade_id(),
                    maker_order_id=maker.order_id,
                    taker_order_id=taker.order_id,
                    symbol=cmd.symbol,
                    price=match_price,
                    quantity=match_qty,
                    maker_side=maker.side,
                    taker_side=taker.side,
                    sequence_number=self._next_sequence(),
                    timestamp_ns=ts,
                )
                self.trades_history.append(trade)

                # Emit OrderMatchedEvent
                self._emit(
                    OrderMatchedEvent(
                        sequence_number=trade.sequence_number,
                        timestamp_ns=ts,
                        trade_id=trade.trade_id,
                        symbol=cmd.symbol,
                        maker_order_id=maker.order_id,
                        taker_order_id=taker.order_id,
                        maker_side=maker.side,
                        taker_side=taker.side,
                        price=match_price,
                        quantity=match_qty,
                        quote_amount=quote_amt,
                        maker_remaining_qty=maker.remaining_quantity,
                        taker_remaining_qty=taker.remaining_quantity,
                    ),
                    events,
                )

                # Check if maker is completely filled
                if maker.is_filled:
                    level.remove(maker)
                    if maker.order_id in book.orders:
                        del book.orders[maker.order_id]
                    self._emit(
                        OrderFilledEvent(
                            sequence_number=self._next_sequence(),
                            timestamp_ns=ts,
                            order_id=maker.order_id,
                            symbol=cmd.symbol,
                            filled_quantity=maker.filled_quantity,
                        ),
                        events,
                    )
                else:
                    # Maker was only partially filled, so taker must be 0 remaining
                    pass

            # Level status update event
            if level.is_empty():
                if best_opposing_price in opposing_tree:
                    del opposing_tree[best_opposing_price]
                self._emit(
                    BookLevelUpdatedEvent(
                        sequence_number=self._next_sequence(),
                        timestamp_ns=ts,
                        symbol=cmd.symbol,
                        side=Side.SELL if cmd.side == Side.BUY else Side.BUY,
                        price=best_opposing_price,
                        new_volume=0,
                        order_count=0,
                    ),
                    events,
                )
            else:
                self._emit(
                    BookLevelUpdatedEvent(
                        sequence_number=self._next_sequence(),
                        timestamp_ns=ts,
                        symbol=cmd.symbol,
                        side=Side.SELL if cmd.side == Side.BUY else Side.BUY,
                        price=best_opposing_price,
                        new_volume=level.total_volume,
                        order_count=level.order_count,
                    ),
                    events,
                )

        # 5. Post-Matching Resolution for Taker Order
        if taker.is_filled:
            self._emit(
                OrderFilledEvent(
                    sequence_number=self._next_sequence(),
                    timestamp_ns=ts,
                    order_id=taker.order_id,
                    symbol=cmd.symbol,
                    filled_quantity=taker.filled_quantity,
                ),
                events,
            )
        else:
            # Order still has remaining quantity
            if taker.order_type == OrderType.MARKET:
                # Market order cannot rest on book; cancel leftover
                self._emit(
                    OrderCanceledEvent(
                        sequence_number=self._next_sequence(),
                        timestamp_ns=ts,
                        order_id=taker.order_id,
                        symbol=cmd.symbol,
                        reason="MARKET_EXHAUSTED_BOOK_LIQUIDITY",
                        remaining_quantity=taker.remaining_quantity,
                    ),
                    events,
                )
            elif taker.time_in_force == TimeInForce.IOC:
                # IOC cannot rest on book; cancel leftover
                self._emit(
                    OrderCanceledEvent(
                        sequence_number=self._next_sequence(),
                        timestamp_ns=ts,
                        order_id=taker.order_id,
                        symbol=cmd.symbol,
                        reason="IOC_REMAINDER_CANCELED",
                        remaining_quantity=taker.remaining_quantity,
                    ),
                    events,
                )
            elif taker.order_type == OrderType.LIMIT and taker.time_in_force == TimeInForce.GTC:
                # Rest in the book
                level = book.add_order(taker)
                self._emit(
                    BookLevelUpdatedEvent(
                        sequence_number=self._next_sequence(),
                        timestamp_ns=ts,
                        symbol=cmd.symbol,
                        side=taker.side,
                        price=taker.price,
                        new_volume=level.total_volume,
                        order_count=level.order_count,
                    ),
                    events,
                )

    def _handle_cancel_order(
        self,
        cmd: CancelOrderCommand,
        events: List[EngineEvent],
    ) -> None:
        ts = cmd.timestamp_ns if cmd.timestamp_ns > 0 else time.time_ns()
        book = self.books.get(cmd.symbol)

        if book is None:
            self._emit(
                OrderRejectedEvent(
                    sequence_number=self._next_sequence(),
                    timestamp_ns=ts,
                    order_id=cmd.order_id,
                    symbol=cmd.symbol,
                    reason=RejectReason.ORDER_NOT_FOUND,
                    message=f"Order book for symbol {cmd.symbol} not found",
                ),
                events,
            )
            return

        order = book.get_order(cmd.order_id)
        if order is None or not order.is_active:
            self._emit(
                OrderRejectedEvent(
                    sequence_number=self._next_sequence(),
                    timestamp_ns=ts,
                    order_id=cmd.order_id,
                    symbol=cmd.symbol,
                    reason=RejectReason.ORDER_NOT_FOUND,
                    message=f"Active order {cmd.order_id} not found in book",
                ),
                events,
            )
            return

        price = order.price
        side = order.side
        rem_qty = order.remaining_quantity
        book.cancel_order(cmd.order_id)

        self._emit(
            OrderCanceledEvent(
                sequence_number=self._next_sequence(),
                timestamp_ns=ts,
                order_id=cmd.order_id,
                symbol=cmd.symbol,
                reason="USER_REQUESTED_CANCEL",
                remaining_quantity=rem_qty,
            ),
            events,
        )

        # Check remaining level volume
        tree = book.bids if side == Side.BUY else book.asks
        level = tree.get(price)
        vol = level.total_volume if level is not None else 0
        cnt = level.order_count if level is not None else 0

        self._emit(
            BookLevelUpdatedEvent(
                sequence_number=self._next_sequence(),
                timestamp_ns=ts,
                symbol=cmd.symbol,
                side=side,
                price=price,
                new_volume=vol,
                order_count=cnt,
            ),
            events,
        )
