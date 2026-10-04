"""
ChronosEngine - Fixed-Point Numeric Types and Financial Enums.
Designed for ultra-low latency, deterministic matching, and zero IEEE 754 precision loss.
"""

from enum import Enum
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Union

# 8 decimal places of precision (10^8 units per base/quote unit, e.g. satoshi equivalent)
PRICE_SCALE: int = 100_000_000
QTY_SCALE: int = 100_000_000
PRICE_DECIMALS: int = 8
QTY_DECIMALS: int = 8

class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self == Side.BUY else Side.BUY


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class TimeInForce(str, Enum):
    GTC = "GTC"  # Good 'Til Canceled (rests on book)
    IOC = "IOC"  # Immediate-Or-Cancel (fill what is possible immediately, cancel remainder)
    FOK = "FOK"  # Fill-Or-Kill (must fill 100% immediately, or kill entire order)


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


class RejectReason(str, Enum):
    NONE = "NONE"
    INVALID_PRICE = "INVALID_PRICE"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    DUPLICATE_ORDER_ID = "DUPLICATE_ORDER_ID"
    FOK_CANNOT_BE_FILLED = "FOK_CANNOT_BE_FILLED"
    MARKET_ORDER_NO_LIQUIDITY = "MARKET_ORDER_NO_LIQUIDITY"


def to_fixed_point(value: Union[int, float, str, Decimal], scale: int = PRICE_SCALE) -> int:
    """Convert any numerical input into integer fixed-point representation with Bankers Rounding."""
    if isinstance(value, int):
        return value * scale
    if isinstance(value, float):
        value = str(value)
    d = Decimal(str(value))
    return int((d * scale).to_integral_value(rounding=ROUND_HALF_EVEN))


def from_fixed_point(value: int, scale: int = PRICE_SCALE) -> float:
    """Convert integer fixed-point value back to float for read-only / display purposes."""
    return value / scale


def fixed_to_str(value: int, scale: int = PRICE_SCALE, decimals: int = 8) -> str:
    """Deterministic string formatting for fixed-point integer."""
    sign = "-" if value < 0 else ""
    abs_val = abs(value)
    integer_part = abs_val // scale
    frac_part = abs_val % scale
    return f"{sign}{integer_part}.{frac_part:0{decimals}d}"


def calculate_quote_amount(price_fixed: int, qty_fixed: int) -> int:
    """
    Calculate quote amount (price * quantity) in fixed-point (8 decimals).
    (price * qty) // 10^8
    """
    return (price_fixed * qty_fixed) // PRICE_SCALE
