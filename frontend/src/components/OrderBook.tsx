import React, { useMemo } from 'react';
import { OrderBookState } from '../types';
import { formatPrice, formatQty, normalizePrice, normalizeQty } from '../utils/formatters';

interface OrderBookProps {
  orderBook: OrderBookState;
  onSelectPrice?: (price: number) => void;
}

export const OrderBook: React.FC<OrderBookProps> = ({ orderBook, onSelectPrice }) => {
  const { bids, asks, spread, spreadPercent, bestBid } = orderBook;

  // Compute maximum cumulative volume for depth fill bars with strict numeric additions
  const { asksWithCumulative, bidsWithCumulative, maxTotalVolume } = useMemo(() => {
    // Outlier filter safeguard: within ±10% of mid-price
    const firstAsk = asks && asks.length > 0 ? normalizePrice(asks[0][0]) : null;
    const mid = (bestBid && firstAsk) ? (bestBid + firstAsk) / 2 : (bestBid || firstAsk || 65000);
    const minP = mid * 0.90;
    const maxP = mid * 1.10;

    let askCum = 0;
    const asksWithCum: [number, number, number, number][] = [];
    const topAsks = (asks || [])
      .map(([rawPx, rawVol, cnt]) => [normalizePrice(rawPx), normalizeQty(rawVol), Number(cnt) || 1] as [number, number, number])
      .filter(([px, vol]) => px >= minP && px <= maxP && vol > 0)
      .slice(0, 18);

    for (const [px, vol, cnt] of topAsks) {
      askCum = Number(askCum) + Number(vol);
      asksWithCum.push([px, vol, cnt, askCum]);
    }

    let bidCum = 0;
    const bidsWithCum: [number, number, number, number][] = [];
    const topBids = (bids || [])
      .map(([rawPx, rawVol, cnt]) => [normalizePrice(rawPx), normalizeQty(rawVol), Number(cnt) || 1] as [number, number, number])
      .filter(([px, vol]) => px >= minP && px <= maxP && vol > 0)
      .slice(0, 18);

    for (const [px, vol, cnt] of topBids) {
      bidCum = Number(bidCum) + Number(vol);
      bidsWithCum.push([px, vol, cnt, bidCum]);
    }

    const maxVol = Math.max(askCum, bidCum, 1.0);
    return {
      asksWithCumulative: asksWithCum,
      bidsWithCumulative: bidsWithCum,
      maxTotalVolume: maxVol,
    };
  }, [asks, bids, bestBid]);

  return (
    <div className="w-72 bg-terminal-surface border-r border-terminal-border flex flex-col h-full select-none text-[11px] font-mono shrink-0">
      {/* Table Header */}
      <div className="h-8 border-b border-terminal-border flex items-center justify-between px-3 text-terminal-muted font-sans font-semibold text-[10px] uppercase">
        <span>Price (USDT)</span>
        <span className="text-right">Size (BTC)</span>
        <span className="text-right">Total</span>
      </div>

      {/* Asks (Sells) - Rendered in reverse so lowest ask is closest to spread */}
      <div className="flex-1 overflow-hidden flex flex-col justify-end py-1">
        {asksWithCumulative
          .slice()
          .reverse()
          .map(([px, vol, _cnt, cum]: [number, number, number, number]) => {
            const depthPct = Math.min(100, Math.round((cum / maxTotalVolume) * 100));
            return (
              <div
                key={`ask-${px}`}
                onClick={() => onSelectPrice && onSelectPrice(px)}
                className="relative flex items-center justify-between px-3 py-[2px] cursor-pointer hover:bg-terminal-card group transition-colors"
              >
                {/* Red Depth Bar Fill */}
                <div
                  className="absolute right-0 top-0 bottom-0 bg-trade-sellSoft pointer-events-none transition-all duration-75"
                  style={{ width: `${depthPct}%` }}
                />
                <span className="text-trade-sell font-semibold z-10">
                  {formatPrice(px, 2)}
                </span>
                <span className="text-terminal-text z-10 text-right">{formatQty(vol, 4)}</span>
                <span className="text-terminal-muted z-10 text-right">{formatQty(cum, 4)}</span>
              </div>
            );
          })}
      </div>

      {/* Mid Spread Row */}
      <div className="h-9 bg-terminal-card border-y border-terminal-border flex items-center justify-between px-3 shrink-0">
        <div className="flex items-baseline gap-2">
          <span className="text-xs font-bold text-terminal-text">
            {bestBid ? `$${formatPrice(bestBid, 2)}` : '---'}
          </span>
          <span className="text-[10px] text-terminal-muted">Spread</span>
        </div>
        <div className="text-right">
          <span className="text-terminal-muted font-bold block text-[10px]">
            {spread !== null ? `$${formatPrice(spread, 2)}` : '0.00'}
          </span>
          <span className="text-[9px] text-terminal-muted block">
            {spreadPercent !== null ? `${spreadPercent.toFixed(2)}%` : '0.00%'}
          </span>
        </div>
      </div>

      {/* Bids (Buys) */}
      <div className="flex-1 overflow-hidden flex flex-col py-1">
        {bidsWithCumulative.map(([px, vol, _cnt, cum]: [number, number, number, number]) => {
          const depthPct = Math.min(100, Math.round((cum / maxTotalVolume) * 100));
          return (
            <div
              key={`bid-${px}`}
              onClick={() => onSelectPrice && onSelectPrice(px)}
              className="relative flex items-center justify-between px-3 py-[2px] cursor-pointer hover:bg-terminal-card group transition-colors"
            >
              {/* Green Depth Bar Fill */}
              <div
                className="absolute right-0 top-0 bottom-0 bg-trade-buySoft pointer-events-none transition-all duration-75"
                style={{ width: `${depthPct}%` }}
              />
              <span className="text-trade-buy font-semibold z-10">
                {formatPrice(px, 2)}
              </span>
              <span className="text-terminal-text z-10 text-right">{formatQty(vol, 4)}</span>
              <span className="text-terminal-muted z-10 text-right">{formatQty(cum, 4)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};
