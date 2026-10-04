"""
ChronosEngine - WebSocket Streaming Endpoints.
Serves:
  /ws/market: Dynamic multiplexed channel subscriptions (book_l2, trades, telemetry).
  /ws/telemetry: Dedicated 1Hz engine telemetry metrics.
"""

import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import orjson
from core.models.types import from_fixed_point


def create_ws_router(bridge) -> APIRouter:
    router = APIRouter(tags=["WebSockets"])
    manager = bridge.ws_manager

    @router.websocket("/ws/market")
    async def websocket_market_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                data_text = await websocket.receive_text()
                try:
                    msg = orjson.loads(data_text)
                    action = msg.get("action", "").lower()
                    channels = msg.get("channels", [])
                    symbol = msg.get("symbol", "BTC-USDT")

                    if action == "subscribe":
                        await manager.subscribe(websocket, channels, symbol=symbol)

                        # If subscribed to 'book_l2', send immediate initial snapshot
                        if "book_l2" in channels:
                            book = bridge.engine.get_or_create_book(symbol)
                            l2 = book.get_l2_snapshot(depth=25)
                            formatted_bids = [
                                [from_fixed_point(px), from_fixed_point(vol), cnt]
                                for px, vol, cnt in l2["bids"]
                            ]
                            formatted_asks = [
                                [from_fixed_point(px), from_fixed_point(vol), cnt]
                                for px, vol, cnt in l2["asks"]
                            ]
                            snap_msg = {
                                "channel": "book_l2",
                                "type": "snapshot",
                                "symbol": symbol,
                                "timestamp_ms": int(time.time() * 1000),
                                "bids": formatted_bids,
                                "asks": formatted_asks,
                            }
                            await manager.send_direct(websocket, snap_msg)

                        # If subscribed to 'telemetry', send immediate snapshot
                        if "telemetry" in channels:
                            tel_msg = {
                                "channel": "telemetry",
                                "data": bridge.metrics.get_snapshot(),
                            }
                            await manager.send_direct(websocket, tel_msg)

                        # Acknowledge subscription
                        ack = {
                            "type": "subscribed",
                            "channels": list(manager.client_channels.get(websocket, [])),
                            "symbol": symbol,
                        }
                        await manager.send_direct(websocket, ack)

                    elif action == "unsubscribe":
                        await manager.unsubscribe(websocket, channels)
                        ack = {
                            "type": "unsubscribed",
                            "channels": list(manager.client_channels.get(websocket, [])),
                        }
                        await manager.send_direct(websocket, ack)

                except Exception as err:
                    err_msg = {"type": "error", "message": f"Malformed request: {err}"}
                    await manager.send_direct(websocket, err_msg)

        except WebSocketDisconnect:
            await manager.disconnect(websocket)
        except Exception:
            await manager.disconnect(websocket)

    @router.websocket("/ws/telemetry")
    async def websocket_telemetry_dedicated(websocket: WebSocket):
        """Dedicated telemetry socket streaming system metrics."""
        await manager.connect(websocket)
        await manager.subscribe(websocket, ["telemetry"])
        # Send immediate metrics
        await manager.send_direct(websocket, {
            "channel": "telemetry",
            "data": bridge.metrics.get_snapshot(),
        })
        try:
            while True:
                # Keep socket alive awaiting client pings
                await websocket.receive_text()
        except WebSocketDisconnect:
            await manager.disconnect(websocket)
        except Exception:
            await manager.disconnect(websocket)

    return router
