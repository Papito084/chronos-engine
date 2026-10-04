import { useEffect, useRef, useState, useCallback } from 'react';
import { OrderBookState, TradeEvent, TelemetryMetrics, OrderBookLevel } from '../types';
import { normalizePrice, normalizeQty } from '../utils/formatters';

interface UseWebSocketOptions {
  symbol: string;
}

export function useWebSocket({ symbol }: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [orderBook, setOrderBook] = useState<OrderBookState>({
    symbol,
    bids: [],
    asks: [],
    bestBid: null,
    bestAsk: null,
    spread: null,
    spreadPercent: null,
  });
  const [trades, setTrades] = useState<TradeEvent[]>([]);
  const [telemetry, setTelemetry] = useState<TelemetryMetrics | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const activeBidsRef = useRef<Map<number, [number, number]>>(new Map());
  const activeAsksRef = useRef<Map<number, [number, number]>>(new Map());

  // Determine WebSocket target endpoint
  const getWsUrl = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // If port 3000 (Vite dev), connect to vite proxy or direct to 8000
    if (window.location.port === '3000' || window.location.port === '3002') {
      return `${protocol}//${window.location.host}/ws/market`;
    }
    return `${protocol}//${window.location.hostname}:8000/ws/market`;
  }, []);

  const updateOrderBookState = useCallback(() => {
    // 1. Convert to OrderBookLevel, normalize and filter invalid/zero entries
    const rawBids: OrderBookLevel[] = Array.from(activeBidsRef.current.entries())
      .map(([px, [vol, cnt]]) => [normalizePrice(px), normalizeQty(vol), Number(cnt) || 1] as OrderBookLevel)
      .filter(([px, vol]) => px > 0 && vol > 0)
      .sort((a, b) => b[0] - a[0]);

    const rawAsks: OrderBookLevel[] = Array.from(activeAsksRef.current.entries())
      .map(([px, [vol, cnt]]) => [normalizePrice(px), normalizeQty(vol), Number(cnt) || 1] as OrderBookLevel)
      .filter(([px, vol]) => px > 0 && vol > 0)
      .sort((a, b) => a[0] - b[0]);

    const initialBestBid = rawBids.length > 0 ? rawBids[0][0] : null;
    const initialBestAsk = rawAsks.length > 0 ? rawAsks[0][0] : null;

    let midPrice = 65000.0;
    if (initialBestBid !== null && initialBestAsk !== null) {
      midPrice = (initialBestBid + initialBestAsk) / 2.0;
    } else if (initialBestBid !== null) {
      midPrice = initialBestBid;
    } else if (initialBestAsk !== null) {
      midPrice = initialBestAsk;
    }

    // Filter outliers within ±10% of mid-price to preserve visual depth scale
    const minPrice = midPrice * 0.90;
    const maxPrice = midPrice * 1.10;

    const filteredBids = rawBids
      .filter(([px]) => px >= minPrice && px <= maxPrice)
      .slice(0, 25);

    const filteredAsks = rawAsks
      .filter(([px]) => px >= minPrice && px <= maxPrice)
      .slice(0, 25);

    const bestBid = filteredBids.length > 0 ? filteredBids[0][0] : initialBestBid;
    const bestAsk = filteredAsks.length > 0 ? filteredAsks[0][0] : initialBestAsk;
    let spread: number | null = null;
    let spreadPercent: number | null = null;

    if (bestBid !== null && bestAsk !== null) {
      spread = Math.round((bestAsk - bestBid) * 100) / 100;
      spreadPercent = Math.round(((bestAsk - bestBid) / bestAsk) * 10000) / 100;
    }

    setOrderBook({
      symbol,
      bids: filteredBids,
      asks: filteredAsks,
      bestBid,
      bestAsk,
      spread,
      spreadPercent,
    });
  }, [symbol]);

  const connect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    try {
      const url = getWsUrl();
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        // Subscribe to channels
        const subMsg = {
          action: 'subscribe',
          channels: ['book_l2', 'trades', 'telemetry'],
          symbol,
        };
        ws.send(JSON.stringify(subMsg));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          const channel = msg.channel;
          const msgType = msg.type;

          if (channel === 'book_l2') {
            if (msgType === 'snapshot') {
              activeBidsRef.current.clear();
              activeAsksRef.current.clear();
              for (const [px, vol, cnt] of msg.bids || []) {
                const normPx = normalizePrice(px);
                const normVol = normalizeQty(vol);
                activeBidsRef.current.set(normPx, [normVol, Number(cnt) || 1]);
              }
              for (const [px, vol, cnt] of msg.asks || []) {
                const normPx = normalizePrice(px);
                const normVol = normalizeQty(vol);
                activeAsksRef.current.set(normPx, [normVol, Number(cnt) || 1]);
              }
              updateOrderBookState();
            } else if (msgType === 'diff') {
              // Apply diffs
              for (const [px, vol, cnt] of msg.bids || []) {
                const normPx = normalizePrice(px);
                const normVol = normalizeQty(vol);
                if (normVol <= 0) {
                  activeBidsRef.current.delete(normPx);
                } else {
                  activeBidsRef.current.set(normPx, [normVol, Number(cnt) || 1]);
                }
              }
              for (const [px, vol, cnt] of msg.asks || []) {
                const normPx = normalizePrice(px);
                const normVol = normalizeQty(vol);
                if (normVol <= 0) {
                  activeAsksRef.current.delete(normPx);
                } else {
                  activeAsksRef.current.set(normPx, [normVol, Number(cnt) || 1]);
                }
              }
              updateOrderBookState();
            }
          } else if (channel === 'trades' && msgType === 'trade') {
            const trade: TradeEvent = {
              trade_id: Number(msg.trade_id),
              symbol: msg.symbol,
              price: normalizePrice(msg.price),
              price_str: msg.price_str,
              quantity: normalizeQty(msg.quantity),
              quantity_str: msg.quantity_str,
              quote_amount: normalizePrice(msg.quote_amount),
              maker_side: msg.maker_side,
              taker_side: msg.taker_side,
              timestamp_ms: Number(msg.timestamp_ms) || Date.now(),
            };

            setTrades((prev) => [trade, ...prev.slice(0, 49)]);
          }
 else if (channel === 'telemetry') {
            setTelemetry(msg.data);
          }
        } catch (err) {
          console.warn('[WebSocket Parse Error]', err);
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        wsRef.current = null;
        // Exponential/constant backoff reconnect
        reconnectTimeoutRef.current = window.setTimeout(connect, 1500);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch (e) {
      setIsConnected(false);
      reconnectTimeoutRef.current = window.setTimeout(connect, 2000);
    }
  }, [getWsUrl, symbol, updateOrderBookState]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return {
    isConnected,
    orderBook,
    trades,
    telemetry,
  };
}
