-- ==============================================================================
-- ChronosEngine - ClickHouse High-Frequency Financial OLAP Schema
-- Features:
-- - Fixed-point 10^8 pricing and volumetric representation.
-- - DoubleDelta/Gorilla and T64/ZSTD columnar compression codecs.
-- - Sub-second and 1-minute OHLCV AggregatingMergeTree materialized rollups.
-- ==============================================================================

CREATE DATABASE IF NOT EXISTS chronos;

-- 1. Trades Raw Table (Tick Data Log)
CREATE TABLE IF NOT EXISTS chronos.trades
(
    trade_id            UInt64 CODEC(DoubleDelta, ZSTD(1)),
    symbol              LowCardinality(String),
    maker_order_id      String CODEC(ZSTD(1)),
    taker_order_id      String CODEC(ZSTD(1)),
    price               Int64 CODEC(DoubleDelta, ZSTD(1)),       -- Fixed-point 10^8
    quantity            Int64 CODEC(T64, ZSTD(1)),               -- Fixed-point 10^8
    quote_amount        Int64 CODEC(T64, ZSTD(1)),               -- Fixed-point 10^8
    taker_side          Enum8('BUY' = 1, 'SELL' = 2),
    timestamp_ns        DateTime64(9, 'UTC') CODEC(DoubleDelta, ZSTD(1)),
    sequence_number     UInt64 CODEC(DoubleDelta, ZSTD(1))
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp_ns)
ORDER BY (symbol, timestamp_ns, sequence_number)
SETTINGS index_granularity = 8192;

-- 2. L2 Order Book Snapshot Store (Historical Depth State)
CREATE TABLE IF NOT EXISTS chronos.order_book_snapshots
(
    symbol              LowCardinality(String),
    sequence_number     UInt64 CODEC(DoubleDelta, ZSTD(1)),
    timestamp_ns        DateTime64(9, 'UTC') CODEC(DoubleDelta, ZSTD(1)),
    best_bid            Nullable(Int64) CODEC(DoubleDelta, ZSTD(1)),
    best_ask            Nullable(Int64) CODEC(DoubleDelta, ZSTD(1)),
    spread              Nullable(Int64) CODEC(DoubleDelta, ZSTD(1)),
    bids_price          Array(Int64) CODEC(ZSTD(1)),
    bids_volume         Array(Int64) CODEC(ZSTD(1)),
    asks_price          Array(Int64) CODEC(ZSTD(1)),
    asks_volume         Array(Int64) CODEC(ZSTD(1))
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp_ns)
ORDER BY (symbol, timestamp_ns, sequence_number)
SETTINGS index_granularity = 8192;

-- 3. 1-Second OHLCV Aggregating Data Table
CREATE TABLE IF NOT EXISTS chronos.candles_1s_data
(
    time_bucket         DateTime CODEC(DoubleDelta, ZSTD(1)),
    symbol              LowCardinality(String),
    open_state          AggregateFunction(argMin, Int64, DateTime64(9, 'UTC')),
    high_state          AggregateFunction(max, Int64),
    low_state           AggregateFunction(min, Int64),
    close_state         AggregateFunction(argMax, Int64, DateTime64(9, 'UTC')),
    volume_state        AggregateFunction(sum, Int64),
    quote_volume_state  AggregateFunction(sum, Int64),
    trade_count_state   AggregateFunction(count, UInt64)
)
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(time_bucket)
ORDER BY (symbol, time_bucket)
SETTINGS index_granularity = 8192;

-- Materialized View: Ticks -> 1-Second OHLCV
CREATE MATERIALIZED VIEW IF NOT EXISTS chronos.candles_1s_mv
TO chronos.candles_1s_data AS
SELECT
    toStartOfInterval(timestamp_ns, INTERVAL 1 SECOND) AS time_bucket,
    symbol,
    argMinState(price, timestamp_ns) AS open_state,
    maxState(price) AS high_state,
    minState(price) AS low_state,
    argMaxState(price, timestamp_ns) AS close_state,
    sumState(quantity) AS volume_state,
    sumState(quote_amount) AS quote_volume_state,
    countState() AS trade_count_state
FROM chronos.trades
GROUP BY time_bucket, symbol;

-- Read View for 1-Second Candles
CREATE VIEW IF NOT EXISTS chronos.candles_1s AS
SELECT
    time_bucket,
    symbol,
    argMinMerge(open_state) AS open,
    maxMerge(high_state) AS high,
    minMerge(low_state) AS low,
    argMaxMerge(close_state) AS close,
    sumMerge(volume_state) AS volume,
    sumMerge(quote_volume_state) AS quote_volume,
    countMerge(trade_count_state) AS trade_count
FROM chronos.candles_1s_data
GROUP BY time_bucket, symbol
ORDER BY time_bucket ASC;

-- 4. 1-Minute OHLCV Aggregating Data Table
CREATE TABLE IF NOT EXISTS chronos.candles_1m_data
(
    time_bucket         DateTime CODEC(DoubleDelta, ZSTD(1)),
    symbol              LowCardinality(String),
    open_state          AggregateFunction(argMin, Int64, DateTime64(9, 'UTC')),
    high_state          AggregateFunction(max, Int64),
    low_state           AggregateFunction(min, Int64),
    close_state         AggregateFunction(argMax, Int64, DateTime64(9, 'UTC')),
    volume_state        AggregateFunction(sum, Int64),
    quote_volume_state  AggregateFunction(sum, Int64),
    trade_count_state   AggregateFunction(count, UInt64)
)
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(time_bucket)
ORDER BY (symbol, time_bucket)
SETTINGS index_granularity = 8192;

-- Materialized View: Ticks -> 1-Minute OHLCV
CREATE MATERIALIZED VIEW IF NOT EXISTS chronos.candles_1m_mv
TO chronos.candles_1m_data AS
SELECT
    toStartOfInterval(timestamp_ns, INTERVAL 1 MINUTE) AS time_bucket,
    symbol,
    argMinState(price, timestamp_ns) AS open_state,
    maxState(price) AS high_state,
    minState(price) AS low_state,
    argMaxState(price, timestamp_ns) AS close_state,
    sumState(quantity) AS volume_state,
    sumState(quote_amount) AS quote_volume_state,
    countState() AS trade_count_state
FROM chronos.trades
GROUP BY time_bucket, symbol;

-- Read View for 1-Minute Candles
CREATE VIEW IF NOT EXISTS chronos.candles_1m AS
SELECT
    time_bucket,
    symbol,
    argMinMerge(open_state) AS open,
    maxMerge(high_state) AS high,
    minMerge(low_state) AS low,
    argMaxMerge(close_state) AS close,
    sumMerge(volume_state) AS volume,
    sumMerge(quote_volume_state) AS quote_volume,
    countMerge(trade_count_state) AS trade_count
FROM chronos.candles_1m_data
GROUP BY time_bucket, symbol
ORDER BY time_bucket ASC;
