import React from 'react';
import { TradeEvent } from '../types';
import { formatPrice, formatQty } from '../utils/formatters';

interface RecentTradesProps {
  trades: TradeEvent[];
}

export const RecentTrades: React.FC<RecentTradesProps> = ({ trades }) => {
  const formatTime = (tsMs: number) => {
    const d = new Date(tsMs);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    const s = String(d.getSeconds()).padStart(2, '0');
    const ms = String(d.getMilliseconds()).padStart(3, '0');
    return `${h}:${m}:${s}.${ms}`;
  };

  return (
    <div className="flex flex-col h-full bg-[#12161c] border border-[#1e2329] rounded select-none text-xs">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#1e2329] bg-[#0b0e11]">
        <span className="font-semibold text-gray-200">Recent Trades</span>
        <span className="text-[10px] text-gray-500 font-mono">Real-time</span>
      </div>

      {/* Column Titles */}
      <div className="grid grid-cols-3 px-3 py-1.5 text-[10px] text-gray-500 uppercase tracking-wider border-b border-[#1e2329]/50">
        <div className="text-left">Price (USDT)</div>
        <div className="text-right">Qty (BTC)</div>
        <div className="text-right">Time</div>
      </div>

      {/* Trades List */}
      <div className="flex-1 overflow-y-auto font-mono scrollbar-thin">
        {trades.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-gray-500 text-xs">
            Waiting for market executions...
          </div>
        ) : (
          trades.slice(0, 50).map((trade, idx) => {
            const isBuy = trade.taker_side === 'BUY';
            return (
              <div
                key={`${trade.trade_id}-${trade.timestamp_ms}-${idx}`}
                className="grid grid-cols-3 px-3 py-0.5 hover:bg-[#1e2329]/40 transition-colors duration-75 text-[11px]"
              >
                <div className={`text-left font-medium ${isBuy ? 'text-[#0ecb81]' : 'text-[#f6465d]'}`}>
                  {formatPrice(trade.price, 2)}
                </div>
                <div className="text-right text-gray-300">
                  {formatQty(trade.quantity, 4)}
                </div>
                <div className="text-right text-gray-500 text-[10px]">
                  {formatTime(trade.timestamp_ms)}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
