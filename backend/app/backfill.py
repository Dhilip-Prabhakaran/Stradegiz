"""Backfill daily option OI from the NSE bhavcopy archive.

Intraday history must be self-recorded, but daily history is free and already
published, so this gives the tool years of depth on day one.

    docker compose run --rm recorder python -m app.backfill --days 365
    docker compose run --rm recorder python -m app.backfill --from 2025-01-01 --to 2025-12-31
"""

from __future__ import annotations

import argparse
import logging
import time as _time
from datetime import date, datetime, timedelta

import httpx

from .config import get_settings
from .datasources import bhavcopy
from .datasources.base import DataSourceError
from .db import connection
from .market_hours import is_trading_day
from .recorder import INSERT_SQL

log = logging.getLogger("stradegiz.backfill")

#: Courtesy pause between archive downloads so we do not hammer NSE.
DELAY_SECONDS = 0.7


def _store(rows) -> int:
    if not rows:
        return 0
    with connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                INSERT_SQL,
                [
                    (
                        r.underlying, r.expiry, r.strike, r.option_type, r.ts,
                        r.oi, r.prev_oi, r.volume, r.ltp, r.iv, r.spot,
                    )
                    for r in rows
                ],
            )
    return len(rows)


def run(start: date, end: date, underlyings: set[str]) -> tuple[int, int]:
    """Load every trading day in [start, end]. Returns (days, rows)."""
    total_rows = 0
    days_loaded = 0

    with httpx.Client(timeout=90, follow_redirects=True) as client:
        day = start
        while day <= end:
            if not is_trading_day(day):
                day += timedelta(days=1)
                continue

            try:
                rows = bhavcopy.fetch_day(day, underlyings, client)
            except DataSourceError as exc:
                # One bad day must not abandon the rest of the range.
                log.warning("%s: %s", day, exc)
                day += timedelta(days=1)
                continue

            if rows:
                written = _store(rows)
                total_rows += written
                days_loaded += 1
                log.info("%s: %d rows", day, written)
            else:
                # Trading holiday: NSE publishes no file.
                log.info("%s: no file (holiday?)", day)

            _time.sleep(DELAY_SECONDS)
            day += timedelta(days=1)

    return days_loaded, total_rows


def main() -> None:
    p = argparse.ArgumentParser(description="Backfill daily OI from NSE bhavcopy")
    p.add_argument("--days", type=int, help="how many days back from today")
    p.add_argument("--from", dest="start", help="start date YYYY-MM-DD")
    p.add_argument("--to", dest="end", help="end date YYYY-MM-DD")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()

    today = datetime.now().date()
    if args.days:
        start, end = today - timedelta(days=args.days), today
    elif args.start:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end) if args.end else today
    else:
        p.error("give --days or --from")

    wanted = set(settings.capture_underlyings)
    skipped = wanted - bhavcopy.NSE_UNDERLYINGS
    if skipped:
        # SENSEX/BANKEX live in the BSE archive, which this loader does not read.
        log.warning("not in the NSE archive, skipping: %s", ", ".join(sorted(skipped)))

    log.info("backfilling %s to %s for %s", start, end, ", ".join(sorted(wanted & bhavcopy.NSE_UNDERLYINGS)))
    days, rows = run(start, end, wanted)
    log.info("done: %d trading days, %d rows", days, rows)


if __name__ == "__main__":
    main()
