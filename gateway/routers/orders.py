"""
ChronosEngine - REST Order Submission & Cancellation Router.
Translates incoming HTTP payloads into fixed-point NewOrderCommand / CancelOrderCommand
and returns deterministic matching results.
"""

import uuid
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.models.types import (
    Side,
    OrderType,
    TimeInForce,
    to_fixed_point,
    from_fixed_point,
    fixed_to_str,
)
from core.models.events import (
    NewOrderCommand,
    CancelOrderCommand,
    OrderAcceptedEvent,
    OrderRejectedEvent,
    OrderMatchedEvent,
    OrderFilledEvent,
    OrderCanceledEvent,
)


class OrderCreateRequest(BaseModel):
    symbol: str = Field(default="BTC-USDT", description="Trading pair symbol")
    side: str = Field(..., description="Order side: 'BUY' or 'SELL'")
    order_type: str = Field(default="LIMIT", description="Order type: 'LIMIT' or 'MARKET'")
    price: float = Field(default=0.0, ge=0.0, description="Limit price in quote currency")
    quantity: float = Field(..., gt=0.0, description="Order quantity in base currency")
    time_in_force: str = Field(default="GTC", description="'GTC', 'IOC', or 'FOK'")
    order_id: Optional[str] = Field(default=None, description="Client order ID")


class OrderCancelRequest(BaseModel):
    order_id: str
    symbol: str = "BTC-USDT"


def create_orders_router(bridge) -> APIRouter:
    router = APIRouter(prefix="/api/v1/orders", tags=["Orders"])

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def place_order(req: OrderCreateRequest):
        # 1. Parse Enums & validations
        try:
            side_enum = Side(req.side.upper())
            type_enum = OrderType(req.order_type.upper())
            tif_enum = TimeInForce(req.time_in_force.upper())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid enum parameter: {e}")

        # 2. Convert to fixed-point 10^8 integers
        price_fixed = to_fixed_point(str(req.price)) if type_enum == OrderType.LIMIT else 0
        qty_fixed = to_fixed_point(str(req.quantity))

        order_id = req.order_id or f"ord_{uuid.uuid4().hex[:12]}"

        # 3. Create command and dispatch to matching engine
        cmd = NewOrderCommand(
            order_id=order_id,
            symbol=req.symbol,
            side=side_enum,
            order_type=type_enum,
            price=price_fixed,
            quantity=qty_fixed,
            time_in_force=tif_enum,
        )

        events = bridge.execute_command(cmd)

        # 4. Check for rejection
        rejections = [e for e in events if isinstance(e, OrderRejectedEvent)]
        if rejections:
            rej = rejections[0]
            raise HTTPException(
                status_code=400,
                detail={
                    "status": "REJECTED",
                    "reason": rej.reason.value,
                    "message": rej.message,
                },
            )

        # 5. Extract executions and final status
        matches = [e for e in events if isinstance(e, OrderMatchedEvent)]
        fills = [e for e in events if isinstance(e, OrderFilledEvent) and e.order_id == order_id]
        cancels = [e for e in events if isinstance(e, OrderCanceledEvent) and e.order_id == order_id]

        if fills:
            final_status = "FILLED"
        elif cancels:
            final_status = "CANCELED"
        elif matches:
            final_status = "PARTIALLY_FILLED"
        else:
            final_status = "NEW"

        trades_summary = []
        for m in matches:
            trades_summary.append({
                "trade_id": m.trade_id,
                "price": from_fixed_point(m.price),
                "quantity": from_fixed_point(m.quantity),
                "quote_amount": from_fixed_point(m.quote_amount),
                "maker_order_id": m.maker_order_id,
                "maker_side": m.maker_side.value,
            })

        return {
            "order_id": order_id,
            "symbol": req.symbol,
            "side": req.side.upper(),
            "order_type": req.order_type.upper(),
            "price": req.price,
            "quantity": req.quantity,
            "time_in_force": req.time_in_force.upper(),
            "status": final_status,
            "trades": trades_summary,
            "event_count": len(events),
        }

    @router.delete("")
    async def cancel_orders_bulk(
        symbol: str = Query("BTC-USDT", description="Symbol to cancel orders for"),
        prefix: Optional[str] = Query(None, description="Cancel orders matching this ID prefix"),
    ):
        book = bridge.engine.books.get(symbol)
        if not book:
            return {"symbol": symbol, "canceled_count": 0}

        target_ids = [
            oid for oid in list(book.orders.keys())
            if prefix is None or oid.startswith(prefix)
        ]

        canceled = 0
        for oid in target_ids:
            cmd = CancelOrderCommand(order_id=oid, symbol=symbol)
            events = bridge.execute_command(cmd)
            if any(isinstance(e, OrderCanceledEvent) for e in events):
                canceled += 1

        return {"symbol": symbol, "canceled_count": canceled, "total_target": len(target_ids)}

    @router.delete("/{order_id}")
    async def cancel_order(order_id: str, symbol: str = Query("BTC-USDT")):
        cmd = CancelOrderCommand(order_id=order_id, symbol=symbol)
        events = bridge.execute_command(cmd)

        rejections = [e for e in events if isinstance(e, OrderRejectedEvent)]
        if rejections:
            raise HTTPException(status_code=404, detail=rejections[0].message)

        cancels = [e for e in events if isinstance(e, OrderCanceledEvent)]
        if cancels:
            c = cancels[0]
            return {
                "order_id": c.order_id,
                "symbol": c.symbol,
                "status": "CANCELED",
                "remaining_quantity": from_fixed_point(c.remaining_quantity),
                "reason": c.reason,
            }

        return {"order_id": order_id, "status": "UNKNOWN"}

    @router.get("/{order_id}")
    async def get_order_status(order_id: str, symbol: str = Query("BTC-USDT")):
        book = bridge.engine.books.get(symbol)
        if not book:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

        order = book.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail=f"Active order {order_id} not found in book")

        return order.to_dict()

    return router
