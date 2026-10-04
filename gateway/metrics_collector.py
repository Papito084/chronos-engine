"""
ChronosEngine - Internal Engine Telemetry & Performance Collector.
Gathers sub-microsecond latency distributions (P50, P90, P99), throughput (ops/sec),
order book depth, active orders count, and system memory consumption.
"""

import time
import os
from collections import deque
from typing import Dict, Any, List
import numpy as np

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    psutil = None
    _HAS_PSUTIL = False


class MetricsCollector:
    """
    Lock-free/lightweight telemetry aggregator designed for high-frequency instrumentation.
    """

    def __init__(self, window_size: int = 10000) -> None:
        self.window_size: int = window_size
        self._latencies_ns: deque[int] = deque(maxlen=window_size)
        try:
            self._process = psutil.Process(os.getpid()) if _HAS_PSUTIL and psutil else None
        except Exception:
            self._process = None

        # Counters
        self.total_orders_processed: int = 0
        self.total_trades_executed: int = 0
        self.active_orders_count: int = 0

        # Throughput tracking
        self._last_tick_time: float = time.monotonic()
        self._last_order_count: int = 0
        self._current_ops_sec: float = 0.0

    def record_latency(self, latency_ns: int) -> None:
        """Records a matching execution duration in nanoseconds."""
        self._latencies_ns.append(latency_ns)
        self.total_orders_processed += 1

    def record_trade(self) -> None:
        """Increments total trades executed."""
        self.total_trades_executed += 1

    def update_active_orders(self, count: int) -> None:
        """Updates count of active orders currently resting in the book."""
        self.active_orders_count = count

    def tick_throughput(self) -> None:
        """Calculates operations per second over elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_tick_time
        if elapsed >= 0.5:
            delta_orders = self.total_orders_processed - self._last_order_count
            self._current_ops_sec = delta_orders / elapsed
            self._last_tick_time = now
            self._last_order_count = self.total_orders_processed

    def get_snapshot(self) -> Dict[str, Any]:
        """Returns consolidated telemetry metrics for API and WebSocket streaming."""
        self.tick_throughput()

        if self._latencies_ns:
            arr_us = np.array(self._latencies_ns, dtype=np.float64) / 1000.0
            p50 = float(np.percentile(arr_us, 50))
            p90 = float(np.percentile(arr_us, 90))
            p99 = float(np.percentile(arr_us, 99))
            mean_lat = float(np.mean(arr_us))
            min_lat = float(np.min(arr_us))
            max_lat = float(np.max(arr_us))
        else:
            p50 = p90 = p99 = mean_lat = min_lat = max_lat = 0.0

        mem_mb = 0.0
        cpu_pct = 0.0
        if self._process is not None:
            try:
                mem_info = self._process.memory_info()
                mem_mb = round(mem_info.rss / (1024 * 1024), 2)
                cpu_pct = round(self._process.cpu_percent(), 1)
            except Exception:
                mem_mb = 0.0
                cpu_pct = 0.0

        return {
            "timestamp_ms": int(time.time() * 1000),
            "p50_latency_us": round(p50, 2),
            "p90_latency_us": round(p90, 2),
            "p99_latency_us": round(p99, 2),
            "mean_latency_us": round(mean_lat, 2),
            "min_latency_us": round(min_lat, 2),
            "max_latency_us": round(max_lat, 2),
            "ops_per_sec": round(self._current_ops_sec, 1),
            "total_orders": self.total_orders_processed,
            "total_trades": self.total_trades_executed,
            "active_orders": self.active_orders_count,
            "memory_mb": mem_mb,
            "cpu_percent": cpu_pct,
        }
