"""Runtime settings, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    default_exchange: str = "NSE"
    #: How much history to pull for a symbol that has never been ingested.
    initial_history_days: int = 730
    #: Upstox market-data token. Read from the environment and never logged.
    upstox_access_token: str = ""
    capture_underlyings: tuple[str, ...] = ("NIFTY", "BANKNIFTY")
    capture_interval_seconds: int = 300


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL",
            "postgresql://stradegiz:stradegiz_dev@db:5432/stradegiz",
        ),
        default_exchange=os.environ.get("DEFAULT_EXCHANGE", "NSE"),
        initial_history_days=int(os.environ.get("INITIAL_HISTORY_DAYS", "730")),
        upstox_access_token=os.environ.get("UPSTOX_ACCESS_TOKEN", ""),
        capture_underlyings=tuple(
            u.strip().upper()
            for u in os.environ.get("CAPTURE_UNDERLYINGS", "NIFTY,BANKNIFTY").split(",")
            if u.strip()
        ),
        capture_interval_seconds=int(os.environ.get("CAPTURE_INTERVAL_SECONDS", "300")),
    )
