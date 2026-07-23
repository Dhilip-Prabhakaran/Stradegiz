"""Read queries for the F&O open-interest screens."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from .analytics import interpret_oi
from .db import connection

# Intervals the UI may request, mapped to Postgres interval literals.
# Whitelisted rather than interpolated: this value reaches SQL directly.
INTERVALS = {
    "1min": "1 minute",
    "3min": "3 minutes",
    "5min": "5 minutes",
    "15min": "15 minutes",
    "30min": "30 minutes",
    "60min": "1 hour",
    # Day buckets read the bhavcopy backfill, where each trading day
    # contributes one end-of-day row.
    "1day": "1 day",
}

#: Intervals that span multiple trading days rather than sitting within one.
MULTI_DAY = {"1day"}


def available_expiries(underlying: str) -> list[str]:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT expiry FROM options_chain
                WHERE underlying = %s ORDER BY expiry
                """,
                (underlying,),
            )
            return [r[0].isoformat() for r in cur.fetchall()]


def available_strikes(underlying: str, expiry: date) -> list[float]:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT strike FROM options_chain
                WHERE underlying = %s AND expiry = %s ORDER BY strike
                """,
                (underlying, expiry),
            )
            return [float(r[0]) for r in cur.fetchall()]


def _f(value: Any) -> float | None:
    return float(value) if isinstance(value, (Decimal, int, float)) else None


def oi_analysis(
    underlying: str,
    expiry: date,
    strike: float,
    start: date,
    end: date,
    interval: str = "5min",
) -> list[dict[str, Any]]:
    """One strike over a date range, bucketed, call and put side by side.

    Backs the OI Analysis screen. Intraday intervals are normally called with
    start == end (a single trading day); the '1day' interval spans a range and
    reads the end-of-day backfill, one row per trading day.

    NSE hours (09:15-15:30 IST = 03:45-10:00 UTC) fall inside a single UTC
    day, so bucketing in UTC does not shift any trading day.
    """
    if interval not in INTERVALS:
        raise ValueError(f"unsupported interval: {interval}")
    if end < start:
        raise ValueError("end date is before start date")

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT time_bucket(INTERVAL '{INTERVALS[interval]}', ts) AS bucket,
                       option_type,
                       last(oi, ts)     AS oi,
                       last(ltp, ts)    AS ltp,
                       last(volume, ts) AS volume,
                       last(spot, ts)   AS spot
                FROM options_chain
                WHERE underlying = %s
                  AND expiry = %s
                  AND strike = %s
                  AND ts >= %s::date
                  AND ts <  (%s::date + 1)
                GROUP BY bucket, option_type
                ORDER BY bucket
                """,
                (underlying, expiry, strike, start, end),
            )
            rows = cur.fetchall()

    # Collapse the two sides of each bucket into a single row.
    buckets: dict[Any, dict[str, Any]] = {}
    for bucket, side, oi, ltp, volume, spot in rows:
        entry = buckets.setdefault(bucket, {"bucket": bucket, "spot": _f(spot)})
        key = "call" if side == "CE" else "put"
        entry[key] = {"oi": oi, "ltp": _f(ltp), "volume": volume}

    ordered = [buckets[k] for k in sorted(buckets)]

    out: list[dict[str, Any]] = []
    for i, entry in enumerate(ordered):
        prev = ordered[i - 1] if i > 0 else None
        row: dict[str, Any] = {
            "time": entry["bucket"].isoformat(),
            "spot": entry.get("spot"),
        }

        for side in ("call", "put"):
            cur_side = entry.get(side)
            if cur_side is None:
                row[side] = None
                continue

            prev_side = prev.get(side) if prev else None
            # The first bucket in range has no predecessor, so its changes are
            # unknown rather than zero — reported as null so the UI can show
            # a dash instead of implying a flat reading.
            oi_change = (
                cur_side["oi"] - prev_side["oi"]
                if prev_side and cur_side["oi"] is not None
                else None
            )
            ltp_change = (
                round(cur_side["ltp"] - prev_side["ltp"], 2)
                if prev_side
                and cur_side["ltp"] is not None
                and prev_side["ltp"] is not None
                else None
            )

            row[side] = {
                "oi": cur_side["oi"],
                "oi_change": oi_change,
                "ltp": cur_side["ltp"],
                "ltp_change": ltp_change,
                "volume": cur_side["volume"],
                "interpretation": interpret_oi(oi_change, ltp_change),
            }

        out.append(row)

    # Newest first, matching how the screen is read.
    out.reverse()
    return out
