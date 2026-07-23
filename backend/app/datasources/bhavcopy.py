"""End-of-day option data from the NSE F&O Bhavcopy.

Kotak has no historical endpoint, so live snapshots are the only way to build
intraday history. But NSE publishes a free daily archive going back years, so
*daily* OI can be backfilled immediately rather than waited for.

Scope: NSE index options (NIFTY, BANKNIFTY, ...). SENSEX/BANKEX are BSE
contracts and need the separate BSE archive, which this module does not cover.

Column names and conventions verified against a real 2026-07-22 file:
  TckrSymb  XpryDt(ISO)  StrkPric  OptnTp  OpnIntrst  ChngInOpnIntrst
  TtlTradgVol  ClsPric  UndrlygPric
Note StrkPric is the plain strike here — unlike Kotak's scrip master, it is
NOT scaled by 100.
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import pandas as pd

from ..market_hours import IST
from .base import DataSourceError
from .upstox_source import ChainRow

log = logging.getLogger("stradegiz.bhavcopy")

URL = (
    "https://nsearchives.nseindia.com/content/fo/"
    "BhavCopy_NSE_FO_0_0_0_{d}_F_0000.csv.zip"
)

# NSE rejects requests without a browser-like agent.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

#: FinInstrmTp code for index options (STO/STF/IDF are stock options,
#: stock futures and index futures respectively).
INDEX_OPTION = "IDO"

#: EOD rows are stamped after the close so they cannot collide with the
#: 15:30 intraday snapshot on days where both exist.
EOD_TIME = time(15, 40)

NSE_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}


def _dec(value: Any) -> Decimal | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return Decimal(str(round(float(value), 4)))
    except (TypeError, ValueError, InvalidOperation):
        return None


def _int(value: Any) -> int:
    try:
        if pd.isna(value):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def download(day: date, client: httpx.Client | None = None) -> pd.DataFrame | None:
    """The day's F&O bhavcopy, or None when NSE has no file (holiday/weekend)."""
    url = URL.format(d=day.strftime("%Y%m%d"))
    owned = client is None
    client = client or httpx.Client(timeout=90, follow_redirects=True)
    try:
        resp = client.get(url, headers=HEADERS)
    except httpx.HTTPError as exc:
        raise DataSourceError(f"bhavcopy fetch failed for {day}: {exc}") from exc
    finally:
        if owned:
            client.close()

    if resp.status_code == 404:
        # Weekend or trading holiday — absence is expected, not an error.
        return None
    if resp.status_code != 200:
        raise DataSourceError(f"bhavcopy {day}: HTTP {resp.status_code}")

    try:
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        return pd.read_csv(zf.open(zf.namelist()[0]))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise DataSourceError(f"bhavcopy {day}: unreadable archive ({exc})") from exc


def to_rows(df: pd.DataFrame, day: date, underlyings: set[str]) -> list[ChainRow]:
    """Index-option rows for the requested underlyings."""
    wanted = {u for u in underlyings if u in NSE_UNDERLYINGS}
    if not wanted:
        return []

    frame = df[
        (df["FinInstrmTp"].astype(str) == INDEX_OPTION)
        & (df["TckrSymb"].astype(str).isin(wanted))
        & (df["OptnTp"].astype(str).isin(["CE", "PE"]))
    ]

    ts = datetime.combine(day, EOD_TIME, tzinfo=IST)
    rows: list[ChainRow] = []

    for r in frame.itertuples(index=False):
        strike = _dec(getattr(r, "StrkPric", None))
        expiry_raw = getattr(r, "XpryDt", None)
        if strike is None or not expiry_raw:
            continue
        try:
            expiry = datetime.strptime(str(expiry_raw)[:10], "%Y-%m-%d").date()
        except ValueError:
            continue

        oi = _int(getattr(r, "OpnIntrst", 0))
        change = _int(getattr(r, "ChngInOpnIntrst", 0))

        rows.append(
            ChainRow(
                underlying=str(r.TckrSymb),
                expiry=expiry,
                strike=strike,
                option_type=str(r.OptnTp),
                ts=ts,
                oi=oi,
                # The file gives the day's OI delta, so the previous close
                # follows directly and needs no extra lookup.
                prev_oi=oi - change,
                volume=_int(getattr(r, "TtlTradgVol", 0)),
                ltp=_dec(getattr(r, "ClsPric", None)),
                iv=None,  # not published in the bhavcopy
                spot=_dec(getattr(r, "UndrlygPric", None)),
            )
        )
    return rows


def fetch_day(
    day: date, underlyings: set[str], client: httpx.Client | None = None
) -> list[ChainRow]:
    df = download(day, client)
    if df is None:
        return []
    return to_rows(df, day, underlyings)
