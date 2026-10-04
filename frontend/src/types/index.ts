export type OrderBookLevel = [number, number, number]; // [price, volume, order_count]

export interface OrderBookState {
  symbol: string;
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
  bestBid: number | null;
  bestAsk: number | null;
  spread: number | null;
  spreadPercent: number | null;
}

export interface TradeEvent {
  trade_id: number;
  symbol: string;
  price: number;
  price_str?: string;
  quantity: number;
  quantity_str?: string;
  quote_amount: number;
  maker_side: 'BUY' | 'SELL';
  taker_side: 'BUY' | 'SELL';
  timestamp_ms: number;
}

export interface MarketSummary {
  symbol: string;
  high_24h: number;
  low_24h: number;
  volume_24h: number;
  quote_volume_24h: number;
  vwap_24h: number;
  trade_count_24h: number;
}

export interface TelemetryMetrics {
  timestamp_ms: number;
  p50_latency_us: number;
  p90_latency_us: number;
  p99_latency_us: number;
  mean_latency_us: number;
  min_latency_us: number;
  max_latency_us: number;
  ops_per_sec: number;
  total_orders: number;
  total_trades: number;
  active_orders: number;
  memory_mb: number;
  cpu_percent: number;
}

export interface CandleData {
  time: number; // Unix timestamp in seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
