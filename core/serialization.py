"""
ChronosEngine - Ultra-Fast Deterministic Serialization.
Uses orjson (Rust-backed) to serialize/deserialize events and commands to/from bytes.
Strictly preserves 64-bit integer Fixed-Point (10^8) scales, monotonic sequence numbers,
and type-safe domain Enums.
"""

from typing import Union, Dict, Any
import orjson

from core.models.types import Side, OrderType, TimeInForce, RejectReason
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


def _default_encoder(obj: Any) -> Any:
    """Handles domain Enums and custom types for orjson serialization."""
    if isinstance(obj, (Side, OrderType, TimeInForce, RejectReason)):
        return obj.value
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# --- Event Serialization / Deserialization ---

EVENT_CLASS_MAP = {
    "ORDER_ACCEPTED": OrderAcceptedEvent,
    "ORDER_REJECTED": OrderRejectedEvent,
    "ORDER_MATCHED": OrderMatchedEvent,
    "ORDER_CANCELED": OrderCanceledEvent,
    "ORDER_FILLED": OrderFilledEvent,
    "BOOK_LEVEL_UPDATED": BookLevelUpdatedEvent,
}


def serialize_event(event: EngineEvent) -> bytes:
    """Serializes an EngineEvent dataclass directly into bytes."""
    data = {
        "event_type": event.event_type,
        "sequence_number": event.sequence_number,
        "timestamp_ns": event.timestamp_ns,
    }

    if isinstance(event, OrderAcceptedEvent):
        data.update({
            "order_id": event.order_id,
            "symbol": event.symbol,
            "side": event.side.value,
            "order_type": event.order_type.value,
            "price": event.price,
            "quantity": event.quantity,
            "time_in_force": event.time_in_force.value,
        })
    elif isinstance(event, OrderMatchedEvent):
        data.update({
            "trade_id": event.trade_id,
            "symbol": event.symbol,
            "maker_order_id": event.maker_order_id,
            "taker_order_id": event.taker_order_id,
            "maker_side": event.maker_side.value,
            "taker_side": event.taker_side.value,
            "price": event.price,
            "quantity": event.quantity,
            "quote_amount": event.quote_amount,
            "maker_remaining_qty": event.maker_remaining_qty,
            "taker_remaining_qty": event.taker_remaining_qty,
        })
    elif isinstance(event, OrderCanceledEvent):
        data.update({
            "order_id": event.order_id,
            "symbol": event.symbol,
            "reason": event.reason,
            "remaining_quantity": event.remaining_quantity,
        })
    elif isinstance(event, OrderFilledEvent):
        data.update({
            "order_id": event.order_id,
            "symbol": event.symbol,
            "filled_quantity": event.filled_quantity,
        })
    elif isinstance(event, OrderRejectedEvent):
        data.update({
            "order_id": event.order_id,
            "symbol": event.symbol,
            "reason": event.reason.value,
            "message": event.message,
        })
    elif isinstance(event, BookLevelUpdatedEvent):
        data.update({
            "symbol": event.symbol,
            "side": event.side.value,
            "price": event.price,
            "new_volume": event.new_volume,
            "order_count": event.order_count,
        })

    return orjson.dumps(data, default=_default_encoder, option=orjson.OPT_SORT_KEYS)


