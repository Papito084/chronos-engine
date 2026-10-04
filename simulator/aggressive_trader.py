"""
ChronosEngine - Aggressive Liquidity Takers with Slippage Control.
Simulates realistic taker order flow with institutional execution protection:
- Order sizes sampled from a heavy-tailed Power-Law (Pareto) distribution.
- Strict 0.2% Maximum Slippage Guard relative to current mid-price.
- Converts aggressive / market orders into Immediate-Or-Cancel (IOC) crossing limit orders
  anchored at the top-of-book (best_bid / best_ask) to prevent sweeping phantom or stale depth levels.
"""

import asyncio
import random
import uuid
from typing import Dict, Any, List, Optional
import numpy as np

from simulator.client import ExchangeClient


class AggressiveTrader:
    """
    Stochastic taker with institutional 0.2% slippage protection.
    """

    def __init__(
        self,
        client: ExchangeClient,
        symbol: str = "BTC-USDT",
        min_qty: float = 0.05,
        max_qty: float = 4.0,
        pareto_alpha: float = 1.8,
        market_order_ratio: float = 0.60,
        max_slippage_pct: float = 0.002,  # 0.2% max allowed deviation from mid-price
    ) -> None:
        self.client: ExchangeClient = client
        self.symbol: str = symbol
        self.min_qty: float = min_qty
        self.max_qty: float = max_qty
        self.pareto_alpha: float = pareto_alpha
        self.market_order_ratio: float = market_order_ratio
        self.max_slippage_pct: float = max_slippage_pct
        self._running: bool = False

        self.total_orders_sent: int = 0
        self.total_volume_traded: float = 0.0

    def sample_order_quantity(self) -> float:
        """Draws order size from a truncated Pareto (Power-Law) distribution."""
        u = random.random()
        # Pareto quantile function: Q = min_qty * (1 - u)^(-1 / alpha)
        raw_qty = self.min_qty * ((1.0 - u) ** (-1.0 / self.pareto_alpha))
        clipped_qty = min(self.max_qty, max(self.min_qty, raw_qty))
        return round(clipped_qty, 3)

    async def execute_trade(self) -> Dict[str, Any]:
        """
        Fires an aggressive trade protected by strict 0.2% slippage limits.
        Converts execution into IOC limit orders at top-of-book so phantom or stale
        resting levels are never swept.
        """
        # 1. Inspect live order book for BBO and reference mid-price
        book = await self.client.get_order_book(self.symbol, depth=5)
        best_bid = book.get("best_bid")
        best_ask = book.get("best_ask")

        if best_bid is not None and best_ask is not None:
            mid_price = (best_bid + best_ask) / 2.0
        elif best_bid is not None:
            mid_price = best_bid
        elif best_ask is not None:
            mid_price = best_ask
        else:
            # Book completely dry, skip aggression
            return {"status": "NO_LIQUIDITY"}

        side = "BUY" if random.random() < 0.5 else "SELL"
        qty = self.sample_order_quantity()
        oid = f"taker_{uuid.uuid4().hex[:8]}"

        if side == "BUY":
            if not best_ask:
                return {"status": "NO_ASK_LIQUIDITY"}

            # Upper slippage bound: mid_price * (1 + 0.2%)
            max_buy_price = round(mid_price * (1.0 + self.max_slippage_pct), 2)
            if best_ask > max_buy_price:
                # Top ask violates 0.2% slippage; avoid sweeping wide levels
                return {"status": "SLIPPAGE_EXCEEDED"}

            # Aggress at best_ask with minimal tick crossing, capped at max_buy_price
            limit_px = min(max_buy_price, round(best_ask + random.choice([0.0, 0.5, 1.0]), 2))
            res = await self.client.place_order(
                symbol=self.symbol,
                side="BUY",
                order_type="LIMIT",
                price=limit_px,
                quantity=qty,
                time_in_force="IOC",
                order_id=oid,
            )
        else:
            if not best_bid:
                return {"status": "NO_BID_LIQUIDITY"}

            # Lower slippage bound: mid_price * (1 - 0.2%)
            min_sell_price = round(mid_price * (1.0 - self.max_slippage_pct), 2)
            if best_bid < min_sell_price:
                # Top bid violates 0.2% slippage; avoid sweeping wide levels
                return {"status": "SLIPPAGE_EXCEEDED"}

            # Aggress at best_bid with minimal tick crossing, floored at min_sell_price
            limit_px = max(min_sell_price, round(best_bid - random.choice([0.0, 0.5, 1.0]), 2))
            res = await self.client.place_order(
                symbol=self.symbol,
                side="SELL",
                order_type="LIMIT",
                price=limit_px,
                quantity=qty,
                time_in_force="IOC",
                order_id=oid,
            )

        self.total_orders_sent += 1
        self.total_volume_traded += qty
        return res

    async def run_loop(self, orders_per_sec: float = 100.0) -> None:
        """Runs continuous aggressive order generation at target rate."""
        self._running = True
        interval = 1.0 / orders_per_sec if orders_per_sec > 0 else 0.01

        while self._running:
            try:
                await self.execute_trade()
            except Exception as e:
                print(f"[AggressiveTrader] Execution error: {e}")
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._running = False
