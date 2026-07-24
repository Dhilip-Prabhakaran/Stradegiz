"""Snapshot recorder — captures the live option chain on a fixed interval.

This is the most important process in the system. Five-minute OI history
cannot be bought after the fact, so any market day this is not running is a
permanent hole in the archive.

    docker compose up -d recorder          # run continuously
    docker compose run --rm recorder python -m app.recorder --once
"""

from __future__ import annotations

import argparse
import logging
import time as _time
from datetime import date, datetime

from . import auth
from .config import get_settings
from .datasources.base import DataSourceError
from .datasources.factory import make_source
from .datasources.upstox_source import ChainRow
from .db import connection
from .market_hours import IST, is_market_open, next_tick, now_ist

log = logging.getLogger("stradegiz.recorder")

INSERT_SQL = """
INSERT INTO options_chain (underlying, expiry, strike, option_type, ts,
                           oi, prev_oi, volume, ltp, iv, spot)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (underlying, expiry, strike, option_type, ts) DO UPDATE SET
    oi = EXCLUDED.oi, prev_oi = EXCLUDED.prev_oi, volume = EXCLUDED.volume,
    ltp = EXCLUDED.ltp, iv = EXCLUDED.iv, spot = EXCLUDED.spot
"""


def _store(rows: list[ChainRow]) -> int:
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


FUT_SQL = """
INSERT INTO futures_snapshot (underlying, expiry, ts, total_oi, volume, ltp,
                             day_high, day_low)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (underlying, expiry, ts) DO UPDATE SET
    total_oi = EXCLUDED.total_oi, volume = EXCLUDED.volume, ltp = EXCLUDED.ltp,
    day_high = EXCLUDED.day_high, day_low = EXCLUDED.day_low
"""


def _store_future(fut) -> None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                FUT_SQL,
                (
                    fut.underlying, fut.expiry, fut.ts, fut.oi, fut.volume,
                    fut.ltp, fut.day_high, fut.day_low,
                ),
            )


def _log_capture(underlying: str, status: str, rows: int, detail: str | None) -> None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO capture_log (underlying, status, rows_written, detail)
                VALUES (%s, %s, %s, %s)
                """,
                (underlying, status, rows, detail),
            )


def capture_once(
    source: UpstoxOptionChain,
    underlyings: list[str],
    ts: datetime | None = None,
    expiry: date | None = None,
) -> int:
    """One snapshot across all configured underlyings."""
    ts = ts or now_ist()
    total = 0

    for underlying in underlyings:
        try:
            # Nearest expiry unless one is pinned: that is where the OI
            # activity these screens are about actually concentrates.
            target = expiry
            if target is None:
                available = source.expiries(underlying)
                today = ts.astimezone(IST).date()
                future = [e for e in available if e >= today]
                if not future:
                    raise DataSourceError("no upcoming expiry returned")
                target = future[0]

            rows = source.fetch_chain(underlying, target, ts)
            written = _store(rows)
            total += written

            # Front-month futures price + OI, for the price-based strategies.
            # Best-effort: a futures hiccup must not fail the option capture,
            # which is the primary archive.
            fut_note = ""
            try:
                fut = source.fetch_front_future(underlying, ts)
                _store_future(fut)
                fut_note = f", fut ltp={fut.ltp}"
            except (DataSourceError, AttributeError) as exc:
                fut_note = f", fut failed: {str(exc)[:60]}"

            _log_capture(underlying, "ok", written, f"expiry={target}")
            log.info(
                "%s %s: %d rows (expiry %s)%s",
                underlying, ts.strftime("%H:%M:%S"), written, target, fut_note,
            )

        except DataSourceError as exc:
            # One underlying failing must not stop the others, and the gap
            # must be visible in capture_log rather than silently absent.
            log.error("%s: %s", underlying, exc)
            _log_capture(underlying, "error", 0, str(exc)[:500])
        except Exception as exc:  # noqa: BLE001 - the loop must survive anything
            log.exception("%s: unexpected failure", underlying)
            _log_capture(underlying, "error", 0, f"unexpected: {exc}"[:500])

    return total


def run_forever(source: UpstoxOptionChain, underlyings: list[str], interval: int) -> None:
    log.info(
        "recorder started — %s every %ds, session 09:15-15:30 IST",
        ",".join(underlyings),
        interval,
    )
    while True:
        target = next_tick(interval)
        _time.sleep(max(0.0, (target - now_ist()).total_seconds()))

        if not is_market_open(target):
            # Outside the session there is nothing new to capture; the loop
            # keeps ticking quietly rather than exiting so the container
            # stays up across days without supervision.
            continue

        capture_once(source, underlyings, ts=target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stradegiz OI snapshot recorder")
    parser.add_argument("--once", action="store_true", help="capture a single snapshot and exit")
    parser.add_argument("--ignore-hours", action="store_true", help="capture even when the market is closed")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()

    # Upstox path only: bootstrap a .env token into the DB so it can be
    # replaced later without a restart. Harmless when DATA_SOURCE=kotak.
    if (
        settings.data_source == "upstox"
        and settings.upstox_access_token
        and auth.get_valid_token() is None
    ):
        auth.save_token(settings.upstox_access_token)
        log.info("seeded Upstox token from .env into the database")

    try:
        source = make_source(settings)
    except DataSourceError as exc:
        log.error("%s", exc)
        raise SystemExit(1)

    log.info("data source: %s", settings.data_source)
    underlyings = settings.capture_underlyings

    if args.once:
        if not args.ignore_hours and not is_market_open():
            log.warning("market is closed (09:15-15:30 IST, Mon-Fri); pass --ignore-hours to force")
            return
        log.info("captured %d rows", capture_once(source, underlyings))
        return

    run_forever(source, underlyings, settings.capture_interval_seconds)


if __name__ == "__main__":
    main()
