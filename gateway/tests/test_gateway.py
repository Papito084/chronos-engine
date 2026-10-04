"""
Comprehensive Verification Suite for ChronosEngine Gateway & API.
Tests:
1. REST /api/v1/health & /api/v1/telemetry
2. REST /api/v1/orders (Placement, Matching, Rejections, Cancellation)
3. REST /api/v1/market/book, /candles, /trades, /summary
4. WebSocket /ws/market (Multiplexed channels: book_l2, trades, telemetry)
5. 50ms L2 Diff Throttling & Coalescing validation.
"""

import time
import asyncio
from typing import Dict, Any
import pytest
from starlette.testclient import TestClient
import orjson

from gateway.main import app
from core.models.types import to_fixed_point, from_fixed_point
from gateway.connection_manager import ConnectionManager


def test_rest_health_and_telemetry():
    """Verifies that healthcheck and telemetry endpoints respond with accurate engine state."""
    with TestClient(app) as client:
        res = client.get("/api/v1/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "HEALTHY"
        assert data["engine_status"] == "ONLINE"

        res_tel = client.get("/api/v1/telemetry")
        assert res_tel.status_code == 200
        tel_data = res_tel.json()
        assert "p50_latency_us" in tel_data
        assert "ops_per_sec" in tel_data
        assert "memory_mb" in tel_data


def test_rest_order_placement_and_matching():
    """
    Verifies:
    1. Placing a resting limit order.
    2. Placing a crossing aggressive order that immediately matches.
    3. Canceling a resting order.
    """
    with TestClient(app) as client:
        symbol = "BTC-TEST"

        # 1. Place resting maker order: SELL 1.0 @ 51,000
        order_payload_1 = {
            "symbol": symbol,
            "side": "SELL",
            "order_type": "LIMIT",
            "price": 51000.0,
            "quantity": 1.0,
            "time_in_force": "GTC",
            "order_id": "test_maker_1",
        }
        res1 = client.post("/api/v1/orders", json=order_payload_1)
        assert res1.status_code == 201
        data1 = res1.json()
        assert data1["order_id"] == "test_maker_1"
        assert data1["status"] in ("NEW", "PARTIALLY_FILLED")

        # 2. Place crossing taker order: BUY 0.5 @ 51,000 (Matches!)
        order_payload_2 = {
            "symbol": symbol,
            "side": "BUY",
            "order_type": "LIMIT",
            "price": 51000.0,
            "quantity": 0.5,
            "time_in_force": "IOC",
            "order_id": "test_taker_1",
        }
        res2 = client.post("/api/v1/orders", json=order_payload_2)
        assert res2.status_code == 201
        data2 = res2.json()
        assert data2["order_id"] == "test_taker_1"
        assert data2["status"] == "FILLED"
        assert len(data2["trades"]) == 1
        assert data2["trades"][0]["maker_order_id"] == "test_maker_1"
        assert data2["trades"][0]["quantity"] == 0.5
        assert data2["trades"][0]["price"] == 51000.0

        # 3. Cancel remaining 0.5 of test_maker_1
        res3 = client.delete(f"/api/v1/orders/test_maker_1?symbol={symbol}")
        assert res3.status_code == 200
        data3 = res3.json()
        assert data3["status"] == "CANCELED"
        assert data3["remaining_quantity"] == 0.5

        # 4. Attempt to cancel again -> 404
        res4 = client.delete(f"/api/v1/orders/test_maker_1?symbol={symbol}")
        assert res4.status_code == 404


def test_rest_market_data_endpoints():
    """Verifies L2 order book snapshot, trade history and summary."""
    with TestClient(app) as client:
        symbol = "BTC-USDT"

        # L2 Book
        res_book = client.get(f"/api/v1/market/book?symbol={symbol}&depth=10")
        assert res_book.status_code == 200
        book_data = res_book.json()
        assert book_data["symbol"] == symbol
        assert isinstance(book_data["bids"], list)
        assert isinstance(book_data["asks"], list)

        # Market Summary
        res_sum = client.get(f"/api/v1/market/summary?symbol={symbol}")
        assert res_sum.status_code == 200
        sum_data = res_sum.json()
        assert sum_data["symbol"] == symbol
        assert "vwap_24h" in sum_data

        # Candles
        res_candles = client.get(f"/api/v1/market/candles?symbol={symbol}&timeframe=1s&limit=10")
        assert res_candles.status_code == 200
        assert isinstance(res_candles.json(), list)


def test_websocket_market_subscription_and_live_events():
    """
    WebSocket Streaming Test:
    1. Connects to /ws/market inside lifespan.
    2. Subscribes to ['book_l2', 'trades', 'telemetry'].
    3. Validates receipt of initial book_l2 snapshot.
    4. Validates receipt of telemetry packet.
    5. Places an order causing a match and verifies immediate 'trades' broadcast.
    """
    with TestClient(app) as client:
        with client.websocket_connect("/ws/market") as ws:
            # Subscribe to channels
            sub_msg = {
                "action": "subscribe",
                "channels": ["book_l2", "trades", "telemetry"],
                "symbol": "BTC-USDT",
            }
            ws.send_text(orjson.dumps(sub_msg).decode("utf-8"))

            # Message 1: Initial book_l2 snapshot
            msg1_raw = ws.receive_text()
            msg1 = orjson.loads(msg1_raw)
            assert msg1.get("channel") == "book_l2"
            assert msg1.get("type") == "snapshot"
            assert "bids" in msg1
            assert "asks" in msg1

            # Message 2: Initial telemetry snapshot
            msg2_raw = ws.receive_text()
            msg2 = orjson.loads(msg2_raw)
            assert msg2.get("channel") == "telemetry"
            assert "data" in msg2

            # Message 3: Subscription acknowledgement
            msg3_raw = ws.receive_text()
            msg3 = orjson.loads(msg3_raw)
            assert msg3.get("type") == "subscribed"
            assert "book_l2" in msg3.get("channels", [])

            # Trigger a trade in the running application via REST
            res = client.post("/api/v1/orders", json={
                "symbol": "BTC-USDT",
                "side": "SELL",
                "order_type": "LIMIT",
                "price": 65000.0,
                "quantity": 0.1,
                "time_in_force": "IOC",
            })
            assert res.status_code == 201

            # WebSocket must receive the executed trade event immediately
            raw = ws.receive_text()
            event_obj = orjson.loads(raw)
            assert event_obj.get("channel") == "trades"
            assert event_obj.get("symbol") == "BTC-USDT"
            assert event_obj.get("price") == 65000.0


def test_l2_diff_throttling_coalescence():
    """
    Verifies that rapid bursts of level updates are buffered and coalesced
    into a single diff message rather than flooding the connection.
    """
    cm = ConnectionManager(throttle_ms=50)

    # Simulate 100 rapid price level updates for the same price level
    for i in range(100):
        vol = 1000 + i
        cm.buffer_l2_update("BTC-USDT", "BUY", 5000000000000, vol, 1)

    # Inspect the buffer: should be coalesced to 1 entry for this price
    buffered = cm._l2_diff_buffer["BTC-USDT"]["bids"]
    assert len(buffered) == 1
    assert buffered[5000000000000] == (1099, 1)
