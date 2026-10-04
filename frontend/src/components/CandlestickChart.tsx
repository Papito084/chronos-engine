import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CandlestickData,
  UTCTimestamp,
  PriceScaleMode,
} from 'lightweight-charts';
import { Clock } from 'lucide-react';
import { TradeEvent } from '../types';
import { normalizePrice } from '../utils/formatters';

interface CandlestickChartProps {
  symbol: string;
  latestTrade: TradeEvent | null;
}

function toUtcTimestamp(rawTime: any): UTCTimestamp {
  if (typeof rawTime === 'number') {
    const sec = rawTime > 1e11 ? Math.floor(rawTime / 1000) : Math.floor(rawTime);
    return sec as UTCTimestamp;
  }
  if (typeof rawTime === 'string') {
    const num = Number(rawTime);
    if (!isNaN(num) && num > 0) {
      const sec = num > 1e11 ? Math.floor(num / 1000) : Math.floor(num);
      return sec as UTCTimestamp;
    }
    const parsed = Math.floor(new Date(rawTime).getTime() / 1000);
    if (!isNaN(parsed) && parsed > 0) {
      return parsed as UTCTimestamp;
    }
  }
  return Math.floor(Date.now() / 1000) as UTCTimestamp;
}

export const CandlestickChart: React.FC<CandlestickChartProps> = ({ symbol, latestTrade }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const activeCandleRef = useRef<CandlestickData | null>(null);
  const lastTimeRef = useRef<number | null>(null);

  const [timeframe, setTimeframe] = useState<'1s' | '1m'>('1s');
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // Initialize TradingView Lightweight Chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: '#0b0e11' },
        textColor: '#848e9c',
        fontSize: 11,
        fontFamily: 'JetBrains Mono, monospace',
      },
      grid: {
        vertLines: { color: '#151a1e' },
        horzLines: { color: '#151a1e' },
      },
      crosshair: {
        vertLine: { color: '#848e9c', width: 1, style: 2 },
        horzLine: { color: '#848e9c', width: 1, style: 2 },
      },
      rightPriceScale: {
        autoScale: true,
        mode: PriceScaleMode.Normal,
        borderColor: '#2b313a',
        scaleMargins: { top: 0.15, bottom: 0.15 },
      },
      timeScale: {
        borderColor: '#2b313a',
        timeVisible: true,
        secondsVisible: timeframe === '1s',
        barSpacing: 10,
        minBarSpacing: 3,
        rightOffset: 5,
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#0ecb81',
      downColor: '#f6465d',
      borderVisible: false,
      wickUpColor: '#0ecb81',
      wickDownColor: '#f6465d',
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    lastTimeRef.current = null;
    activeCandleRef.current = null;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
      }
    };

    window.addEventListener('resize', handleResize);
    handleResize();

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      lastTimeRef.current = null;
      activeCandleRef.current = null;
    };
  }, [timeframe]);

  // Load Historical Candles
  const loadCandles = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`/api/v1/market/candles?symbol=${symbol}&timeframe=${timeframe}&limit=200`);
      if (res.ok) {
        const data: any[] = await res.json();
        if (data && data.length > 0 && candleSeriesRef.current) {
          // Deduplicate by integer second timestamp and map to CandlestickData
          const map = new Map<number, CandlestickData>();
          for (const c of data) {
            const open = normalizePrice(c.open);
            const high = normalizePrice(c.high);
            const low = normalizePrice(c.low);
            const close = normalizePrice(c.close);

            // Sanity check: Filter out corrupt / outlier candles outside realistic trading range
            if (open < 10000 || close < 10000 || low < 10000 || high > 100000) {
              continue;
            }

            const rawTime = c.time ?? c.timestamp ?? c.time_bucket ?? c.bucket ?? c.time_iso;
            const t = toUtcTimestamp(rawTime);
            const tNum = Number(t);
            map.set(tNum, {
              time: t,
              open,
              high,
              low,
              close,
            });
          }

          // Sort strictly ascending
          const sortedCandles = Array.from(map.values()).sort(
            (a, b) => Number(a.time) - Number(b.time)
          );

          if (sortedCandles.length > 0) {
            candleSeriesRef.current.setData(sortedCandles);
            const last = sortedCandles[sortedCandles.length - 1];
            activeCandleRef.current = last;
            lastTimeRef.current = Number(last.time);
            chartRef.current?.timeScale().fitContent();
          }
        } else {
          candleSeriesRef.current?.setData([]);
          activeCandleRef.current = null;
          lastTimeRef.current = null;
        }
      }
    } catch (e) {
      console.warn('[Chart Data Error]', e);
    } finally {
      setIsLoading(false);
    }
  }, [symbol, timeframe]);

  useEffect(() => {
    loadCandles();
  }, [loadCandles]);

  // Incremental real-time update with every live trade from WebSocket
  useEffect(() => {
    if (!latestTrade || !candleSeriesRef.current) return;

    const intervalSec = timeframe === '1s' ? 1 : 60;
    const rawMs = latestTrade.timestamp_ms || Date.now();
    const tradeSec = Math.floor(Number(rawMs) / 1000);
    const bucketSec = Math.floor(tradeSec - (tradeSec % intervalSec));
    const bucketTime = bucketSec as UTCTimestamp;
    const price = normalizePrice(latestTrade.price);

    // Sanity filter: Ignore zero or outlier prices outside [10000, 100000]
    if (price < 10000 || price > 100000) return;

    // Discard trades with older timestamps than the last rendered candle
    if (lastTimeRef.current !== null && bucketSec < lastTimeRef.current) {
      return;
    }

    if (lastTimeRef.current !== null && bucketSec === lastTimeRef.current && activeCandleRef.current) {
      // Same bucket: update High, Low, Close
      const current = activeCandleRef.current;
      const updated: CandlestickData = {
        time: bucketTime,
        open: current.open,
        high: Math.max(current.high, price),
        low: Math.min(current.low, price),
        close: price,
      };
      candleSeriesRef.current.update(updated);
      activeCandleRef.current = updated;
    } else {
      // New bucket: initialize new candle bar
      const newCandle: CandlestickData = {
        time: bucketTime,
        open: price,
        high: price,
        low: price,
        close: price,
      };
      candleSeriesRef.current.update(newCandle);
      activeCandleRef.current = newCandle;
      const isInitial = lastTimeRef.current === null;
      lastTimeRef.current = bucketSec;
      if (isInitial) {
        chartRef.current?.timeScale().fitContent();
      }
    }
  }, [latestTrade, timeframe]);

  return (
    <div className="flex-1 flex flex-col h-full bg-terminal-bg border-r border-terminal-border relative">
      {/* Top Controls Bar */}
      <div className="h-9 border-b border-terminal-border bg-terminal-surface/40 flex items-center justify-between px-3 shrink-0">
        <div className="flex items-center gap-2">
          <Clock className="w-3.5 h-3.5 text-terminal-muted" />
          <span className="text-xs text-terminal-muted font-medium">Timeframe:</span>
          <div className="flex items-center gap-1 bg-terminal-card p-0.5 rounded border border-terminal-border text-xs">
            <button
              onClick={() => setTimeframe('1s')}
              className={`px-2 py-0.5 rounded font-mono font-medium transition-colors ${
                timeframe === '1s'
                  ? 'bg-terminal-border text-trade-buy shadow-sm'
                  : 'text-terminal-muted hover:text-terminal-text'
              }`}
            >
              1s
            </button>
            <button
              onClick={() => setTimeframe('1m')}
              className={`px-2 py-0.5 rounded font-mono font-medium transition-colors ${
                timeframe === '1m'
                  ? 'bg-terminal-border text-trade-buy shadow-sm'
                  : 'text-terminal-muted hover:text-terminal-text'
              }`}
            >
              1m
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2 text-[11px] text-terminal-muted font-mono">
          <span className="inline-block w-2 h-2 rounded-full bg-trade-buy animate-pulse" />
          <span>Real-Time OHLCV (ClickHouse)</span>
        </div>
      </div>

      {/* Chart Canvas Container */}
      <div className="flex-1 w-full h-full relative" ref={chartContainerRef}>
        {isLoading && (
          <div className="absolute inset-0 bg-terminal-bg/80 backdrop-blur-sm flex items-center justify-center z-10">
            <div className="flex items-center gap-2 text-xs font-mono text-terminal-muted">
              <div className="w-3.5 h-3.5 border-2 border-trade-buy border-t-transparent rounded-full animate-spin" />
              <span>Loading Candlesticks...</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
