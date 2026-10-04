"""
ChronosEngine - High-Frequency Stress & Burst Load Injector.
Fires high-intensity microsecond bursts (5,000 to 25,000 orders) to stress test
the LMAX Disruptor queue, matching engine determinism, and P99/P99.9 latency envelopes.
"""

import time
import random
import uuid
from typing import Dict, Any, List
import numpy as np

from simulator.client import ExchangeClient, DirectExchangeClient


class StressInjector:
    """
    Stress generator capable of saturating the matching core with concentrated order bursts.
    """

    def __init__(self, client: ExchangeClient, symbol: str = "BTC-USDT") -> None:
        self.client: ExchangeClient = client
        self.symbol: str = symbol

    async def fire_burst(
        self,
        burst_size: int = 5000,
        base_price: float = 65000.0,
    ) -> Dict[str, Any]:
        """
        Executes a concentrated burst of orders and collects precise latency statistics.
        """
        order_latencies_ns: List[int] = []

        t_start_all = time.perf_counter()

        for i in range(burst_size):
            side = "BUY" if i % 2 == 0 else "SELL"
            # 80% limit crossing, 20% market orders
            is_market = (i % 5 == 0)
            offset = (i % 10 - 5) * 1.0
            price = base_price + offset
            qty = 0.1

            oid = f"burst_{i}_{uuid.uuid4().hex[:6]}"

            t0 = time.perf_counter_ns()
            if is_market:
                limit_px = round(base_price * 1.002, 2) if side == "BUY" else round(base_price * 0.998, 2)
                await self.client.place_order(
                    symbol=self.symbol,
                    side=side,
                    order_type="LIMIT",
                    price=limit_px,
                    quantity=qty,
                    time_in_force="IOC",
                    order_id=oid,
                )
            else:
                await self.client.place_order(
                    symbol=self.symbol,
                    side=side,
                    order_type="LIMIT",
                    price=price,
                    quantity=qty,
                    time_in_force="IOC",
                    order_id=oid,
                )
            t1 = time.perf_counter_ns()
            order_latencies_ns.append(t1 - t0)

        t_end_all = time.perf_counter()
        total_time_sec = t_end_all - t_start_all

        # Compute percentile metrics in microseconds
        lat_arr_us = np.array(order_latencies_ns, dtype=np.float64) / 1000.0
        p50 = float(np.percentile(lat_arr_us, 50))
        p90 = float(np.percentile(lat_arr_us, 90))
        p99 = float(np.percentile(lat_arr_us, 99))
        p99_9 = float(np.percentile(lat_arr_us, 99.9))
        mean_lat = float(np.mean(lat_arr_us))
        min_lat = float(np.min(lat_arr_us))
        max_lat = float(np.max(lat_arr_us))

        ops_per_sec = burst_size / total_time_sec if total_time_sec > 0 else 0.0

        return {
            "burst_size": burst_size,
            "total_duration_sec": round(total_time_sec, 4),
            "ops_per_sec": round(ops_per_sec, 1),
            "p50_latency_us": round(p50, 2),
            "p90_latency_us": round(p90, 2),
            "p99_latency_us": round(p99, 2),
            "p99_9_latency_us": round(p99_9, 2),
            "mean_latency_us": round(mean_lat, 2),
            "min_latency_us": round(min_lat, 2),
            "max_latency_us": round(max_lat, 2),
        }
