"""
ChronosEngine - WebSocket Connection & Multi-Channel Subscription Manager.
Provides dynamic topic routing for:
  - 'book_l2': Initial L2 snapshot + 50ms throttled delta diffs.
  - 'trades': Zero-latency execution broadcast.
  - 'telemetry': 1Hz cluster performance metrics.
"""

import asyncio
import time
from typing import Dict, Set, Any, List, Optional
from fastapi import WebSocket
import orjson
from core.models.types import from_fixed_point


class ConnectionManager:
    """
    Manages active WebSocket connections, channel subscriptions, and throttled L2 diff broadcasts.
    """

    def __init__(self, throttle_ms: int = 50) -> None:
        self.throttle_sec: float = throttle_ms / 1000.0
        # Map: channel_name -> set(WebSocket)
        self.subscriptions: Dict[str, Set[WebSocket]] = {
            "book_l2": set(),
            "trades": set(),
            "telemetry": set(),
        }
        # Client tracking: WebSocket -> set(channels)
        self.client_channels: Dict[WebSocket, Set[str]] = {}
        # Client tracking: WebSocket -> symbol
        self.client_symbols: Dict[WebSocket, str] = {}

        # L2 Diff Buffer: symbol -> {'bids': {price: (volume, count)}, 'asks': {price: (volume, count)}}
        self._l2_diff_buffer: Dict[str, Dict[str, Dict[int, tuple]]] = {}
        self._flusher_task: Optional[asyncio.Task] = None
        self._running: bool = False

    async def connect(self, websocket: WebSocket) -> None:
        """Accepts a new WebSocket connection."""
        await websocket.accept()
        self.client_channels[websocket] = set()
        self.client_symbols[websocket] = "BTC-USDT"

    async def disconnect(self, websocket: WebSocket) -> None:
        """Removes a disconnected client from all channel subscriptions."""
        if websocket in self.client_channels:
            for channel in self.client_channels[websocket]:
                if channel in self.subscriptions:
                    self.subscriptions[channel].discard(websocket)
            del self.client_channels[websocket]
        if websocket in self.client_symbols:
            del self.client_symbols[websocket]

    async def subscribe(self, websocket: WebSocket, channels: List[str], symbol: str = "BTC-USDT") -> None:
        """Subscribes a client to requested channels."""
        self.client_symbols[websocket] = symbol
        for ch in channels:
            if ch in self.subscriptions:
                self.subscriptions[ch].add(websocket)
                self.client_channels[websocket].add(ch)

    async def unsubscribe(self, websocket: WebSocket, channels: List[str]) -> None:
        """Unsubscribes a client from specific channels."""
        for ch in channels:
            if ch in self.subscriptions:
                self.subscriptions[ch].discard(websocket)
                self.client_channels[websocket].discard(ch)

    async def send_direct(self, websocket: WebSocket, message: Dict[str, Any]) -> None:
        """Sends a JSON message directly to a single connected client."""
        try:
            payload = orjson.dumps(message).decode("utf-8")
            await websocket.send_text(payload)
        except Exception:
            await self.disconnect(websocket)

    async def broadcast_to_channel(self, channel: str, message: Dict[str, Any], symbol: Optional[str] = None) -> None:
        """Broadcasts a JSON message to all clients subscribed to a channel."""
        subscribers = list(self.subscriptions.get(channel, set()))
        if not subscribers:
            return

        payload = orjson.dumps(message).decode("utf-8")
        dead_clients = []

        for ws in subscribers:
            # Check symbol filter if specified
            if symbol and self.client_symbols.get(ws) != symbol:
                continue
            try:
                await ws.send_text(payload)
            except Exception:
                dead_clients.append(ws)

        for ws in dead_clients:
            await self.disconnect(ws)

    # --- L2 Throttled Diff Buffering ---

    def buffer_l2_update(self, symbol: str, side: str, price: int, volume: int, order_count: int) -> None:
        """
        Synchronously buffers an L2 level update into the throttle bucket.
        Called on every matching engine BookLevelUpdatedEvent.
        """
        if symbol not in self._l2_diff_buffer:
            self._l2_diff_buffer[symbol] = {"bids": {}, "asks": {}}

        side_key = "bids" if side == "BUY" else "asks"
        self._l2_diff_buffer[symbol][side_key][price] = (volume, order_count)

    async def flush_l2_diffs(self) -> None:
        """Flushes buffered L2 diffs to subscribed clients if any updates accumulated."""
        if not self._l2_diff_buffer:
            return

        current_diffs = self._l2_diff_buffer
        self._l2_diff_buffer = {}

        now_ms = int(time.time() * 1000)

        for symbol, levels in current_diffs.items():
            bids_diff = [
                [from_fixed_point(px), from_fixed_point(vol), cnt]
                for px, (vol, cnt) in levels["bids"].items()
            ]
            asks_diff = [
                [from_fixed_point(px), from_fixed_point(vol), cnt]
                for px, (vol, cnt) in levels["asks"].items()
            ]

            if bids_diff or asks_diff:
                msg = {
                    "channel": "book_l2",
                    "type": "diff",
                    "symbol": symbol,
                    "timestamp_ms": now_ms,
                    "bids": bids_diff,
                    "asks": asks_diff,
                }
                await self.broadcast_to_channel("book_l2", msg, symbol=symbol)

    async def _l2_throttle_loop(self) -> None:
        """50ms throttle loop for L2 differential streaming (20 FPS)."""
        while self._running:
            await asyncio.sleep(self.throttle_sec)
            try:
                await self.flush_l2_diffs()
            except Exception as e:
                print(f"[ConnectionManager] L2 flush error: {e}")

    async def start(self) -> None:
        """Starts background flusher tasks."""
        if not self._running:
            self._running = True
            self._flusher_task = asyncio.create_task(self._l2_throttle_loop())

    async def stop(self) -> None:
        """Stops background tasks."""
        self._running = False
        if self._flusher_task:
            self._flusher_task.cancel()
            try:
                await self._flusher_task
            except asyncio.CancelledError:
                pass
            self._flusher_task = None
