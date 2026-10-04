"""
ChronosEngine - High-Frequency Trading Market Data Gateway & API.
Features:
- FastAPI with asynchronous Lifespan lifecycle management.
- CORS middleware for real-time React 18 trading terminal.
- Zero-copy in-memory matching engine integration via non-blocking EngineBridge.
- 50ms throttled L2 Order Book differential streaming.
- Immediate trade execution broadcasts.
- High-resolution telemetry & ClickHouse OLAP persistence.
"""

from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from core.models.types import to_fixed_point, Side, OrderType, TimeInForce
from core.models.events import NewOrderCommand
from core.engine.matching_engine import MatchingEngine
from persistence.clickhouse_ingestor import ClickHouseIngestor
from persistence.candle_service import CandleService
from gateway.connection_manager import ConnectionManager
from gateway.metrics_collector import MetricsCollector
from gateway.engine_bridge import EngineBridge
from gateway.routers.orders import create_orders_router
from gateway.routers.market_data import create_market_data_router
from gateway.routers.ws import create_ws_router


# Global singletons initialized eagerly
engine: MatchingEngine = MatchingEngine()
ws_manager: ConnectionManager = ConnectionManager(throttle_ms=50)
metrics_collector: MetricsCollector = MetricsCollector()

import os

# ClickHouse persistence & query service
ch_host = os.getenv("CLICKHOUSE_HOST", "localhost")
ch_port = int(os.getenv("CLICKHOUSE_PORT", "8123"))

try:
    ingestor: Optional[ClickHouseIngestor] = ClickHouseIngestor(
        host=ch_host,
        port=ch_port,
        database="chronos",
        batch_size=500,
        flush_interval_ms=250,
    )
    candle_service: Optional[CandleService] = CandleService(
        host=ch_host, port=ch_port, database="chronos"
    )
except Exception as e:
    print(f"[Gateway] ClickHouse init error: {e}")
    ingestor = None
    candle_service = None

# Engine bridge
bridge: EngineBridge = EngineBridge(
    engine=engine,
    connection_manager=ws_manager,
    metrics_collector=metrics_collector,
    ingestor=ingestor,
)

# Seed reference BTC-USDT orders
engine.process_command(
    NewOrderCommand(
        "seed_bid_1",
        "BTC-USDT",
        Side.BUY,
        OrderType.LIMIT,
        to_fixed_point("65000.00"),
        to_fixed_point("1.5"),
        TimeInForce.GTC,
    )
)
engine.process_command(
    NewOrderCommand(
        "seed_ask_1",
        "BTC-USDT",
        Side.SELL,
        OrderType.LIMIT,
        to_fixed_point("65005.00"),
        to_fixed_point("2.0"),
        TimeInForce.GTC,
    )
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background loops
    if ingestor:
        try:
            await ingestor.start()
        except Exception as e:
            print(f"[Gateway Lifespan] ClickHouse offline: {e}")

    await ws_manager.start()
    await bridge.start()
    print("[ChronosEngine Gateway] System online and accepting traffic on port 8000.")

    yield

    # Shutdown sequence
    print("[ChronosEngine Gateway] Initiating graceful shutdown...")
    await bridge.stop()
    await ws_manager.stop()
    if ingestor:
        try:
            await ingestor.stop()
        except Exception:
            pass
    print("[ChronosEngine Gateway] Shutdown complete.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="ChronosEngine Market Data Gateway & API",
        version="0.1.0",
        description="Ultra-low latency exchange gateway with real-time L2 order book streaming and financial telemetry.",
        lifespan=lifespan,
    )

    # Enable full CORS for frontend React 18 integration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers at app creation time
    app.include_router(create_orders_router(bridge))
    app.include_router(create_market_data_router(bridge, candle_service))
    app.include_router(create_ws_router(bridge))

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run("gateway.main:app", host="0.0.0.0", port=8000, reload=False)
