"""
ChronosEngine - Quantitative Market Maker (Avellaneda-Stoikov Model).
Provides passive dual-sided liquidity with dynamic inventory risk management:
- Calculates reservation price: r(s, q) = s - q * gamma * sigma^2 * s
- Quotes multi-level ladder of bids and asks around r(s, q).
- Skews quotes to shed inventory when long and attract inventory when short.
- Strictly cancels all stale quotes on every tick before posting new ladders.
- Guarantees orders never rest further than 10 ticks away from current mid-price.
"""

import asyncio
import uuid
from typing import List, Dict, Any, Optional, Set

from simulator.client import ExchangeClient
from simulator.price_model import JumpDiffusionPriceModel


class AvellanedaStoikovMarketMaker:
    """
    High-Frequency Market Maker with inventory skewing and strict cancellation.
    """

    def __init__(
        self,
        client: ExchangeClient,
        price_model: JumpDiffusionPriceModel,
        symbol: str = "BTC-USDT",
        base_spread: float = 4.0,           # Minimum spread in quote currency
        levels: int = 5,                    # Number of ladder price levels
        level_spacing: float = 2.0,         # Distance between ladder levels (tick size)
        order_quantity: float = 0.5,        # Base quantity per level
        gamma: float = 0.005,               # Risk aversion coefficient
        max_inventory: float = 15.0,        # Hard inventory risk limit
    ) -> None:
        self.client: ExchangeClient = client
        self.price_model: JumpDiffusionPriceModel = price_model
        self.symbol: str = symbol
        self.base_spread: float = base_spread
        self.levels: int = levels
        self.level_spacing: float = level_spacing
        self.order_quantity: float = order_quantity
        self.gamma: float = gamma
        self.max_inventory: float = max_inventory

        # Current state
        self.inventory: float = 0.0          # Base asset inventory (e.g. BTC)
        self.quote_balance: float = 1000000.0  # Quote balance (USDT)
        self.active_order_ids: Set[str] = set()
        self._running: bool = False

    def compute_reservation_price(self, mid_price: float) -> float:
        """
        Computes Avellaneda-Stoikov reservation price:
          r(s, q) = s - (q * gamma * sigma^2 * s)
        """
        sigma = self.price_model.volatility
        skew = self.inventory * self.gamma * (sigma ** 2) * mid_price
        return mid_price - skew

    async def cancel_stale_orders(self) -> None:
        """
        Strictly cancels all active maker quotes before refreshing the ladder.
        Prevents orphan resting orders from lingering on the book.
        """
        # 1. First trigger bulk cancellation of all mm_ orders on exchange
        try:
            await self.client.cancel_all_orders(self.symbol, prefix="mm_")
        except Exception:
            pass

        # 2. Defensively cancel specifically tracked IDs
        if self.active_order_ids:
            to_cancel = list(self.active_order_ids)
            self.active_order_ids.clear()
            cancel_tasks = [
                self.client.cancel_order(oid, self.symbol)
                for oid in to_cancel
            ]
            await asyncio.gather(*cancel_tasks, return_exceptions=True)

    async def quote_ladder(self) -> List[Dict[str, Any]]:
        """
        Computes and places refreshed bid and ask ladders.
        Obligatorily cancels all prior quotes before inserting new orders.
        Guarantees no passive orders rest beyond 10 ticks from the current mid-price.
        """
        # 1. Mandatory strict cancellation of all prior active quotes
        await self.cancel_stale_orders()

        # 2. Get latest stochastic mid-price and reservation price
        mid_price = self.price_model.next_price()
        res_price = self.compute_reservation_price(mid_price)

        half_spread = max(0.5, self.base_spread / 2.0)
        max_tick_distance = 10 * self.level_spacing  # Max 10 ticks away from mid-price
        new_orders = []

        # 3. Post Bid Ladder (Within inventory limit and <= 10 ticks from mid-price)
        if self.inventory < self.max_inventory:
            for k in range(self.levels):
                bid_px = round(res_price - half_spread - (k * self.level_spacing), 2)
                # Ensure strictly positive and within 10 ticks of mid-price
                if bid_px > 0 and (mid_price - bid_px) <= max_tick_distance:
                    oid = f"mm_bid_{uuid.uuid4().hex[:8]}"
                    new_orders.append((oid, "BUY", bid_px, self.order_quantity))

        # 4. Post Ask Ladder (Within inventory limit and <= 10 ticks from mid-price)
        if self.inventory > -self.max_inventory:
            for k in range(self.levels):
                ask_px = round(res_price + half_spread + (k * self.level_spacing), 2)
                # Ensure higher than best bid and within 10 ticks of mid-price
                if ask_px > (res_price - half_spread) and (ask_px - mid_price) <= max_tick_distance:
                    oid = f"mm_ask_{uuid.uuid4().hex[:8]}"
                    new_orders.append((oid, "SELL", ask_px, self.order_quantity))

        # 5. Track IDs for mandatory cancellation on the next tick
        for oid, _, _, _ in new_orders:
            self.active_order_ids.add(oid)

        # 6. Dispatch orders concurrently
        place_tasks = [
            self.client.place_order(
                symbol=self.symbol,
                side=side,
                order_type="LIMIT",
                price=px,
                quantity=qty,
                time_in_force="GTC",
                order_id=oid,
            )
            for oid, side, px, qty in new_orders
        ]
        results = await asyncio.gather(*place_tasks, return_exceptions=True)

        # Clean up orders that already terminated (filled / rejected)
        for (oid, _, _, _), res in zip(new_orders, results):
            if isinstance(res, dict) and res.get("status") in ("FILLED", "REJECTED", "CANCELED"):
                self.active_order_ids.discard(oid)
            elif isinstance(res, Exception):
                self.active_order_ids.discard(oid)

        return [r for r in results if isinstance(r, dict)]

    def record_fill(self, side: str, quantity: float, price: float) -> None:
        """Updates internal inventory and quote balance upon trade execution."""
        if side.upper() == "BUY":
            # Maker was buying -> inventory increased, cash decreased
            self.inventory += quantity
            self.quote_balance -= (quantity * price)
        else:
            # Maker was selling -> inventory decreased, cash increased
            self.inventory -= quantity
            self.quote_balance += (quantity * price)

    async def run_loop(self, interval_sec: float = 0.1) -> None:
        """Continuous high-frequency quoting loop with guaranteed cleanup."""
        self._running = True
        try:
            while self._running:
                try:
                    await self.quote_ladder()
                except Exception as e:
                    print(f"[MarketMaker] Quoting error: {e}")
                await asyncio.sleep(interval_sec)
        finally:
            # Ensure no orphan orders remain on book when loop stops
            await self.cancel_stale_orders()

    def stop(self) -> None:
        self._running = False
