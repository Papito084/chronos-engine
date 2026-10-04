"""
ChronosEngine - Event Sourcing Contracts and Inbound/Outbound Events.
All events are strictly serialized, immutable, and carry monotonically increasing sequence numbers.
"""

from dataclasses import dataclass
from typing import Optional, Union, Dict, Any
from core.models.types import (
    Side,
    OrderType,
    TimeInForce,
    RejectReason,
    from_fixed_point,
    fixed_to_str,
)


@dataclass(slots=True)
class NewOrderCommand:
    order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    price: int                  # Fixed-point 10^8
    quantity: int               # Fixed-point 10^8
    time_in_force: TimeInForce = TimeInForce.GTC
    timestamp_ns: int = 0


@dataclass(slots=True)
class CancelOrderCommand:
    order_id: str
    symbol: str
    timestamp_ns: int = 0


# --- Output Events for Event Sourcing ---

@dataclass(slots=True)
class OrderAcceptedEvent:
    sequence_number: int
    timestamp_ns: int
    order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    price: int
    quantity: int
    time_in_force: TimeInForce
    event_type: str = "ORDER_ACCEPTED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "sequence_number": self.sequence_number,
            "timestamp_ns": self.timestamp_ns,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "price": self.price,
            "price_str": fixed_to_str(self.price),
            "quantity": self.quantity,
            "quantity_str": fixed_to_str(self.quantity),
            "time_in_force": self.time_in_force.value,
        }


@dataclass(slots=True)
class OrderRejectedEvent:
    sequence_number: int
    timestamp_ns: int
    order_id: str
    symbol: str
    reason: RejectReason
    message: str
    event_type: str = "ORDER_REJECTED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "sequence_number": self.sequence_number,
            "timestamp_ns": self.timestamp_ns,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "reason": self.reason.value,
            "message": self.message,
        }


@dataclass(slots=True)
class OrderMatchedEvent:
    sequence_number: int
    timestamp_ns: int
    trade_id: int
    symbol: str
    maker_order_id: str
    taker_order_id: str
    maker_side: Side
    taker_side: Side
    price: int
    quantity: int
    quote_amount: int
    maker_remaining_qty: int
    taker_remaining_qty: int
    event_type: str = "ORDER_MATCHED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "sequence_number": self.sequence_number,
            "timestamp_ns": self.timestamp_ns,
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "maker_order_id": self.maker_order_id,
            "taker_order_id": self.taker_order_id,
            "maker_side": self.maker_side.value,
            "taker_side": self.taker_side.value,
            "price": self.price,
            "price_str": fixed_to_str(self.price),
            "quantity": self.quantity,
            "quantity_str": fixed_to_str(self.quantity),
            "quote_amount": self.quote_amount,
            "quote_amount_str": fixed_to_str(self.quote_amount),
            "maker_remaining_qty": self.maker_remaining_qty,
            "maker_remaining_qty_str": fixed_to_str(self.maker_remaining_qty),
            "taker_remaining_qty": self.taker_remaining_qty,
            "taker_remaining_qty_str": fixed_to_str(self.taker_remaining_qty),
        }


@dataclass(slots=True)
class OrderCanceledEvent:
    sequence_number: int
    timestamp_ns: int
    order_id: str
    symbol: str
    reason: str
    remaining_quantity: int
    event_type: str = "ORDER_CANCELED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "sequence_number": self.sequence_number,
            "timestamp_ns": self.timestamp_ns,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "reason": self.reason,
            "remaining_quantity": self.remaining_quantity,
            "remaining_quantity_str": fixed_to_str(self.remaining_quantity),
        }


@dataclass(slots=True)
class OrderFilledEvent:
    sequence_number: int
    timestamp_ns: int
    order_id: str
    symbol: str
    filled_quantity: int
    event_type: str = "ORDER_FILLED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "sequence_number": self.sequence_number,
            "timestamp_ns": self.timestamp_ns,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "filled_quantity": self.filled_quantity,
            "filled_quantity_str": fixed_to_str(self.filled_quantity),
        }


@dataclass(slots=True)
class BookLevelUpdatedEvent:
    sequence_number: int
    timestamp_ns: int
    symbol: str
    side: Side
    price: int
    new_volume: int
    order_count: int
    event_type: str = "BOOK_LEVEL_UPDATED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "sequence_number": self.sequence_number,
            "timestamp_ns": self.timestamp_ns,
            "symbol": self.symbol,
            "side": self.side.value,
            "price": self.price,
            "price_str": fixed_to_str(self.price),
            "new_volume": self.new_volume,
            "new_volume_str": fixed_to_str(self.new_volume),
            "order_count": self.order_count,
        }


EngineEvent = Union[
    OrderAcceptedEvent,
    OrderRejectedEvent,
    OrderMatchedEvent,
    OrderCanceledEvent,
    OrderFilledEvent,
    BookLevelUpdatedEvent,
]
