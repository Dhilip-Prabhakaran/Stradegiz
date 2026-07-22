"""Fetch bars from a DataSource and upsert them into the store.

Run inside the container:
    docker compose run --rm backend python -m app.ingest --seed
    docker compose run --rm backend python -m app.ingest
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta, timezone

from .config import get_settings
from .datasources.base import TF_DAILY, Bar, DataSource, DataSourceError
from .datasources.yfinance_source import YFinanceSource
from .db import connection

log = logging.getLogger("stradegiz.ingest")

# A starter slice of NIFTY 50. Enough breadth to build screeners and sector
# views against without waiting on a long first ingest.
SEED_SYMBOLS: list[tuple[str, str, str]] = [
    ("RELIANCE", "Reliance Industries Ltd", "Energy"),
    ("TCS", "Tata Consultancy Services Ltd", "IT"),
    ("HDFCBANK", "HDFC Bank Ltd", "Financials"),
    ("INFY", "Infosys Ltd", "IT"),
    ("ICICIBANK", "ICICI Bank Ltd", "Financials"),
    ("HINDUNILVR", "Hindustan Unilever Ltd", "FMCG"),
    ("ITC", "ITC Ltd", "FMCG"),
    ("SBIN", "State Bank of India", "Financials"),
    ("BHARTIARTL", "Bharti Airtel Ltd", "Telecom"),
    ("LT", "Larsen & Toubro Ltd", "Industrials"),
]

UPSERT_SQL = """
INSERT INTO ohlcv (symbol, timeframe, ts, open, high, low, close, volume)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (symbol, timeframe, ts) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume
"""


def seed_symbols() -> int:
    """Insert the starter symbol list. Safe to re-run."""
    with connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO symbols (symbol, name, exchange, sector)
                VALUES (%s, %s, 'NSE', %s)
                ON CONFLICT (symbol) DO UPDATE SET
                    name = EXCLUDED.name,
                    sector = EXCLUDED.sector
                """,
                SEED_SYMBOLS,
            )
    return len(SEED_SYMBOLS)


def active_symbols() -> list[str]:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol FROM symbols WHERE is_active ORDER BY symbol")
            return [row[0] for row in cur.fetchall()]


def _resume_point(symbol: str, timeframe: str, source: str) -> date | None:
    """The last bar we already hold, so we fetch only what is missing."""
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT last_bar_ts FROM ingestion_state
                WHERE symbol = %s AND timeframe = %s AND source = %s
                """,
                (symbol, timeframe, source),
            )
            row = cur.fetchone()
    return row[0].date() if row and row[0] else None


def _record_state(
    symbol: str,
    timeframe: str,
    source: str,
    last_bar_ts: datetime | None,
    status: str,
    error: str | None,
) -> None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_state
                    (symbol, timeframe, source, last_bar_ts, last_run_at,
                     last_status, last_error)
                VALUES (%s, %s, %s, %s, now(), %s, %s)
                ON CONFLICT (symbol, timeframe, source) DO UPDATE SET
                    -- Keep the furthest point reached; a failed run must not
                    -- rewind progress made by an earlier successful one.
                    last_bar_ts = GREATEST(
                        ingestion_state.last_bar_ts,
                        COALESCE(EXCLUDED.last_bar_ts, ingestion_state.last_bar_ts)
                    ),
                    last_run_at = EXCLUDED.last_run_at,
                    last_status = EXCLUDED.last_status,
                    last_error  = EXCLUDED.last_error
                """,
                (symbol, timeframe, source, last_bar_ts, status, error),
            )


def _store(bars: list[Bar]) -> int:
    if not bars:
        return 0
    rows = [
        (b.symbol, b.timeframe, b.ts, b.open, b.high, b.low, b.close, b.volume)
        for b in bars
    ]
    with connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, rows)
    return len(rows)


def ingest_symbol(source: DataSource, symbol: str, timeframe: str = TF_DAILY) -> int:
    """Fetch and store bars for one symbol. Returns rows written."""
    settings = get_settings()
    today = datetime.now(timezone.utc).date()

    last = _resume_point(symbol, timeframe, source.name)
    if last is None:
        start = today - timedelta(days=settings.initial_history_days)
    else:
        # Re-fetch the last held day: the most recent bar may have been
        # provisional when we stored it. The upsert makes this free.
        start = last

    if start > today:
        return 0

    try:
        bars = source.fetch(symbol, timeframe, start, today)
    except DataSourceError as exc:
        log.warning("%s: %s", symbol, exc)
        _record_state(symbol, timeframe, source.name, None, "error", str(exc))
        return 0

    written = _store(bars)
    newest = max((b.ts for b in bars), default=None)
    _record_state(symbol, timeframe, source.name, newest, "ok", None)
    log.info("%s: %d bars (from %s)", symbol, written, start)
    return written


def run(timeframe: str = TF_DAILY) -> int:
    source = YFinanceSource(get_settings().default_exchange)
    symbols = active_symbols()
    if not symbols:
        log.warning("no active symbols — run with --seed first")
        return 0

    total = 0
    for symbol in symbols:
        # One symbol's failure must not abort the run; state is recorded
        # per symbol so a later run retries only what is behind.
        total += ingest_symbol(source, symbol, timeframe)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Stradegiz data ingestion")
    parser.add_argument(
        "--seed", action="store_true", help="insert the starter symbol list, then exit"
    )
    parser.add_argument("--timeframe", default=TF_DAILY)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.seed:
        log.info("seeded %d symbols", seed_symbols())
        return

    log.info("wrote %d bars total", run(args.timeframe))


if __name__ == "__main__":
    main()
