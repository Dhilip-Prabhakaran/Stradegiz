"""Read-side database queries.

Kept apart from the HTTP layer so the same queries can back the API, the
analytics jobs, and (later) the paper-trading simulator.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .db import connection


def list_symbols() -> list[dict[str, Any]]:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.symbol, s.name, s.exchange, s.sector,
                       i.last_bar_ts::date AS last_bar
                FROM symbols s
                LEFT JOIN ingestion_state i
                       ON i.symbol = s.symbol AND i.timeframe = '1d'
                WHERE s.is_active
                ORDER BY s.symbol
                """
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_ohlcv(
    symbol: str,
    timeframe: str,
    start: date | None = None,
    end: date | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    """Bars for one symbol, oldest first (the order charting libraries expect)."""
    clauses = ["symbol = %s", "timeframe = %s"]
    params: list[Any] = [symbol, timeframe]

    if start is not None:
        clauses.append("ts >= %s")
        params.append(start)
    if end is not None:
        # end is inclusive of the whole day
        clauses.append("ts < (%s::date + 1)")
        params.append(end)

    params.append(limit)
    sql = f"""
        SELECT ts, open, high, low, close, volume
        FROM ohlcv
        WHERE {' AND '.join(clauses)}
        ORDER BY ts DESC
        LIMIT %s
    """

    with connection() as conn:
        with conn.cursor() as cur:
            # Newest-first with LIMIT so a capped request returns the most
            # recent window; reversed here to hand back chronological order.
            cur.execute(sql, params)
            rows = cur.fetchall()

    return [
        {
            "time": int(ts.timestamp()),
            # Decimal is right for storage and arithmetic, but the chart
            # consumes JSON numbers; the cast happens only at the edge.
            "open": float(o),
            "high": float(h),
            "low": float(low),
            "close": float(c),
            "volume": int(v),
        }
        for ts, o, h, low, c, v in reversed(rows)
    ]
