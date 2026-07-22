"""Capture-health reporting for the /api/health/capture endpoint.

Turns the silent, unrecoverable failure mode (token expired, nothing recorded)
into something the UI can surface loudly.
"""

from __future__ import annotations

from typing import Any

from . import auth
from .db import connection
from .market_hours import is_market_open, now_ist


def last_captures() -> list[dict[str, Any]]:
    """Most recent capture-log entry per underlying."""
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (underlying)
                       underlying, ts, status, rows_written, detail
                FROM capture_log
                ORDER BY underlying, ts DESC
                """
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def capture_health() -> dict[str, Any]:
    """Overall health: is a valid token present, and is capture succeeding.

    `healthy` answers the question that matters at 09:15 — can we record right
    now — so the UI can show one clear red/green state.
    """
    token = auth.get_status()
    captures = last_captures()
    market_open = is_market_open()

    # During the session, health requires a valid token; outside it, an absent
    # or expired token is expected (it will be refreshed before next open) and
    # must not raise a false alarm.
    healthy = token.valid if market_open else token.present

    return {
        "now_ist": now_ist().isoformat(),
        "market_open": market_open,
        "healthy": healthy,
        "token": token.as_dict(),
        "captures": [
            {
                "underlying": c["underlying"],
                "ts": c["ts"].isoformat() if c["ts"] else None,
                "status": c["status"],
                "rows_written": c["rows_written"],
                "detail": c["detail"],
            }
            for c in captures
        ],
    }
