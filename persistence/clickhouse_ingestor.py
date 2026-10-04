"""
ChronosEngine - High-Throughput ClickHouse Micro-Batch Ingestor.
Consumes market execution events, aggregates them into in-memory buffers,
and flushes batches to ClickHouse using a dual-trigger strategy:
  1. Volume Threshold (e.g. 5,000 trades)
  2. Time Interval Threshold (e.g. 250 ms)
Includes exponential backoff retry for transient network/broker anomalies.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import clickhouse_connect
from clickhouse_connect.driver.client import Client

from core.models.events import OrderMatchedEvent, EngineEvent
from core.models.trade import Trade
from core.serialization import deserialize_event


class ClickHouseIngestor:
    """
    Micro-batching ingestor for ClickHouse OLAP storage.
    Buffers trades in memory and issues bulk vector inserts.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8123,
        database: str = "chronos",
        username: str = "default",
        password: str = "",
        batch_size: int = 5000,
        flush_interval_ms: int = 250,
        max_retries: int = 5,
        base_backoff_sec: float = 0.1,
    ) -> None:
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.batch_size = batch_size
        self.flush_interval_sec = flush_interval_ms / 1000.0
        self.max_retries = max_retries
        self.base_backoff_sec = base_backoff_sec

        self._trade_buffer: List[List[Any]] = []
        self._last_flush_time = time.monotonic()
        self._client: Optional[Client] = None
        self._running = False
        self._flush_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # Telemetry
        self.total_trades_ingested = 0
        self.total_batches_flushed = 0
        self.total_flush_time_ms = 0.0

    def connect(self) -> Client:
        """Establishes connection to ClickHouse server."""
        if self._client is None:
            self._client = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                database=self.database,
                username=self.username,
                password=self.password,
                connect_timeout=5,
                send_receive_timeout=15,
            )
        return self._client

    def close(self) -> None:
        """Closes ClickHouse connection."""
        if self._client:
            self._client.close()
            self._client = None

    def transform_match_event(self, event: OrderMatchedEvent) -> List[Any]:
        """Maps an OrderMatchedEvent into a ClickHouse trades table row."""
        # Convert nanosecond timestamp to datetime in UTC
        ts_sec = event.timestamp_ns / 1_000_000_000.0
        dt = datetime.fromtimestamp(ts_sec, tz=timezone.utc)

        return [
            event.trade_id,
            event.symbol,
            event.maker_order_id,
            event.taker_order_id,
            event.price,
            event.quantity,
            event.quote_amount,
            event.taker_side.value,
            dt,
            event.sequence_number,
        ]

    def transform_trade(self, trade: Trade) -> List[Any]:
        """Maps a Trade model into a ClickHouse trades table row."""
        ts_sec = trade.timestamp_ns / 1_000_000_000.0
        dt = datetime.fromtimestamp(ts_sec, tz=timezone.utc)

        return [
            trade.trade_id,
            trade.symbol,
            trade.maker_order_id,
            trade.taker_order_id,
            trade.price,
            trade.quantity,
            trade.quote_amount,
            trade.taker_side.value,
            dt,
            trade.sequence_number,
        ]

    async def add_event(self, event: EngineEvent) -> None:
        """Enqueues an event into the micro-batch buffer if it represents a match/trade."""
        if isinstance(event, OrderMatchedEvent):
            row = self.transform_match_event(event)
            async with self._lock:
                self._trade_buffer.append(row)
                if len(self._trade_buffer) >= self.batch_size:
                    await self._flush_buffer_locked()

    async def add_trade(self, trade: Trade) -> None:
        """Enqueues a Trade model directly."""
        row = self.transform_trade(trade)
        async with self._lock:
            self._trade_buffer.append(row)
            if len(self._trade_buffer) >= self.batch_size:
                await self._flush_buffer_locked()

    async def flush(self) -> int:
        """Explicitly flushes the trade buffer."""
        async with self._lock:
            return await self._flush_buffer_locked()

    async def _flush_buffer_locked(self) -> int:
        """Internal flush execution under lock with retry and exponential backoff."""
        if not self._trade_buffer:
            self._last_flush_time = time.monotonic()
            return 0

        batch = self._trade_buffer
        self._trade_buffer = []
        batch_len = len(batch)

        columns = [
            "trade_id",
            "symbol",
            "maker_order_id",
            "taker_order_id",
            "price",
            "quantity",
            "quote_amount",
            "taker_side",
            "timestamp_ns",
            "sequence_number",
        ]

        t0 = time.perf_counter()
        attempt = 0
        while attempt < self.max_retries:
            try:
                client = self.connect()
                # Run synchronous insert in executor thread to keep async loop non-blocking
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: client.insert(
                        table="trades",
                        data=batch,
                        column_names=columns,
                    ),
                )
                dur_ms = (time.perf_counter() - t0) * 1000.0
                self.total_trades_ingested += batch_len
                self.total_batches_flushed += 1
                self.total_flush_time_ms += dur_ms
                self._last_flush_time = time.monotonic()
                return batch_len
            except Exception as e:
                attempt += 1
                backoff = self.base_backoff_sec * (2 ** (attempt - 1))
                if attempt >= self.max_retries:
                    # Re-insert failed batch back into buffer to avoid data loss
                    self._trade_buffer = batch + self._trade_buffer
                    raise RuntimeError(
                        f"Failed to flush {batch_len} trades to ClickHouse after {attempt} attempts: {e}"
                    ) from e
                await asyncio.sleep(backoff)

        return 0

    async def start_periodic_flusher(self) -> None:
        """Background loop ensuring time-based flush every flush_interval_sec."""
        self._running = True
        while self._running:
            await asyncio.sleep(self.flush_interval_sec)
            now = time.monotonic()
            if (now - self._last_flush_time) >= self.flush_interval_sec:
                try:
                    await self.flush()
                except Exception as e:
                    print(f"[ClickHouseIngestor] Periodic flush error: {e}")

    async def start(self) -> None:
        """Starts background periodic flush loop."""
        if not self._running:
            self._flush_task = asyncio.create_task(self.start_periodic_flusher())

    async def stop(self) -> None:
        """Stops background flusher and flushes remaining buffer."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        await self.flush()
        self.close()
