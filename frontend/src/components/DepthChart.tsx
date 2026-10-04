import React, { useEffect, useRef } from 'react';
import { OrderBookState } from '../types';
import { normalizePrice, normalizeQty, formatPrice } from '../utils/formatters';

interface DepthChartProps {
  orderBook: OrderBookState;
}

export const DepthChart: React.FC<DepthChartProps> = ({ orderBook }) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Handle high-DPI retina display
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const width = rect.width;
    const height = rect.height;

    // Clear background
    ctx.fillStyle = '#0b0e11';
    ctx.fillRect(0, 0, width, height);

    const { bids, asks, bestBid, bestAsk, spread } = orderBook;
    if (!bids || !asks || (bids.length === 0 && asks.length === 0)) return;

    // 1. Calculate cumulative volumes
    // Bids are sorted descending (bids[0] is best_bid). Cumulative volume grows as we move away from best_bid.
    let bidSum = 0;
    const bidPoints: { px: number; cum: number }[] = [];
    for (const [rawPx, rawVol] of bids) {
      const px = normalizePrice(rawPx);
      const vol = normalizeQty(rawVol);
      if (px > 0 && vol > 0) {
        bidSum = Number(bidSum) + Number(vol);
        bidPoints.push({ px, cum: bidSum });
      }
    }

    // Asks are sorted ascending (asks[0] is best_ask). Cumulative volume grows as we move away from best_ask.
    let askSum = 0;
    const askPoints: { px: number; cum: number }[] = [];
    for (const [rawPx, rawVol] of asks) {
      const px = normalizePrice(rawPx);
      const vol = normalizeQty(rawVol);
      if (px > 0 && vol > 0) {
        askSum = Number(askSum) + Number(vol);
        askPoints.push({ px, cum: askSum });
      }
    }

    const maxCumulativeVolume = Math.max(bidSum, askSum, 1.0);
    const midpoint = width / 2;
    const topMargin = 22; // Reserve space for header legends
    const bottomMargin = 16; // Reserve space for bottom price ticks
    const usableHeight = height - topMargin - bottomMargin;

    // 2. Draw Bids (Left half, green: center -> left)
    if (bidPoints.length > 0) {
      const numBids = bidPoints.length;

      // Coordinate mapping:
      // index 0 (best_bid, lowest cum) is at midpoint.
      // index numBids - 1 (lowest bid, highest cum) is at x = 0.
      const bidCoords = bidPoints.map((pt, i) => {
        const frac = numBids > 1 ? i / (numBids - 1) : 1;
        const x = midpoint - frac * midpoint;
        const y = height - bottomMargin - (pt.cum / maxCumulativeVolume) * usableHeight;
        return { x, y, px: pt.px, cum: pt.cum };
      });

      // Green Polygon Fill
      ctx.beginPath();
      ctx.moveTo(midpoint, height - bottomMargin); // Center bottom
      ctx.lineTo(midpoint, bidCoords[0].y); // Up to best bid
      for (const pt of bidCoords) {
        ctx.lineTo(pt.x, pt.y);
      }
      ctx.lineTo(0, height - bottomMargin); // Down to left bottom
      ctx.closePath();

      const bidGrad = ctx.createLinearGradient(0, topMargin, 0, height - bottomMargin);
      bidGrad.addColorStop(0, 'rgba(14, 203, 129, 0.30)');
      bidGrad.addColorStop(1, 'rgba(14, 203, 129, 0.03)');
      ctx.fillStyle = bidGrad;
      ctx.fill();

      // Green Line Stroke (along top profile only)
      ctx.beginPath();
      ctx.moveTo(midpoint, bidCoords[0].y);
      for (const pt of bidCoords) {
        ctx.lineTo(pt.x, pt.y);
      }
      ctx.strokeStyle = '#0ecb81';
      ctx.lineWidth = 1.75;
      ctx.stroke();
    }

    // 3. Draw Asks (Right half, red: center -> right)
    if (askPoints.length > 0) {
      const numAsks = askPoints.length;

      // Coordinate mapping:
      // index 0 (best_ask, lowest cum) is at midpoint.
      // index numAsks - 1 (highest ask, highest cum) is at x = width.
      const askCoords = askPoints.map((pt, i) => {
        const frac = numAsks > 1 ? i / (numAsks - 1) : 1;
        const x = midpoint + frac * (width - midpoint);
        const y = height - bottomMargin - (pt.cum / maxCumulativeVolume) * usableHeight;
        return { x, y, px: pt.px, cum: pt.cum };
      });

      // Red Polygon Fill
      ctx.beginPath();
      ctx.moveTo(midpoint, height - bottomMargin); // Center bottom
      ctx.lineTo(midpoint, askCoords[0].y); // Up to best ask
      for (const pt of askCoords) {
        ctx.lineTo(pt.x, pt.y);
      }
      ctx.lineTo(width, height - bottomMargin); // Down to right bottom
      ctx.closePath();

      const askGrad = ctx.createLinearGradient(0, topMargin, 0, height - bottomMargin);
      askGrad.addColorStop(0, 'rgba(246, 70, 93, 0.30)');
      askGrad.addColorStop(1, 'rgba(246, 70, 93, 0.03)');
      ctx.fillStyle = askGrad;
      ctx.fill();

      // Red Line Stroke (along top profile only)
      ctx.beginPath();
      ctx.moveTo(midpoint, askCoords[0].y);
      for (const pt of askCoords) {
        ctx.lineTo(pt.x, pt.y);
      }
      ctx.strokeStyle = '#f6465d';
      ctx.lineWidth = 1.75;
      ctx.stroke();
    }

    // 4. Central Divider
    ctx.strokeStyle = '#2b313a';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(midpoint, topMargin);
    ctx.lineTo(midpoint, height - bottomMargin);
    ctx.stroke();
    ctx.setLineDash([]);

    // 5. Price & Spread Labels at Bottom
    ctx.fillStyle = '#848e9c';
    ctx.font = '10px JetBrains Mono, monospace';
    ctx.textBaseline = 'bottom';

    // Lowest Bid (bottom left)
    if (bidPoints.length > 0) {
      const minBid = bidPoints[bidPoints.length - 1].px;
      ctx.textAlign = 'left';
      ctx.fillText(`$${formatPrice(minBid, 2)}`, 8, height - 2);
    }

    // Mid Spread (bottom center)
    if (bestBid !== null && bestAsk !== null) {
      const midPx = (bestBid + bestAsk) / 2;
      ctx.textAlign = 'center';
      ctx.fillStyle = '#eaecef';
      ctx.fillText(`$${formatPrice(midPx, 2)} (Spread $${formatPrice(spread, 2)})`, midpoint, height - 2);
    }

    // Highest Ask (bottom right)
    if (askPoints.length > 0) {
      const maxAsk = askPoints[askPoints.length - 1].px;
      ctx.textAlign = 'right';
      ctx.fillStyle = '#848e9c';
      ctx.fillText(`$${formatPrice(maxAsk, 2)}`, width - 8, height - 2);
    }
  }, [orderBook]);

  return (
    <div className="h-36 bg-terminal-bg border-t border-terminal-border relative shrink-0">
      <div className="absolute top-2 left-3 z-10 text-[10px] font-mono text-terminal-muted flex items-center gap-3">
        <span className="font-semibold uppercase tracking-wider">Depth Chart</span>
        <span className="flex items-center gap-1 text-trade-buy">
          <span className="w-2 h-2 rounded-full bg-trade-buy" /> Bids (Buy Depth)
        </span>
        <span className="flex items-center gap-1 text-trade-sell">
          <span className="w-2 h-2 rounded-full bg-trade-sell" /> Asks (Sell Depth)
        </span>
      </div>
      <canvas ref={canvasRef} className="w-full h-full block" />
    </div>
  );
};
