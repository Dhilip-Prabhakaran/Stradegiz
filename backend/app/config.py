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
    #: Which provider the recorder uses: "kotak" or "upstox".
    data_source: str = "kotak"
    #: Kotak Neo credentials. These grant full account access, so they live
    #: only in .env (gitignored) and are never logged.
    kotak: "KotakCreds | None" = None


@dataclass(frozen=True)
class KotakCreds:
    consumer_key: str
    consumer_secret: str
    mobile: str
    ucc: str
    mpin: str
    totp_secret: str

    def is_complete(self) -> bool:
        return all(
            (
                self.consumer_key,
                self.consumer_secret,
                self.mobile,
                self.ucc,
                self.mpin,
                self.totp_secret,
            )
        )


def _kotak_creds() -> KotakCreds:
    e = os.environ.get
    return KotakCreds(
        consumer_key=e("KOTAK_CONSUMER_KEY", ""),
        consumer_secret=e("KOTAK_CONSUMER_SECRET", ""),
        mobile=e("KOTAK_MOBILE", ""),
        ucc=e("KOTAK_UCC", ""),
        mpin=e("KOTAK_MPIN", ""),
        totp_secret=e("KOTAK_TOTP_SECRET", ""),
    )


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
        data_source=os.environ.get("DATA_SOURCE", "kotak").strip().lower(),
        kotak=_kotak_creds(),
    )
