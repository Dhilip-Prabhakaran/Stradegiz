"""Capture-health reporting for the /api/health/capture endpoint.

Turns the silent, unrecoverable failure mode (token expired, nothing recorded)
into something the UI can surface loudly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import auth
from .config import get_settings
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


#: Missed intervals before capture counts as stale. Two allows one hiccup
#: (a transient network blip) without crying wolf.
STALE_AFTER_INTERVALS = 2


def is_stale(
    newest_ok: datetime | None,
    market_open: bool,
    interval_seconds: int,
    now: datetime | None = None,
) -> bool:
    """Whether capture has gone quiet while the market is open.

    Outside market hours nothing is expected, so nothing is ever stale — that
    would be a false alarm every single evening.
    """
    if not market_open:
        return False
    if newest_ok is None:
        return True
    now = now or now_ist()
    return (now - newest_ok).total_seconds() > interval_seconds * STALE_AFTER_INTERVALS


def capture_health() -> dict[str, Any]:
    """Overall health, aware of how the configured provider authenticates.

    `healthy` answers the question that matters at 09:15 — is data actually
    landing right now — so the UI can show one clear red/green state.
    """
    settings = get_settings()
    provider = settings.data_source
    captures = last_captures()
    market_open = is_market_open()

    newest_ok = max(
        (c["ts"] for c in captures if c["status"] == "ok" and c["ts"]),
        default=None,
    )
    stale = is_stale(newest_ok, market_open, settings.capture_interval_seconds)
    failing = [c for c in captures if c["status"] == "error"]

    if provider == "kotak":
        # Kotak logs in automatically via its TOTP secret, so there is no
        # stored token to inspect. Capture success IS the auth signal: a login
        # failure surfaces as failing captures, not as a missing token.
        auth_info: dict[str, Any] = {
            "mode": "auto-login",
            "provider": "kotak",
            "manual_action_needed": False,
        }
        healthy = not stale and not failing
    else:
        # Upstox needs a manually pasted token, so its absence is itself the
        # fault worth reporting — before any capture has had a chance to fail.
        token = auth.get_status()
        auth_info = {
            "mode": "manual-token",
            "provider": "upstox",
            "manual_action_needed": not token.valid,
            **token.as_dict(),
        }
        healthy = (token.valid if market_open else token.present) and not stale

    return {
        "now_ist": now_ist().isoformat(),
        "market_open": market_open,
        "healthy": healthy,
        "stale": stale,
        "data_source": provider,
        "auth": auth_info,
        # Retained for backwards compatibility with the existing UI shape.
        "token": auth_info,
        "last_success": newest_ok.isoformat() if newest_ok else None,
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
