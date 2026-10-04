import React, { useState } from 'react';
import { ErrorBoundary } from './components/ErrorBoundary';
import { Header } from './components/Header';
import { CandlestickChart } from './components/CandlestickChart';
import { DepthChart } from './components/DepthChart';
import { OrderBook } from './components/OrderBook';
import { RecentTrades } from './components/RecentTrades';
import { OrderForm } from './components/OrderForm';
import { TelemetryBar } from './components/TelemetryBar';
import { useWebSocket } from './hooks/useWebSocket';

export const App: React.FC = () => {
  const [symbol] = useState<string>('BTC-USDT');
  const [selectedPrice, setSelectedPrice] = useState<number | null>(null);

  // Real-time WebSocket connection to Gateway
  const { isConnected, orderBook, trades, telemetry } = useWebSocket({ symbol });

  const latestTrade = trades.length > 0 ? trades[0] : null;

  return (
    <ErrorBoundary>
      <div className="h-screen w-screen flex flex-col bg-[#0b0e11] text-gray-200 overflow-hidden font-sans">
        {/* Top Header & 24h Market Stats */}
        <Header
          symbol={symbol}
          latestTrade={latestTrade}
          isConnected={isConnected}
        />

        {/* Central Trading Workplace */}
        <div className="flex-1 flex overflow-hidden">
          {/* Left Panel: Order Submission Form */}
          <div className="w-80 border-r border-[#1e2329] bg-[#0b0e11] flex flex-col p-2 gap-2 overflow-y-auto shrink-0 scrollbar-thin">
            <OrderForm
              symbol={symbol}
              selectedPrice={selectedPrice}
              onOrderPlaced={() => setSelectedPrice(null)}
            />

            {/* Quick Engine Status Card */}
            <div className="p-3 bg-[#12161c] border border-[#1e2329] rounded text-[11px] font-mono text-gray-400">
              <div className="text-gray-300 font-semibold mb-2 flex items-center justify-between">
                <span>EXECUTION ENGINE</span>
                <span className="text-[#0ecb81] text-[10px]">DETERMINISTIC L3</span>
              </div>
              <div className="space-y-1 text-[10px]">
                <div className="flex justify-between">
                  <span className="text-gray-500">Matching Mode:</span>
                  <span className="text-gray-300">Single-Thread FIFO</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Scale:</span>
                  <span className="text-gray-300">Fixed-Point (10^8)</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Time-In-Force:</span>
                  <span className="text-gray-300">GTC, IOC, FOK</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Data Bus:</span>
                  <span className="text-gray-300">Redpanda Event Journal</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Analytics:</span>
                  <span className="text-gray-300">ClickHouse OLAP</span>
                </div>
              </div>
            </div>
          </div>

          {/* Center Panel: Interactive Financial Charts */}
          <div className="flex-1 flex flex-col overflow-hidden min-w-0">
            <div className="flex-1 min-h-0">
              <CandlestickChart symbol={symbol} latestTrade={latestTrade} />
            </div>
            <DepthChart orderBook={orderBook} />
          </div>

          {/* Right Panel: L2 Order Book & Recent Trades */}
          <div className="flex shrink-0">
            {/* Order Book L2 */}
            <OrderBook
              orderBook={orderBook}
              onSelectPrice={(px) => setSelectedPrice(px)}
            />

            {/* Recent Executions Stream */}
            <div className="w-64 border-l border-[#1e2329] p-1 bg-[#0b0e11]">
              <RecentTrades trades={trades} />
            </div>
          </div>
        </div>

        {/* Bottom Docked Telemetry Ribbon */}
        <TelemetryBar isConnected={isConnected} telemetry={telemetry} />
      </div>
    </ErrorBoundary>
  );
};

export default App;
