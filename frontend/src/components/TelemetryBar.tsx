import React from 'react';
import { TelemetryMetrics } from '../types';
import { Activity, Cpu, Database, Zap, Radio } from 'lucide-react';

interface TelemetryBarProps {
  isConnected: boolean;
  telemetry: TelemetryMetrics | null;
}

export const TelemetryBar: React.FC<TelemetryBarProps> = ({
  isConnected,
  telemetry,
}) => {
  const formatLatency = (val?: number) => {
    if (val == null) return '-- µs';
    return `${val.toFixed(1)} µs`;
  };

  const getLatencyColor = (val?: number) => {
    if (val == null) return 'text-gray-400';
    if (val < 15) return 'text-[#0ecb81]';
    if (val < 50) return 'text-yellow-400';
    return 'text-[#f6465d]';
  };

  return (
    <footer className="h-8 bg-[#0b0e11] border-t border-[#1e2329] px-4 flex items-center justify-between text-[11px] font-mono text-gray-400 select-none z-20">
      {/* Left Section: Connection Status & Engine Heartbeat */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-1.5">
          <div
            className={`w-2 h-2 rounded-full ${
              isConnected
                ? 'bg-[#0ecb81] shadow-[0_0_8px_rgba(14,203,129,0.7)] animate-pulse'
                : 'bg-[#f6465d] shadow-[0_0_8px_rgba(246,70,93,0.7)]'
            }`}
          />
          <span className="font-semibold text-gray-200">
            {isConnected ? 'WS CONNECTED' : 'WS RECONNECTING'}
          </span>
        </div>

        <span className="text-[#1e2329]">|</span>

        <div className="flex items-center gap-1">
          <Radio className="w-3.5 h-3.5 text-blue-400" />
          <span>Gateway: <strong className="text-gray-200">8000</strong></span>
        </div>

        <span className="text-[#1e2329]">|</span>

        <div className="flex items-center gap-1">
          <Database className="w-3.5 h-3.5 text-purple-400" />
          <span>ClickHouse: <strong className="text-gray-200">ONLINE</strong></span>
        </div>
      </div>

      {/* Center / Right Section: Latency Metrics & Throughput */}
      <div className="flex items-center gap-5">
        {/* Latency Percentiles */}
        <div className="flex items-center gap-3">
          <span className="text-gray-500 flex items-center gap-1">
            <Zap className="w-3.5 h-3.5 text-yellow-500" /> Latency:
          </span>
          <div>
            P50: <strong className={getLatencyColor(telemetry?.p50_latency_us)}>
              {formatLatency(telemetry?.p50_latency_us)}
            </strong>
          </div>
          <div>
            P90: <strong className={getLatencyColor(telemetry?.p90_latency_us)}>
              {formatLatency(telemetry?.p90_latency_us)}
            </strong>
          </div>
          <div>
            P99: <strong className={getLatencyColor(telemetry?.p99_latency_us)}>
              {formatLatency(telemetry?.p99_latency_us)}
            </strong>
          </div>
        </div>

        <span className="text-[#1e2329]">|</span>

        {/* Throughput */}
        <div className="flex items-center gap-1">
          <Activity className="w-3.5 h-3.5 text-cyan-400" />
          <span>Ops/sec:</span>
          <strong className="text-cyan-300">
            {telemetry?.ops_per_sec?.toLocaleString('en-US') || '0'}
          </strong>
        </div>

        <span className="text-[#1e2329]">|</span>

        {/* Total Events / Orders */}
        <div>
          Orders: <strong className="text-gray-200">{telemetry?.total_orders?.toLocaleString() || '0'}</strong>
        </div>

        <div>
          Active: <strong className="text-gray-200">{telemetry?.active_orders?.toLocaleString() || '0'}</strong>
        </div>

        <div>
          Trades: <strong className="text-gray-200">{telemetry?.total_trades?.toLocaleString() || '0'}</strong>
        </div>

        <span className="text-[#1e2329]">|</span>

        {/* Resource Usage */}
        <div className="flex items-center gap-1">
          <Cpu className="w-3.5 h-3.5 text-orange-400" />
          <span>Mem:</span>
          <strong className="text-gray-200">
            {telemetry ? `${telemetry.memory_mb.toFixed(1)} MB` : '-- MB'}
          </strong>
        </div>
      </div>
    </footer>
  );
};
