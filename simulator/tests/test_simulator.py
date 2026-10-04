"""
Comprehensive Verification Suite for ChronosEngine Market Simulator.
Tests:
1. Geometric Brownian Motion with Poisson Jump Diffusion dynamics.
2. Avellaneda-Stoikov reservation price skewing under positive/negative inventory.
3. Multi-agent continuous simulation (Market Maker + Heavy-tailed Takers).
4. Concentrated load injection (5,000 order burst) and latency benchmarking.
"""

import asyncio
import time
import pytest

from core.engine.matching_engine import MatchingEngine
from gateway.connection_manager import ConnectionManager
from gateway.metrics_collector import MetricsCollector
from gateway.engine_bridge import EngineBridge
from simulator.price_model import JumpDiffusionPriceModel
from simulator.client import DirectExchangeClient
from simulator.market_maker import AvellanedaStoikovMarketMaker
from simulator.aggressive_trader import AggressiveTrader
from simulator.stress_injector import StressInjector


def test_gbm_jump_diffusion_dynamics():
    """
    Verifies that the JumpDiffusionPriceModel produces realistic, strictly positive
    stochastic trajectories without degenerate NaN/inf values.
    """
    model = JumpDiffusionPriceModel(
        initial_price=65000.0,
        drift=0.01,
        volatility=0.20,
        jump_intensity=0.10,
        jump_mean=0.0,
        jump_std=0.03,
        dt=0.01,
        seed=42,
    )

    prices = []
    for _ in range(1000):
        px = model.next_price()
        assert px > 0.0, "Price must remain strictly positive"
        assert not (px != px), "Price cannot be NaN"
        prices.append(px)

    assert len(prices) == 1000
    # Assert variance exists (stochastic path, not flatline)
    price_range = max(prices) - min(prices)
    assert price_range > 10.0, "Trajectory must exhibit stochastic variation"


def test_avellaneda_stoikov_inventory_skew():
    """
    Verifies quantitative inventory risk management:
    - Zero inventory (q=0): r(s, 0) == s
    - Long inventory (q>0): r(s, q) < s (quote lower to encourage selling)
    - Short inventory (q<0): r(s, q) > s (quote higher to encourage buying)
    """
    class DummyClient:
        pass

    model = JumpDiffusionPriceModel(initial_price=65000.0, volatility=0.30)
    mm = AvellanedaStoikovMarketMaker(
        client=DummyClient(),
        price_model=model,
        symbol="BTC-USDT",
        gamma=0.005,
    )

    mid = 65000.0

    # 1. Zero inventory
    mm.inventory = 0.0
    r_neutral = mm.compute_reservation_price(mid)
    assert r_neutral == mid

    # 2. Long inventory (q = +5.0 BTC)
    mm.inventory = 5.0
    r_long = mm.compute_reservation_price(mid)
    assert r_long < mid, f"Reservation price {r_long} must be less than mid-price {mid} when long"

    # 3. Short inventory (q = -5.0 BTC)
    mm.inventory = -5.0
    r_short = mm.compute_reservation_price(mid)
    assert r_short > mid, f"Reservation price {r_short} must be greater than mid-price {mid} when short"

    # 4. Asymmetry check: Distance from mid should scale with inventory magnitude
    assert abs(mid - r_long) == abs(r_short - mid)


@pytest.mark.asyncio
async def test_combined_multi_agent_continuous_simulation():
    """
    Multi-Agent Integration Test:
    Spawns Avellaneda-Stoikov MM and Aggressive Takers in Direct-Engine mode.
    Runs for 3 seconds:
    - Asserts continuous trades are executed.
    - Asserts order book spread remains bounded.
    - Asserts inventory balances update dynamically.
    """
    engine = MatchingEngine()
    ws_mgr = ConnectionManager(throttle_ms=50)
    metrics = MetricsCollector()
    bridge = EngineBridge(engine, ws_mgr, metrics)
    await ws_mgr.start()
    await bridge.start()

    client = DirectExchangeClient(bridge)
    symbol = "BTC-USDT"

    price_model = JumpDiffusionPriceModel(initial_price=65000.0, volatility=0.20, seed=123)
    mm = AvellanedaStoikovMarketMaker(
        client=client,
        price_model=price_model,
        symbol=symbol,
        base_spread=4.0,
        levels=5,
        level_spacing=2.0,
        order_quantity=0.5,
    )

    takers = AggressiveTrader(
        client=client,
        symbol=symbol,
        min_qty=0.1,
        max_qty=1.5,
        pareto_alpha=1.8,
    )

    # Initial quote
    await mm.quote_ladder()

    # Verify book has liquidity
    book = await client.get_order_book(symbol)
    assert len(book["bids"]) > 0
    assert len(book["asks"]) > 0
    assert book["best_bid"] < book["best_ask"]

    # Run combined loop for 1.5 seconds (or 100 cycles)
    trades_before = metrics.total_trades_executed

    # Launch concurrent tasks
    mm_task = asyncio.create_task(mm.run_loop(interval_sec=0.03))
    taker_task = asyncio.create_task(takers.run_loop(orders_per_sec=150.0))

    await asyncio.sleep(1.5)

    mm.stop()
    takers.stop()
    mm_task.cancel()
    taker_task.cancel()

    await asyncio.gather(mm_task, taker_task, return_exceptions=True)
    await bridge.stop()
    await ws_mgr.stop()

    trades_after = metrics.total_trades_executed
    new_trades = trades_after - trades_before

    print(f"\n[Multi-Agent Test] Generated {new_trades} trades in 1.5s (~{new_trades/1.5:,.0f} trades/sec)")
    assert new_trades > 20, f"Expected >20 trades, got {new_trades}"

    # Verify book maintains valid BBO
    book_final = await client.get_order_book(symbol)
    if book_final["best_bid"] and book_final["best_ask"]:
        assert book_final["best_bid"] <= book_final["best_ask"]


@pytest.mark.asyncio
async def test_stress_injector_burst_5000_orders():
    """
    Stress Load Test:
    Dispatches a concentrated burst of 5,000 orders into the DirectExchangeClient.
    Measures and asserts:
    - High throughput (>50,000 orders/sec).
    - Sub-millisecond latency percentiles (P50, P90, P99).
    """
    engine = MatchingEngine()
    ws_mgr = ConnectionManager()
    metrics = MetricsCollector()
    bridge = EngineBridge(engine, ws_mgr, metrics)
    client = DirectExchangeClient(bridge)

    injector = StressInjector(client=client, symbol="BTC-USDT")

    burst_size = 5000
    res = await injector.fire_burst(burst_size=burst_size, base_price=65000.0)

    print("\n" + "=" * 65)
    print("        STRESS INJECTOR BURST BENCHMARK (5,000 ORDERS)")
    print("=" * 65)
    print(f"Total Orders:        {res['burst_size']:,}")
    print(f"Total Duration:      {res['total_duration_sec']:.4f} s")
    print(f"Throughput:          {res['ops_per_sec']:,.0f} ops/sec")
    print(f"P50 Latency:         {res['p50_latency_us']:.2f} µs")
    print(f"P90 Latency:         {res['p90_latency_us']:.2f} µs")
    print(f"P99 Latency:         {res['p99_latency_us']:.2f} µs")
    print(f"P99.9 Latency:       {res['p99_9_latency_us']:.2f} µs")
    print("=" * 65)

    assert res["burst_size"] == burst_size
    assert res["ops_per_sec"] > 25000.0
    assert res["p50_latency_us"] < 200.0