def deserialize_event(data: bytes) -> EngineEvent:
    """Deserializes raw bytes into a strictly typed EngineEvent instance."""
    payload: Dict[str, Any] = orjson.loads(data)
    etype = payload.get("event_type")

    if etype == "ORDER_ACCEPTED":
        return OrderAcceptedEvent(
            sequence_number=payload["sequence_number"],
            timestamp_ns=payload["timestamp_ns"],
            order_id=payload["order_id"],
            symbol=payload["symbol"],
            side=Side(payload["side"]),
            order_type=OrderType(payload["order_type"]),
            price=payload["price"],
            quantity=payload["quantity"],
            time_in_force=TimeInForce(payload["time_in_force"]),
        )
    elif etype == "ORDER_MATCHED":
        return OrderMatchedEvent(
            sequence_number=payload["sequence_number"],
            timestamp_ns=payload["timestamp_ns"],
            trade_id=payload["trade_id"],
            symbol=payload["symbol"],
            maker_order_id=payload["maker_order_id"],
            taker_order_id=payload["taker_order_id"],
            maker_side=Side(payload["maker_side"]),
            taker_side=Side(payload["taker_side"]),
            price=payload["price"],
            quantity=payload["quantity"],
            quote_amount=payload["quote_amount"],
            maker_remaining_qty=payload["maker_remaining_qty"],
            taker_remaining_qty=payload["taker_remaining_qty"],
        )
    elif etype == "ORDER_CANCELED":
        return OrderCanceledEvent(
            sequence_number=payload["sequence_number"],
            timestamp_ns=payload["timestamp_ns"],
            order_id=payload["order_id"],
            symbol=payload["symbol"],
            reason=payload["reason"],
            remaining_quantity=payload["remaining_quantity"],
        )
    elif etype == "ORDER_FILLED":
        return OrderFilledEvent(
            sequence_number=payload["sequence_number"],
            timestamp_ns=payload["timestamp_ns"],
            order_id=payload["order_id"],
            symbol=payload["symbol"],
            filled_quantity=payload["filled_quantity"],
        )
    elif etype == "ORDER_REJECTED":
        return OrderRejectedEvent(
            sequence_number=payload["sequence_number"],
            timestamp_ns=payload["timestamp_ns"],
            order_id=payload["order_id"],
            symbol=payload["symbol"],
            reason=RejectReason(payload["reason"]),
            message=payload["message"],
        )
    elif etype == "BOOK_LEVEL_UPDATED":
        return BookLevelUpdatedEvent(
            sequence_number=payload["sequence_number"],
            timestamp_ns=payload["timestamp_ns"],
            symbol=payload["symbol"],
            side=Side(payload["side"]),
            price=payload["price"],
            new_volume=payload["new_volume"],
            order_count=payload["order_count"],
        )
    else:
        raise ValueError(f"Unknown event type: {etype}")


# --- Command Serialization / Deserialization ---

def serialize_command(cmd: Union[NewOrderCommand, CancelOrderCommand]) -> bytes:
    """Serializes an inbound command into bytes."""
    if isinstance(cmd, NewOrderCommand):
        data = {
            "command_type": "NEW_ORDER",
            "order_id": cmd.order_id,
            "symbol": cmd.symbol,
            "side": cmd.side.value,
            "order_type": cmd.order_type.value,
            "price": cmd.price,
            "quantity": cmd.quantity,
            "time_in_force": cmd.time_in_force.value,
            "timestamp_ns": cmd.timestamp_ns,
        }
    elif isinstance(cmd, CancelOrderCommand):
        data = {
            "command_type": "CANCEL_ORDER",
            "order_id": cmd.order_id,
            "symbol": cmd.symbol,
            "timestamp_ns": cmd.timestamp_ns,
        }
    else:
        raise TypeError(f"Unknown command type: {type(cmd)}")

    return orjson.dumps(data, default=_default_encoder, option=orjson.OPT_SORT_KEYS)


def deserialize_command(data: bytes) -> Union[NewOrderCommand, CancelOrderCommand]:
    """Deserializes raw bytes into a NewOrderCommand or CancelOrderCommand."""
    payload: Dict[str, Any] = orjson.loads(data)
    ctype = payload.get("command_type")

    if ctype == "NEW_ORDER":
        return NewOrderCommand(
            order_id=payload["order_id"],
            symbol=payload["symbol"],
            side=Side(payload["side"]),
            order_type=OrderType(payload["order_type"]),
            price=payload["price"],
            quantity=payload["quantity"],
            time_in_force=TimeInForce(payload.get("time_in_force", "GTC")),
            timestamp_ns=payload.get("timestamp_ns", 0),
        )
    elif ctype == "CANCEL_ORDER":
        return CancelOrderCommand(
            order_id=payload["order_id"],
            symbol=payload["symbol"],
            timestamp_ns=payload.get("timestamp_ns", 0),
        )
    else:
        raise ValueError(f"Unknown command type: {ctype}")


# --- Snapshot Serialization / Deserialization ---

def serialize_snapshot(snapshot: dict) -> bytes:
    """Serializes OrderBook snapshot dictionary to bytes."""
    return orjson.dumps(snapshot, default=_default_encoder)


def deserialize_snapshot(data: bytes) -> dict:
    """Deserializes OrderBook snapshot from bytes."""
    return orjson.loads(data)
