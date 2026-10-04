"""
ChronosEngine - Trade Execution Model.
Represents an atomic transaction between a passive (Maker) order and an aggressive (Taker) order.
"""

from dataclasses import dataclass
from core.models.types import Side, from_fixed_point, fixed_to_str, calculate_quote_amount

@dataclass(slots=True)
class Trade:
    trade_id: int
    maker_order_id: str
    taker_order_id: str
    symbol: str
    price: int                  # Fixed-point 10^8
    quantity: int               # Fixed-point 10^8
    quote_amount: int           # Fixed-point 10^8 (price * quantity // 10^8)
    maker_side: Side
    taker_side: Side
    sequence_number: int
    timestamp_ns: int

    @classmethod
    def create(
        cls,
        trade_id: int,
        maker_order_id: str,
        taker_order_id: str,
        symbol: str,
        price: int,
        quantity: int,
        maker_side: Side,
        taker_side: Side,
        sequence_number: int,
        timestamp_ns: int,
    ) -> "Trade":
        quote_amt = calculate_quote_amount(price, quantity)
        return cls(
            trade_id=trade_id,
            maker_order_id=maker_order_id,
            taker_order_id=taker_order_id,
            symbol=symbol,
            price=price,
            quantity=quantity,
            quote_amount=quote_amt,
            maker_side=maker_side,
            taker_side=taker_side,
            sequence_number=sequence_number,
            timestamp_ns=timestamp_ns,
        )

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "maker_order_id": self.maker_order_id,
            "taker_order_id": self.taker_order_id,
            "symbol": self.symbol,
            "price": self.price,
            "price_str": fixed_to_str(self.price),
            "price_float": from_fixed_point(self.price),
            "quantity": self.quantity,
            "quantity_str": fixed_to_str(self.quantity),
            "quantity_float": from_fixed_point(self.quantity),
            "quote_amount": self.quote_amount,
            "quote_amount_float": from_fixed_point(self.quote_amount),
            "maker_side": self.maker_side.value,
            "taker_side": self.taker_side.value,
            "sequence_number": self.sequence_number,
            "timestamp_ns": self.timestamp_ns,
        }
