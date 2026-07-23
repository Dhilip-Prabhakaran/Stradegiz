"""End-of-day option data from the NSE and BSE F&O bhavcopy archives.

Kotak has no historical endpoint, so live snapshots are the only way to build
intraday history. But both exchanges publish free daily archives going back
years, so *daily* OI can be backfilled immediately rather than waited for.

Both exchanges publish the same UDiFF column set (verified against real
2026-07-22 files), so parsing is shared. They differ only in delivery:
  NSE: zipped CSV, 404s when a file is absent
  BSE: plain CSV, and answers a MISSING file with 200 + an HTML page — so the
       body must be sniffed rather than trusted by status code alone.

Conventions, both exchanges:
  TckrSymb  XpryDt(ISO)  StrkPric  OptnTp  OpnIntrst  ChngInOpnIntrst
  TtlTradgVol  ClsPric  UndrlygPric
StrkPric is the plain strike here — unlike Kotak's scrip master, it is NOT
scaled by 100.
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import pandas as pd

from ..market_hours import IST
from .base import DataSourceError
from .upstox_source import ChainRow

log = logging.getLogger("stradegiz.bhavcopy")

#: Both exchanges reject requests without a browser-like agent.
_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass(frozen=True)
class Archive:
    """One exchange's daily derivatives archive."""

    name: str
    url_template: str
    zipped: bool
    headers: dict[str, str]
    underlyings: frozenset[str]


NSE = Archive(
    name="NSE",
    url_template=(
        "https://nsearchives.nseindia.com/content/fo/"
        "BhavCopy_NSE_FO_0_0_0_{d}_F_0000.csv.zip"
    ),
    zipped=True,
    headers={"User-Agent": _AGENT, "Accept": "*/*"},
    underlyings=frozenset(
        {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
    ),
)

BSE = Archive(
    name="BSE",
    url_template=(
        "https://www.bseindia.com/download/BhavCopy/Derivative/"
        "BhavCopy_BSE_FO_0_0_0_{d}_F_0000.CSV"
    ),
    zipped=False,
    headers={
        "User-Agent": _AGENT,
        # BSE serves the file only with a plausible referer.
        "Referer": (
            "https://www.bseindia.com/markets/derivatives/DeriReports/"
            "DeriBhavCopy.aspx"
        ),
        "Accept": "*/*",
    },
    underlyings=frozenset({"SENSEX", "BANKEX"}),
)

ARCHIVES = (NSE, BSE)

#: Retained for callers that predate multi-exchange support.
NSE_UNDERLYINGS = set(NSE.underlyings)
SUPPORTED = set(NSE.underlyings) | set(BSE.underlyings)

#: FinInstrmTp code for index options (STO/STF/IDF are stock options,
#: stock futures and index futures respectively). Same on both exchanges.
INDEX_OPTION = "IDO"

#: EOD rows are stamped after the close so they cannot collide with the
#: 15:30 intraday snapshot on days where both exist.
EOD_TIME = time(15, 40)

#: Every UDiFF file starts with this column, so it distinguishes a real CSV
#: from BSE's HTML "not found" page, which also arrives as HTTP 200.
CSV_SENTINEL = "TradDt"


def archives_for(underlyings: set[str]) -> list[tuple[Archive, set[str]]]:
    """Group the requested underlyings by the archive that carries them."""
    out = []
    for archive in ARCHIVES:
        wanted = {u for u in underlyings if u in archive.underlyings}
        if wanted:
            out.append((archive, wanted))
    return out


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


def download(
    day: date, archive: Archive = NSE, client: httpx.Client | None = None
) -> pd.DataFrame | None:
    """The day's bhavcopy, or None when the exchange has no file for it."""
    url = archive.url_template.format(d=day.strftime("%Y%m%d"))
    owned = client is None
    client = client or httpx.Client(timeout=90, follow_redirects=True)
    try:
        resp = client.get(url, headers=archive.headers)
    except httpx.HTTPError as exc:
        raise DataSourceError(
            f"{archive.name} bhavcopy fetch failed for {day}: {exc}"
        ) from exc
    finally:
        if owned:
            client.close()

    if resp.status_code == 404:
        # Weekend or trading holiday — absence is expected, not an error.
        return None
    if resp.status_code != 200:
        raise DataSourceError(f"{archive.name} bhavcopy {day}: HTTP {resp.status_code}")

    try:
        if archive.zipped:
            zf = zipfile.ZipFile(io.BytesIO(resp.content))
            return pd.read_csv(zf.open(zf.namelist()[0]))

        # BSE answers a missing file with 200 and an HTML page, so the body
        # must be checked; trusting the status code would parse the markup.
        text = resp.text
        if not text.lstrip().startswith(CSV_SENTINEL):
            return None
        return pd.read_csv(io.StringIO(text))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise DataSourceError(
            f"{archive.name} bhavcopy {day}: unreadable file ({exc})"
        ) from exc


def to_rows(df: pd.DataFrame, day: date, underlyings: set[str]) -> list[ChainRow]:
    """Index-option rows for the requested underlyings."""
    wanted = {u for u in underlyings if u in SUPPORTED}
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
    """Rows for one day across whichever exchanges carry the underlyings."""
    rows: list[ChainRow] = []
    for archive, wanted in archives_for(underlyings):
        df = download(day, archive, client)
        if df is None:
            continue
        rows.extend(to_rows(df, day, wanted))
    return rows
