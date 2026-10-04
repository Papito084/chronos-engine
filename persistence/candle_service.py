"""
ChronosEngine - Financial Candle & Market Data Query Service.
Executes analytical queries against ClickHouse AggregatingMergeTree views and Trades log:
- get_candles (1s / 1m OHLCV)
- get_recent_trades
- get_market_summary_24h (VWAP, High, Low, 24h Volume)
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
import clickhouse_connect
from clickhouse_connect.driver.client import Client
from core.models.types import from_fixed_point, fixed_to_str


class CandleService:
    """
    Query service providing consolidated financial series from ClickHouse.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8123,
        database: str = "chronos",
        username: str = "default",
        password: str = "",
        client: Optional[Client] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self._client: Optional[Client] = client

    def get_client(self) -> Client:
        if self._client is None:
            self._client = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                database=self.database,
                username=self.username,
                password=self.password,
            )
        return self._client

    def get_candles(
        self,
        symbol: str,
        timeframe: str = "1s",
        limit: int = 100,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves consolidated OHLCV candles from materialized view.
        Supported timeframes: '1s', '1m'.
        """
        table_name = "candles_1s" if timeframe == "1s" else "candles_1m"
        client = self.get_client()

        where_clauses = ["symbol = %(symbol)s"]
        params: Dict[str, Any] = {"symbol": symbol, "limit": limit}

        if start_time:
            where_clauses.append("time_bucket >= %(start_time)s")
            params["start_time"] = start_time
        if end_time:
            where_clauses.append("time_bucket <= %(end_time)s")
            params["end_time"] = end_time

        where_sql = " AND ".join(where_clauses)
        query = f"""
            SELECT
                toUnixTimestamp(time_bucket) AS timestamp,
                time_bucket,
                symbol,
                open,
                high,
                low,
                close,
                volume,
                quote_volume,
                trade_count
            FROM {self.database}.{table_name}
            WHERE {where_sql}
            ORDER BY time_bucket DESC
            LIMIT %(limit)s
        """

        result = client.query(query, parameters=params)
        candles = []
        for row in reversed(result.result_rows):
            # Parse row
            ts_unix, tb, sym, o, h, l, c, v, qv, tc = row
            candles.append({
                "time": ts_unix,
                "time_iso": tb.isoformat() if isinstance(tb, datetime) else str(tb),
                "symbol": sym,
                "open": from_fixed_point(o),
                "high": from_fixed_point(h),
                "low": from_fixed_point(l),
                "close": from_fixed_point(c),
                "open_fixed": o,
                "high_fixed": h,
                "low_fixed": l,
                "close_fixed": c,
                "volume": from_fixed_point(v),
                "volume_fixed": v,
                "quote_volume": from_fixed_point(qv),
                "quote_volume_fixed": qv,
                "trade_count": tc,
            })

        return candles

    def get_recent_trades(
        self,
        symbol: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieves the latest execution ticks for a given symbol."""
        client = self.get_client()
        query = f"""
            SELECT
                trade_id,
                symbol,
                maker_order_id,
                taker_order_id,
                price,
                quantity,
                quote_amount,
                taker_side,
                timestamp_ns,
                sequence_number
            FROM {self.database}.trades
            WHERE symbol = %(symbol)s
            ORDER BY timestamp_ns DESC, sequence_number DESC
            LIMIT %(limit)s
        """
        res = client.query(query, parameters={"symbol": symbol, "limit": limit})
        trades = []
        for row in res.result_rows:
            tid, sym, m_id, t_id, px, qty, q_amt, side, ts, seq = row
            trades.append({
                "trade_id": tid,
                "symbol": sym,
                "maker_order_id": m_id,
                "taker_order_id": t_id,
                "price": from_fixed_point(px),
                "price_fixed": px,
                "quantity": from_fixed_point(qty),
                "quantity_fixed": qty,
                "quote_amount": from_fixed_point(q_amt),
                "quote_amount_fixed": q_amt,
                "taker_side": side,
                "timestamp": ts.isoformat() if isinstance(ts, datetime) else str(ts),
                "sequence_number": seq,
            })
        return trades

    def get_market_summary_24h(self, symbol: str) -> Dict[str, Any]:
        """Calculates 24-hour High, Low, Volume, VWAP and Trade Count."""
        client = self.get_client()
        since_time = datetime.now(timezone.utc) - timedelta(hours=24)

        query = f"""
            SELECT
                min(price) AS low_24h,
                max(price) AS high_24h,
                sum(quantity) AS volume_24h,
                sum(quote_amount) AS quote_volume_24h,
                count() AS trades_24h
            FROM {self.database}.trades
            WHERE symbol = %(symbol)s AND timestamp_ns >= %(since_time)s
        """
        res = client.query(query, parameters={"symbol": symbol, "since_time": since_time})
        if not res.result_rows or res.result_rows[0][0] is None:
            return {
                "symbol": symbol,
                "high_24h": 0.0,
                "low_24h": 0.0,
                "volume_24h": 0.0,
                "quote_volume_24h": 0.0,
                "vwap_24h": 0.0,
                "trade_count_24h": 0,
            }

        low, high, vol, qvol, count = res.result_rows[0]
        vwap = (qvol / vol) if vol and vol > 0 else 0.0

        return {
            "symbol": symbol,
            "high_24h": from_fixed_point(high),
            "low_24h": from_fixed_point(low),
            "volume_24h": from_fixed_point(vol),
            "quote_volume_24h": from_fixed_point(qvol),
            "vwap_24h": from_fixed_point(int(vwap)),
            "trade_count_24h": count,
        }
