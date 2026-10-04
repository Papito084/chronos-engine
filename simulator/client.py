"""
ChronosEngine - Unified Exchange Client Abstraction.
Allows bots to operate either:
  1. Direct-Engine Mode: In-memory direct matching without network overhead (benchmarking).
  2. Network-Gateway Mode: HTTP REST calls against the real gateway (Docker / distributed sim).
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
import httpx

from core.models.types import (
    Side,
    OrderType,
    TimeInForce,
    to_fixed_point,
    from_fixed_point,
)
from core.models.events import (
    NewOrderCommand,
    CancelOrderCommand,
    OrderMatchedEvent,
    OrderFilledEvent,
    OrderCanceledEvent,
    OrderRejectedEvent,
)


class ExchangeClient(ABC):
    """Abstract interface for bot interaction with ChronosEngine."""

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
        time_in_force: str = "GTC",
        order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str = "BTC-USDT") -> Dict[str, Any]:
        pass

    @abstractmethod
    async def cancel_all_orders(self, symbol: str = "BTC-USDT", prefix: Optional[str] = None) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_order_book(self, symbol: str = "BTC-USDT", depth: int = 25) -> Dict[str, Any]:
        pass


class DirectExchangeClient(ExchangeClient):
    """
    Direct in-memory exchange client for zero-overhead quantitative simulation.
    Dispatches directly into the engine bridge.
    """

    def __init__(self, bridge) -> None:
        self.bridge = bridge
        self.engine = bridge.engine

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
        time_in_force: str = "GTC",
        order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        import uuid
        oid = order_id or f"direct_{uuid.uuid4().hex[:10]}"
        side_enum = Side(side.upper())
        type_enum = OrderType(order_type.upper())
        tif_enum = TimeInForce(time_in_force.upper())

        px_fixed = to_fixed_point(str(price)) if type_enum == OrderType.LIMIT else 0
        qty_fixed = to_fixed_point(str(quantity))

        cmd = NewOrderCommand(
            order_id=oid,
            symbol=symbol,
            side=side_enum,
            order_type=type_enum,
            price=px_fixed,
            quantity=qty_fixed,
            time_in_force=tif_enum,
        )

        events = self.bridge.execute_command(cmd)

        matches = [e for e in events if isinstance(e, OrderMatchedEvent)]
        fills = [e for e in events if isinstance(e, OrderFilledEvent) and e.order_id == oid]
        cancels = [e for e in events if isinstance(e, OrderCanceledEvent) and e.order_id == oid]
        rejections = [e for e in events if isinstance(e, OrderRejectedEvent)]

        if rejections:
            status = "REJECTED"
        elif fills:
            status = "FILLED"
        elif cancels:
            status = "CANCELED"
        elif matches:
            status = "PARTIALLY_FILLED"
        else:
            status = "NEW"

        return {
            "order_id": oid,
            "status": status,
            "trades": [
                {
                    "trade_id": m.trade_id,
                    "price": from_fixed_point(m.price),
                    "quantity": from_fixed_point(m.quantity),
                }
                for m in matches
            ],
        }

    async def cancel_order(self, order_id: str, symbol: str = "BTC-USDT") -> Dict[str, Any]:
        cmd = CancelOrderCommand(order_id=order_id, symbol=symbol)
        events = self.bridge.execute_command(cmd)
        cancels = [e for e in events if isinstance(e, OrderCanceledEvent)]
        if cancels:
            return {"order_id": order_id, "status": "CANCELED"}
        return {"order_id": order_id, "status": "NOT_FOUND"}

    async def cancel_all_orders(self, symbol: str = "BTC-USDT", prefix: Optional[str] = None) -> Dict[str, Any]:
        book = self.engine.books.get(symbol)
        if not book:
            return {"symbol": symbol, "canceled_count": 0}
        target_ids = [
            oid for oid in list(book.orders.keys())
            if prefix is None or oid.startswith(prefix)
        ]
        canceled = 0
        for oid in target_ids:
            cmd = CancelOrderCommand(order_id=oid, symbol=symbol)
            events = self.bridge.execute_command(cmd)
            if any(isinstance(e, OrderCanceledEvent) for e in events):
                canceled += 1
        return {"symbol": symbol, "canceled_count": canceled, "total_target": len(target_ids)}

    async def get_order_book(self, symbol: str = "BTC-USDT", depth: int = 25) -> Dict[str, Any]:
        book = self.engine.books.get(symbol)
        if not book:
            return {"symbol": symbol, "bids": [], "asks": []}
        l2 = book.get_l2_snapshot(depth=depth)
        return {
            "symbol": symbol,
            "bids": [[from_fixed_point(p), from_fixed_point(v), c] for p, v, c in l2["bids"]],
            "asks": [[from_fixed_point(p), from_fixed_point(v), c] for p, v, c in l2["asks"]],
            "best_bid": from_fixed_point(l2["best_bid"]) if l2["best_bid"] is not None else None,
            "best_ask": from_fixed_point(l2["best_ask"]) if l2["best_ask"] is not None else None,
        }


class NetworkExchangeClient(ExchangeClient):
    """
    HTTP REST exchange client for distributed container-to-container simulation.
    """

    def __init__(self, base_url: str = "http://localhost:8000", client: Optional[httpx.AsyncClient] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._external_client = client
        self._client: Optional[httpx.AsyncClient] = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=5.0)
        return self._client

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
        time_in_force: str = "GTC",
        order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        c = await self._get_client()
        payload = {
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "price": price,
            "quantity": quantity,
            "time_in_force": time_in_force,
        }
        if order_id:
            payload["order_id"] = order_id

        res = await c.post("/api/v1/orders", json=payload)
        if res.status_code in (200, 201):
            return res.json()
        return {"status": "ERROR", "status_code": res.status_code, "detail": res.text}

    async def cancel_order(self, order_id: str, symbol: str = "BTC-USDT") -> Dict[str, Any]:
        c = await self._get_client()
        res = await c.delete(f"/api/v1/orders/{order_id}?symbol={symbol}")
        if res.status_code == 200:
            return res.json()
        return {"status": "ERROR", "status_code": res.status_code}

    async def cancel_all_orders(self, symbol: str = "BTC-USDT", prefix: Optional[str] = None) -> Dict[str, Any]:
        c = await self._get_client()
        url = f"/api/v1/orders?symbol={symbol}"
        if prefix:
            url += f"&prefix={prefix}"
        res = await c.delete(url)
        if res.status_code == 200:
            return res.json()
        return {"symbol": symbol, "canceled_count": 0}

    async def get_order_book(self, symbol: str = "BTC-USDT", depth: int = 25) -> Dict[str, Any]:
        c = await self._get_client()
        res = await c.get(f"/api/v1/market/book?symbol={symbol}&depth={depth}")
        if res.status_code == 200:
            return res.json()
        return {"symbol": symbol, "bids": [], "asks": []}

    async def close(self) -> None:
        if self._client and not self._external_client:
            await self._client.aclose()
            self._client = None
