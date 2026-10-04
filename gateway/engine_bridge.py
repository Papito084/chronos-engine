"""
ChronosEngine - Zero-Copy Non-Blocking Engine-Gateway Bridge.
Decouples the single-threaded matching core from network I/O and web consumers:
- Intercepts EngineEvents via O(1) in-memory hooks.
- Routes trade ticks immediately to WebSocket broadcast queues and ClickHouse ingestor.
- Buffers L2 level updates into the 50ms throttle ring.
- Runs 1-second telemetry broadcast loop.
"""

import asyncio
import time
from typing import Optional, List, Dict, Any

from core.models.types import from_fixed_point, fixed_to_str
from core.models.events import (
    EngineEvent,
    OrderMatchedEvent,
    BookLevelUpdatedEvent,
    OrderAcceptedEvent,
    OrderCanceledEvent,
    NewOrderCommand,
    CancelOrderCommand,
)
from core.engine.matching_engine import MatchingEngine
from gateway.connection_manager import ConnectionManager
from gateway.metrics_collector import MetricsCollector
from persistence.clickhouse_ingestor import ClickHouseIngestor


class EngineBridge:
    """
    Connects the deterministic core MatchingEngine to Gateway WebSockets,
    Telemetry collectors, and ClickHouse persistence.
    """

    def __init__(
        self,
        engine: MatchingEngine,
        connection_manager: ConnectionManager,
        metrics_collector: MetricsCollector,
        ingestor: Optional[ClickHouseIngestor] = None,
    ) -> None:
        self.engine: MatchingEngine = engine
        self.ws_manager: ConnectionManager = connection_manager
        self.metrics: MetricsCollector = metrics_collector
        self.ingestor: Optional[ClickHouseIngestor] = ingestor

        self._trade_queue: Optional[asyncio.Queue] = None
        self._running: bool = False
        self._trade_broadcaster_task: Optional[asyncio.Task] = None
        self._telemetry_task: Optional[asyncio.Task] = None

        # Register event hook on MatchingEngine
        self.engine.add_event_listener(self.on_engine_event)

    def on_engine_event(self, event: EngineEvent) -> None:
        """
        Synchronous, zero-blocking event callback invoked by the MatchingEngine.
        Takes <1 microsecond to enqueue/buffer.
        """
        if isinstance(event, OrderMatchedEvent):
            self.metrics.record_trade()
            # Push to async queue without blocking
            if self._trade_queue is not None:
                try:
                    self._trade_queue.put_nowait(event)
                except (asyncio.QueueFull, Exception):
                    pass

        elif isinstance(event, BookLevelUpdatedEvent):
            # Buffer into 50ms throttled L2 diff bucket
            self.ws_manager.buffer_l2_update(
                symbol=event.symbol,
                side=event.side.value,
                price=event.price,
                volume=event.new_volume,
                order_count=event.order_count,
            )

    def execute_command(self, cmd: Any) -> List[EngineEvent]:
        """
        Executes a command on the matching engine while instrumenting nanosecond latency.
        """
        t_start = time.perf_counter_ns()
        events = self.engine.process_command(cmd)
        t_end = time.perf_counter_ns()

        self.metrics.record_latency(t_end - t_start)

        # Update active orders count
        book = self.engine.books.get(cmd.symbol)
        if book:
            self.metrics.update_active_orders(len(book.orders))

        return events

    async def _trade_broadcaster_loop(self) -> None:
        """Asynchronously drains the trade queue and broadcasts to WebSocket clients & Ingestor."""
        while self._running:
            try:
                event: OrderMatchedEvent = await self._trade_queue.get()
                trade_payload = {
                    "channel": "trades",
                    "type": "trade",
                    "trade_id": event.trade_id,
                    "symbol": event.symbol,
                    "price": from_fixed_point(event.price),
                    "price_str": fixed_to_str(event.price),
                    "price_fixed": event.price,
                    "quantity": from_fixed_point(event.quantity),
                    "quantity_str": fixed_to_str(event.quantity),
                    "quantity_fixed": event.quantity,
                    "quote_amount": from_fixed_point(event.quote_amount),
                    "quote_amount_fixed": event.quote_amount,
                    "maker_side": event.maker_side.value,
                    "taker_side": event.taker_side.value,
                    "sequence_number": event.sequence_number,
                    "timestamp_ns": event.timestamp_ns,
                    "timestamp_ms": int(event.timestamp_ns // 1_000_000),
                }

                # 1. Forward to WebSockets
                await self.ws_manager.broadcast_to_channel("trades", trade_payload, symbol=event.symbol)

                # 2. Forward to ClickHouse Ingestor if configured
                if self.ingestor:
                    await self.ingestor.add_event(event)

                self._trade_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[EngineBridge] Trade broadcast error: {e}")
                await asyncio.sleep(0.05)

    async def _telemetry_broadcast_loop(self) -> None:
        """Broadcasts system health and latency distributions once per second."""
        while self._running:
            await asyncio.sleep(1.0)
            try:
                snapshot = self.metrics.get_snapshot()
                msg = {
                    "channel": "telemetry",
                    "data": snapshot,
                }
                await self.ws_manager.broadcast_to_channel("telemetry", msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[EngineBridge] Telemetry broadcast error: {e}")

    async def start(self) -> None:
        """Starts background worker tasks."""
        if not self._running:
            self._running = True
            self._trade_queue = asyncio.Queue(maxsize=100000)
            self._trade_broadcaster_task = asyncio.create_task(self._trade_broadcaster_loop())
            self._telemetry_task = asyncio.create_task(self._telemetry_broadcast_loop())

    async def stop(self) -> None:
        """Gracefully shuts down bridge loops."""
        self._running = False
        for t in (self._trade_broadcaster_task, self._telemetry_task):
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        self._trade_broadcaster_task = None
        self._telemetry_task = None
