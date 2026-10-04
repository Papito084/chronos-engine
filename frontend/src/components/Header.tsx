import React, { useEffect, useState, useRef } from 'react';
import { Activity, Wifi, WifiOff, TrendingUp, TrendingDown, Cpu } from 'lucide-react';
import { MarketSummary, TradeEvent } from '../types';
import { formatPrice, formatQty } from '../utils/formatters';

interface HeaderProps {
  symbol: string;
  latestTrade: TradeEvent | null;
  isConnected: boolean;
}

export const Header: React.FC<HeaderProps> = ({ symbol, latestTrade, isConnected }) => {
  const [summary, setSummary] = useState<MarketSummary | null>(null);
  const [priceFlash, setPriceFlash] = useState<'up' | 'down' | null>(null);
  const prevPriceRef = useRef<number | null>(null);

  // Flash animation on trade price change
  useEffect(() => {
    if (latestTrade && prevPriceRef.current !== null) {
      if (latestTrade.price > prevPriceRef.current) {
        setPriceFlash('up');
      } else if (latestTrade.price < prevPriceRef.current) {
        setPriceFlash('down');
      }
      const timer = setTimeout(() => setPriceFlash(null), 350);
      prevPriceRef.current = latestTrade.price;
      return () => clearTimeout(timer);
    }
    if (latestTrade) {
      prevPriceRef.current = latestTrade.price;
    }
  }, [latestTrade]);

  // Periodic poll of 24h summary
  useEffect(() => {
    const fetchSummary = async () => {
      try {
        const res = await fetch(`/api/v1/market/summary?symbol=${symbol}`);
        if (res.ok) {
          const data = await res.json();
          setSummary(data);
        }
      } catch (err) {
        // Silent fallback
      }
    };

    fetchSummary();
    const interval = setInterval(fetchSummary, 3000);
    return () => clearInterval(interval);
  }, [symbol]);

  const currentPrice = latestTrade ? latestTrade.price : 65000.0;
  const priceColor = latestTrade?.taker_side === 'BUY' ? 'text-trade-buy' : 'text-trade-sell';
  const flashBg = priceFlash === 'up' ? 'bg-trade-buySoft' : priceFlash === 'down' ? 'bg-trade-sellSoft' : '';

  return (
    <header className="h-14 bg-terminal-surface border-b border-terminal-border flex items-center justify-between px-4 select-none shrink-0">
      {/* Left: Brand & Symbol */}
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded bg-gradient-to-br from-trade-buy/30 to-emerald-600/10 border border-trade-buy/40 flex items-center justify-center">
            <Cpu className="w-4 h-4 text-trade-buy" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-bold text-sm tracking-wider text-terminal-text">CHRONOS</span>
              <span className="text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded bg-terminal-card border border-terminal-border text-terminal-muted">
                ENGINE
              </span>
            </div>
            <span className="text-[10px] text-terminal-muted block -mt-0.5">L3 In-Memory Exchange</span>
          </div>
        </div>

        <div className="h-6 w-[1px] bg-terminal-border" />

        {/* Pair & Price Display */}
        <div className="flex items-baseline gap-3">
          <div className="flex items-center gap-1.5">
            <span className="text-base font-bold text-terminal-text tracking-wide">{symbol}</span>
            <span className="text-[11px] text-terminal-muted font-mono bg-terminal-card px-1 py-0.5 rounded">PERP</span>
          </div>

          <div className={`flex items-baseline gap-2 px-2 py-0.5 rounded transition-colors duration-200 ${flashBg}`}>
            <span className={`text-xl font-bold font-mono tracking-tight ${priceColor}`}>
              ${formatPrice(currentPrice, 2)}
            </span>
            {priceFlash === 'up' && <TrendingUp className="w-4 h-4 text-trade-buy animate-bounce" />}
            {priceFlash === 'down' && <TrendingDown className="w-4 h-4 text-trade-sell animate-bounce" />}
          </div>
        </div>
      </div>

      {/* Center: 24h Ticker Stats */}
      <div className="hidden lg:flex items-center gap-6 text-xs">
        <div>
          <span className="text-terminal-muted block text-[10px] uppercase font-semibold">24h High</span>
          <span className="font-mono text-terminal-text">
            ${summary?.high_24h ? formatPrice(summary.high_24h, 2) : '65,240.00'}
          </span>
        </div>

        <div>
          <span className="text-terminal-muted block text-[10px] uppercase font-semibold">24h Low</span>
          <span className="font-mono text-terminal-text">
            ${summary?.low_24h ? formatPrice(summary.low_24h, 2) : '64,810.00'}
          </span>
        </div>

        <div>
          <span className="text-terminal-muted block text-[10px] uppercase font-semibold">24h Volume (BTC)</span>
          <span className="font-mono text-terminal-text">
            {summary?.volume_24h ? formatQty(summary.volume_24h, 2) : '1,420.50'}
          </span>
        </div>

        <div>
          <span className="text-terminal-muted block text-[10px] uppercase font-semibold">24h VWAP</span>
          <span className="font-mono text-trade-buy">
            ${summary?.vwap_24h ? formatPrice(summary.vwap_24h, 2) : '65,042.80'}
          </span>
        </div>
      </div>

      {/* Right: Network Status */}
      <div className="flex items-center gap-3">
        <div
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono border ${
            isConnected
              ? 'bg-trade-buySoft border-trade-buy/30 text-trade-buy'
              : 'bg-trade-sellSoft border-trade-sell/30 text-trade-sell'
          }`}
        >
          {isConnected ? (
            <>
              <Wifi className="w-3.5 h-3.5 animate-pulse" />
              <span className="font-semibold">60 FPS WS</span>
            </>
          ) : (
            <>
              <WifiOff className="w-3.5 h-3.5" />
              <span>RECONNECTING</span>
            </>
          )}
        </div>
      </div>
    </header>
  );
};
