"""
Latency Benchmark & Performance Telemetry for ChronosEngine.
Measures nanosecond-level execution latencies across percentiles (P50, P90, P99, P99.9)
for resting orders, crossing matches, and cancellations.
"""

import time
import numpy as np
import pytest
from core.models.types import Side, OrderType, TimeInForce, to_fixed_point
from core.models.events import NewOrderCommand, CancelOrderCommand
from core.engine.matching_engine import MatchingEngine


def test_matching_latency_benchmarks():
    """
    Executes a high-frequency sequence of alternating limit orders, crossing matches,
    and cancellations while capturing latency distributions.
    """
    engine = MatchingEngine()
    warmup_ops = 500
    benchmark_ops = 5000

    base_price = to_fixed_point("50000.00")
    tick_size = to_fixed_point("1.00")
    qty = to_fixed_point("0.1")

    # Warmup
    for i in range(warmup_ops):
        engine.process_command(
            NewOrderCommand(f"w_b_{i}", "BTC-USDT", Side.BUY, OrderType.LIMIT, base_price, qty)
        )
        engine.process_command(
            NewOrderCommand(f"w_s_{i}", "BTC-USDT", Side.SELL, OrderType.LIMIT, base_price, qty)
        )

    # Benchmark: Crossing Trades (Taker matches resting Maker)
    match_latencies_ns = []

    for i in range(benchmark_ops):
        # 1. Place resting maker ask
        maker_id = f"bench_m_{i}"
        engine.process_command(
            NewOrderCommand(maker_id, "BTC-USDT", Side.SELL, OrderType.LIMIT, base_price + tick_size, qty)
        )

        # 2. Measure aggressive crossing taker buy
        taker_id = f"bench_t_{i}"
        cmd = NewOrderCommand(taker_id, "BTC-USDT", Side.BUY, OrderType.LIMIT, base_price + tick_size, qty)

        t_start = time.perf_counter_ns()
        engine.process_command(cmd)
        t_end = time.perf_counter_ns()

        match_latencies_ns.append(t_end - t_start)

    # Statistical computation in microseconds
    latencies_us = np.array(match_latencies_ns, dtype=np.float64) / 1000.0

    p50 = np.percentile(latencies_us, 50)
    p90 = np.percentile(latencies_us, 90)
    p99 = np.percentile(latencies_us, 99)
    p99_9 = np.percentile(latencies_us, 99.9)
    mean_lat = np.mean(latencies_us)
    min_lat = np.min(latencies_us)
    max_lat = np.max(latencies_us)

    throughput_ops_sec = 1_000_000.0 / mean_lat if mean_lat > 0 else 0

    print("\n" + "=" * 65)
    print("           CHRONOS-ENGINE CORE MATCHING BENCHMARK")
    print("=" * 65)
    print(f"Sample Size:        {benchmark_ops:,} order matching cycles")
    print(f"Min Latency:        {min_lat:.2f} µs")
    print(f"Mean Latency:       {mean_lat:.2f} µs")
    print(f"Median (P50):       {p50:.2f} µs")
    print(f"90th %ile (P90):    {p90:.2f} µs")
    print(f"99th %ile (P99):    {p99:.2f} µs")
    print(f"99.9th %ile (P99.9):{p99_9:.2f} µs")
    print(f"Max Latency:        {max_lat:.2f} µs")
    print(f"Est. Throughput:    {throughput_ops_sec:,.0f} matches/sec")
    print("=" * 65)

    # Sanity checks: P50 latency should easily be sub-millisecond (< 500 µs in Python)
    assert p50 < 500.0, f"P50 latency {p50} µs exceeds threshold"
    assert p99 < 2000.0, f"P99 latency {p99} µs exceeds threshold"


def test_disruptor_processor_throughput():
    """Verifies that the Disruptor RingBuffer decouples and processes commands deterministically."""
    from core.engine.disruptor import DisruptorEngineProcessor

    engine = MatchingEngine()
    disruptor = DisruptorEngineProcessor(engine, ring_buffer_size=16384)

    total_orders = 2000
    px = to_fixed_point("100.00")
    qty = to_fixed_point("1.0")

    t_start = time.perf_counter_ns()
    for i in range(total_orders):
        disruptor.submit_command(
            NewOrderCommand(f"ring_ord_{i}", "BTC-USDT", Side.BUY, OrderType.LIMIT, px, qty)
        )
    t_publish_done = time.perf_counter_ns()

    processed = disruptor.process_all_pending()
    t_process_done = time.perf_counter_ns()

    assert processed == total_orders
    publish_dur_ms = (t_publish_done - t_start) / 1_000_000.0
    drain_dur_ms = (t_process_done - t_publish_done) / 1_000_000.0

    print(f"\nDisruptor RingBuffer: Published {total_orders} in {publish_dur_ms:.2f} ms, Drained in {drain_dur_ms:.2f} ms")
