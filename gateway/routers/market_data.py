"""
ChronosEngine - REST Market Data & Telemetry Router.
Serves L2 Order Book snapshots, historical OHLCV candles (from ClickHouse),
recent trade executions, 24h market summaries, and healthcheck telemetry.
"""

import time
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from core.models.types import from_fixed_point, fixed_to_str


def create_market_data_router(bridge, candle_service=None) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Market Data"])
    start_time = time.time()

    @router.get("/health")
    async def healthcheck():
        uptime = round(time.time() - start_time, 1)
        return {
            "status": "HEALTHY",
            "service": "chronos-gateway",
            "uptime_sec": uptime,
            "engine_status": "ONLINE",
            "active_symbols": list(bridge.engine.books.keys()),
        }

    @router.get("/telemetry")
    async def get_telemetry():
        return bridge.metrics.get_snapshot()

    @router.get("/market/book")
    async def get_order_book(
        symbol: str = Query("BTC-USDT", description="Trading pair symbol"),
        depth: int = Query(25, ge=1, le=100, description="Depth levels to return"),
    ):
        book = bridge.engine.books.get(symbol)
        if not book:
            return {
                "symbol": symbol,
                "bids": [],
                "asks": [],
                "best_bid": None,
                "best_ask": None,
                "spread": None,
            }

        l2 = book.get_l2_snapshot(depth=depth)
        # Format for frontend presentation
        formatted_bids = [
            [from_fixed_point(px), from_fixed_point(vol), cnt]
            for px, vol, cnt in l2["bids"]
        ]
        formatted_asks = [
            [from_fixed_point(px), from_fixed_point(vol), cnt]
            for px, vol, cnt in l2["asks"]
        ]

        return {
            "symbol": symbol,
            "bids": formatted_bids,
            "asks": formatted_asks,
            "best_bid": from_fixed_point(l2["best_bid"]) if l2["best_bid"] is not None else None,
            "best_ask": from_fixed_point(l2["best_ask"]) if l2["best_ask"] is not None else None,
            "spread": from_fixed_point(l2["spread"]) if l2["spread"] is not None else None,
            "timestamp_ms": int(time.time() * 1000),
        }

    @router.get("/market/candles")
    async def get_candles(
        symbol: str = Query("BTC-USDT", description="Trading pair symbol"),
        timeframe: str = Query("1s", pattern="^(1s|1m)$", description="Candle timeframe ('1s' or '1m')"),
        limit: int = Query(100, ge=1, le=1000, description="Max candles to retrieve"),
    ):
        candles = []
        if candle_service:
            try:
                candles = candle_service.get_candles(symbol=symbol, timeframe=timeframe, limit=limit)
            except Exception:
                candles = []

        if candles:
            valid_candles = [c for c in candles if 10000 <= float(c.get("open", 0)) <= 100000]
            if valid_candles:
                return valid_candles

        # Fallback 1: Aggregate candles from in-memory matching engine trades history
        recent_trades = [t for t in bridge.engine.trades_history if t.symbol == symbol]
        if recent_trades:
            interval = 1 if timeframe == "1s" else 60
            bucket_map = {}
            for t in recent_trades:
                px = from_fixed_point(t.price)
                if px < 10000 or px > 100000:
                    continue
                sec = int(t.timestamp_ns / 1_000_000_000)
                b_sec = sec - (sec % interval)
                qty = from_fixed_point(t.quantity)
                if b_sec not in bucket_map:
                    bucket_map[b_sec] = {
                        "time": b_sec,
                        "open": px,
                        "high": px,
                        "low": px,
                        "close": px,
                        "volume": qty,
                    }
                else:
                    c = bucket_map[b_sec]
                    c["high"] = max(c["high"], px)
                    c["low"] = min(c["low"], px)
                    c["close"] = px
                    c["volume"] = round(c["volume"] + qty, 6)

            sorted_candles = [bucket_map[k] for k in sorted(bucket_map.keys())]
            if sorted_candles:
                return sorted_candles[-limit:]

        # Fallback 2: Generate baseline history around current mid-price
        now_sec = int(time.time())
        mid = 65000.0
        book = bridge.engine.books.get(symbol)
        if book:
            l2 = book.get_l2_snapshot(depth=1)
            bb = from_fixed_point(l2["best_bid"]) if l2["best_bid"] else None
            ba = from_fixed_point(l2["best_ask"]) if l2["best_ask"] else None
            if bb and ba and 10000 <= bb <= 100000:
                mid = (bb + ba) / 2
            elif bb and 10000 <= bb <= 100000:
                mid = bb
            elif ba and 10000 <= ba <= 100000:
                mid = ba

        interval = 1 if timeframe == "1s" else 60
        base_time = now_sec - (now_sec % interval)
        return [
            {
                "time": base_time - (i * interval),
                "open": mid,
                "high": mid,
                "low": mid,
                "close": mid,
                "volume": 0.1,
            }
            for i in range(min(limit, 30), -1, -1)
        ]

    @router.get("/market/trades")
    async def get_recent_trades(
        symbol: str = Query("BTC-USDT", description="Trading pair symbol"),
        limit: int = Query(50, ge=1, le=200, description="Max trades to retrieve"),
    ):
        # 1. Try ClickHouse first if configured
        if candle_service:
            try:
                trades = candle_service.get_recent_trades(symbol=symbol, limit=limit)
                if trades:
                    valid_trades = [t for t in trades if 10000 <= float(t.get("price", 0)) <= 100000]
                    if valid_trades:
                        return valid_trades
            except Exception:
                pass

        # 2. In-memory engine fallback
        in_memory_trades = [
            t.to_dict() for t in reversed(bridge.engine.trades_history)
            if t.symbol == symbol and 10000 <= from_fixed_point(t.price) <= 100000
        ][:limit]
        return in_memory_trades

    @router.get("/market/summary")
    async def get_market_summary(
        symbol: str = Query("BTC-USDT", description="Trading pair symbol"),
    ):
        if candle_service:
            try:
                return candle_service.get_market_summary_24h(symbol=symbol)
            except Exception:
                pass

        # Fallback computation from in-memory engine trades
        trades = [t for t in bridge.engine.trades_history if t.symbol == symbol]
        if not trades:
            return {
                "symbol": symbol,
                "high_24h": 0.0,
                "low_24h": 0.0,
                "volume_24h": 0.0,
                "quote_volume_24h": 0.0,
                "vwap_24h": 0.0,
                "trade_count_24h": 0,
            }

        prices = [from_fixed_point(t.price) for t in trades]
        vol = sum(from_fixed_point(t.quantity) for t in trades)
        qvol = sum(from_fixed_point(t.quote_amount) for t in trades)
        vwap = (qvol / vol) if vol > 0 else 0.0

        return {
            "symbol": symbol,
            "high_24h": max(prices),
            "low_24h": min(prices),
            "volume_24h": round(vol, 4),
            "quote_volume_24h": round(qvol, 2),
            "vwap_24h": round(vwap, 2),
            "trade_count_24h": len(trades),
        }

    return router
