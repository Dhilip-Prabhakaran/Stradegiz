"""Provider access-token storage and status.

The token lives in the DB (not .env) because Upstox tokens expire daily at
03:30 IST and carry no refresh_token — a fresh one must be supplied each day.
Storing it here lets a new token take effect on the next poll with no restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .db import connection
from .market_hours import next_token_expiry, now_ist

UPSTOX = "upstox"


@dataclass(frozen=True)
class TokenStatus:
    present: bool
    valid: bool
    issued_at: datetime | None
    expires_at: datetime | None
    seconds_left: int | None

    def as_dict(self) -> dict:
        return {
            "present": self.present,
            "valid": self.valid,
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "seconds_left": self.seconds_left,
        }


def save_token(access_token: str, provider: str = UPSTOX) -> TokenStatus:
    """Store a freshly issued token, computing its expiry from the issue time."""
    token = access_token.strip()
    if not token:
        raise ValueError("access_token is empty")

    issued = now_ist()
    expires = next_token_expiry(issued)

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_token (provider, access_token, issued_at,
                                        expires_at, updated_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (provider) DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    issued_at    = EXCLUDED.issued_at,
                    expires_at   = EXCLUDED.expires_at,
                    updated_at   = now()
                """,
                (provider, token, issued, expires),
            )
    return get_status(provider)


def get_valid_token(provider: str = UPSTOX) -> str | None:
    """The current token string, or None if absent or expired.

    Returning None for an expired token (rather than a dead string) means the
    caller gets a clear 'no token' signal instead of a confusing 401.
    """
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT access_token, expires_at FROM auth_token WHERE provider = %s",
                (provider,),
            )
            row = cur.fetchone()

    if not row:
        return None
    token, expires_at = row
    return token if now_ist() < expires_at else None


def get_status(provider: str = UPSTOX) -> TokenStatus:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT issued_at, expires_at FROM auth_token WHERE provider = %s",
                (provider,),
            )
            row = cur.fetchone()

    if not row:
        return TokenStatus(False, False, None, None, None)

    issued_at, expires_at = row
    left = int((expires_at - now_ist()).total_seconds())
    return TokenStatus(
        present=True,
        valid=left > 0,
        issued_at=issued_at,
        expires_at=expires_at,
        seconds_left=max(left, 0) if left > 0 else left,
    )
