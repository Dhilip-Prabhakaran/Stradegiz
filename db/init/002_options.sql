-- F&O open-interest capture.
--
-- Granularity note: 5-minute OI history is not purchasable after the fact.
-- These tables are an archive we build by snapshotting the live chain during
-- market hours; a day not recorded is a day lost permanently.

-- One row per (strike, side) per snapshot. This is the tool's core dataset.
CREATE TABLE options_chain (
    underlying  TEXT           NOT NULL,          -- NIFTY, BANKNIFTY
    expiry      DATE           NOT NULL,
    strike      NUMERIC(12, 2) NOT NULL,
    option_type TEXT           NOT NULL CHECK (option_type IN ('CE', 'PE')),
    ts          TIMESTAMPTZ    NOT NULL,          -- snapshot instant
    oi          BIGINT         NOT NULL,
    prev_oi     BIGINT,                           -- provider's previous-day OI
    volume      BIGINT         NOT NULL DEFAULT 0,
    ltp         NUMERIC(12, 2),
    iv          NUMERIC(8, 2),
    spot        NUMERIC(12, 2),                   -- underlying at snapshot time
    PRIMARY KEY (underlying, expiry, strike, option_type, ts)
);

-- 7-day chunks: a single index at 5-min granularity is ~75 snapshots/day
-- across ~100 strikes x 2 sides, so weekly chunks stay a sensible size.
SELECT create_hypertable('options_chain', 'ts', chunk_time_interval => INTERVAL '7 days');

-- The OI Analysis screen reads one strike across a day, both sides.
CREATE INDEX options_chain_strike_ts_idx
    ON options_chain (underlying, expiry, strike, ts DESC);

-- The options-chain ladder reads all strikes at one instant.
CREATE INDEX options_chain_snapshot_idx
    ON options_chain (underlying, expiry, ts DESC);

-- Aggregate futures/underlying state per snapshot, for the futures OI screen.
CREATE TABLE futures_snapshot (
    underlying TEXT           NOT NULL,
    expiry     DATE           NOT NULL,
    ts         TIMESTAMPTZ    NOT NULL,
    total_oi   BIGINT         NOT NULL,
    volume     BIGINT         NOT NULL DEFAULT 0,
    ltp        NUMERIC(12, 2),
    day_high   NUMERIC(12, 2),
    day_low    NUMERIC(12, 2),
    PRIMARY KEY (underlying, expiry, ts)
);

SELECT create_hypertable('futures_snapshot', 'ts', chunk_time_interval => INTERVAL '30 days');

-- Audit of the capture loop: which polls succeeded, so gaps in the archive
-- are visible rather than silently absent.
CREATE TABLE capture_log (
    id         BIGSERIAL PRIMARY KEY,
    underlying TEXT        NOT NULL,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    status     TEXT        NOT NULL,
    rows_written INTEGER   NOT NULL DEFAULT 0,
    detail     TEXT
);
