-- Stradegiz core schema.
-- Runs automatically on first startup of an empty db volume.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Instruments we track. Kept separate from price data so symbol metadata
-- (name, sector) lives in one row rather than being repeated on every bar.
CREATE TABLE symbols (
    symbol     TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    exchange   TEXT NOT NULL DEFAULT 'NSE',
    sector     TEXT,
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Price bars. `timeframe` is present from day one so intraday ('1m', '5m')
-- can land alongside today's daily ('1d') data without a migration.
CREATE TABLE ohlcv (
    symbol    TEXT        NOT NULL REFERENCES symbols(symbol) ON DELETE CASCADE,
    timeframe TEXT        NOT NULL,
    ts        TIMESTAMPTZ NOT NULL,
    open      NUMERIC(18, 4) NOT NULL,
    high      NUMERIC(18, 4) NOT NULL,
    low       NUMERIC(18, 4) NOT NULL,
    close     NUMERIC(18, 4) NOT NULL,
    volume    BIGINT      NOT NULL DEFAULT 0,
    -- Composite key makes re-ingestion idempotent: a repeated fetch updates
    -- the existing bar instead of inserting a duplicate.
    PRIMARY KEY (symbol, timeframe, ts)
);

-- Partition by time. chunk_time_interval is sized for daily bars today;
-- intraday will want smaller chunks, set per-timeframe when we get there.
SELECT create_hypertable('ohlcv', 'ts', chunk_time_interval => INTERVAL '1 year');

-- The dominant read pattern: one symbol, one timeframe, over a date range.
CREATE INDEX ohlcv_symbol_timeframe_ts_idx ON ohlcv (symbol, timeframe, ts DESC);

-- Tracks how far each (symbol, timeframe) has been ingested, so a nightly
-- job can fetch only what is missing rather than re-pulling full history.
CREATE TABLE ingestion_state (
    symbol       TEXT NOT NULL REFERENCES symbols(symbol) ON DELETE CASCADE,
    timeframe    TEXT NOT NULL,
    source       TEXT NOT NULL,
    last_bar_ts  TIMESTAMPTZ,
    last_run_at  TIMESTAMPTZ,
    last_status  TEXT,
    last_error   TEXT,
    PRIMARY KEY (symbol, timeframe, source)
);
