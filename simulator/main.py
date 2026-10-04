"""
ChronosEngine - Market Simulator & Multi-Agent Orchestrator.
Spawns and coordinates:
- Avellaneda-Stoikov Market Maker (ladder quoting & inventory control).
- Stochastic Aggressive Traders (heavy-tailed power law orders).
- Periodic Stress Injector (burst testing every N seconds).
Configurable via environment variables or CLI arguments.
"""

import asyncio
import os
import sys
import argparse
from typing import Optional

from simulator.price_model import JumpDiffusionPriceModel
from simulator.client import NetworkExchangeClient, DirectExchangeClient
from simulator.market_maker import AvellanedaStoikovMarketMaker
from simulator.aggressive_trader import AggressiveTrader
from simulator.stress_injector import StressInjector


async def run_simulation(
    symbol: str = "BTC-USDT",
    initial_price: float = 65000.0,
    gateway_url: str = "http://localhost:8000",
    mode: str = "network",
    mm_interval_sec: float = 0.10,
    taker_rate: float = 100.0,
    stress_interval_sec: float = 30.0,
    stress_burst_size: int = 5000,
    bridge=None,
    duration_sec: Optional[float] = None,
) -> None:
    print("=" * 65)
    print("           CHRONOS-ENGINE MARKET SIMULATOR ACTIVE")
    print("=" * 65)
    print(f"Symbol:               {symbol}")
    print(f"Initial Mid-Price:    ${initial_price:,.2f}")
    print(f"Connection Mode:      {mode.upper()}")
    print(f"Market Maker Refresh: {mm_interval_sec * 1000:.0f} ms")
    print(f"Taker Order Rate:     {taker_rate:.0f} orders/sec")
    print(f"Stress Burst Interval:{stress_interval_sec:.0f} s (burst size: {stress_burst_size:,})")
    print("=" * 65)

    # 1. Initialize Client
    if mode == "direct":
        if bridge is None:
            raise ValueError("Bridge must be supplied in direct mode")
        client = DirectExchangeClient(bridge)
    else:
        client = NetworkExchangeClient(base_url=gateway_url)

    # 2. Initialize Models & Agents
    price_model = JumpDiffusionPriceModel(
        initial_price=initial_price,
        volatility=0.0008,
        dt=0.1,
        drift=0.0,
    )

    market_maker = AvellanedaStoikovMarketMaker(
        client=client,
        price_model=price_model,
        symbol=symbol,
        base_spread=4.0,
        levels=5,
        level_spacing=2.0,
        order_quantity=0.5,
    )

    aggressive_trader = AggressiveTrader(
        client=client,
        symbol=symbol,
        min_qty=0.05,
        max_qty=4.0,
        pareto_alpha=1.8,
    )

    stress_injector = StressInjector(client=client, symbol=symbol)

    # 3. Background periodic stress task
    async def stress_loop():
        while True:
            await asyncio.sleep(stress_interval_sec)
            print(f"\n[StressInjector] Firing high-intensity burst of {stress_burst_size:,} orders...")
            res = await stress_injector.fire_burst(
                burst_size=stress_burst_size,
                base_price=price_model.current_price,
            )
            print(
                f"[StressInjector] Complete: {res['burst_size']} orders in {res['total_duration_sec']}s "
                f"({res['ops_per_sec']:,.0f} ops/s) | P50: {res['p50_latency_us']} µs | P99: {res['p99_latency_us']} µs"
            )

    # 4. Launch all agent tasks
    tasks = [
        asyncio.create_task(market_maker.run_loop(interval_sec=mm_interval_sec)),
        asyncio.create_task(aggressive_trader.run_loop(orders_per_sec=taker_rate)),
        asyncio.create_task(stress_loop()),
    ]

    try:
        if duration_sec:
            await asyncio.sleep(duration_sec)
        else:
            await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        market_maker.stop()
        aggressive_trader.stop()
        for t in tasks:
            t.cancel()
        if hasattr(client, "close"):
            await client.close()
        print("\n[ChronosEngine Simulator] All simulation agents stopped.")


def main():
    parser = argparse.ArgumentParser(description="ChronosEngine Multi-Agent Market Simulator")
    parser.add_argument("--symbol", default=os.getenv("SYMBOL", "BTC-USDT"), help="Trading pair symbol")
    parser.add_argument(
        "--initial-price",
        type=float,
        default=float(os.getenv("INITIAL_PRICE", "65000.0")),
        help="Initial mid-price",
    )
    parser.add_argument(
        "--gateway-url",
        default=os.getenv("GATEWAY_URL", "http://localhost:8000"),
        help="Market data gateway URL",
    )
    parser.add_argument(
        "--mode",
        default=os.getenv("MODE", "network"),
        choices=["network", "direct"],
        help="Execution mode",
    )
    parser.add_argument(
        "--mm-interval",
        type=float,
        default=float(os.getenv("MM_INTERVAL_MS", "100")) / 1000.0,
        help="Market maker refresh interval in seconds",
    )
    parser.add_argument(
        "--taker-rate",
        type=float,
        default=float(os.getenv("TAKER_RATE_PER_SEC", "100")),
        help="Taker orders per second",
    )
    parser.add_argument(
        "--stress-interval",
        type=float,
        default=float(os.getenv("STRESS_BURST_INTERVAL_SEC", "30")),
        help="Stress burst interval in seconds",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Total simulation run duration in seconds",
    )

    args = parser.parse_args()

    asyncio.run(
        run_simulation(
            symbol=args.symbol,
            initial_price=args.initial_price,
            gateway_url=args.gateway_url,
            mode=args.mode,
            mm_interval_sec=args.mm_interval,
            taker_rate=args.taker_rate,
            stress_interval_sec=args.stress_interval,
            duration_sec=args.duration,
        )
    )


if __name__ == "__main__":
    main()
