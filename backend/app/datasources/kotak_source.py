"""Live option-chain snapshots from the Kotak Neo API.

Data access only — this project never places orders.

Findings from reading the installed SDK source (neo_api_client 2.0.x), which
differ from the published docs and drive the design here:

* **Market data needs only the consumer key.** `quotes` and `scrip_search`
  send `Authorization: <consumer_key>` and nothing else, whereas account APIs
  (positions, holdings) additionally send `Sid`/`Auth` from the TOTP session.
  So no login, no MPIN, no TOTP, and no session that could collide with
  another tool using the same account.
* `NeoAPI` takes `consumer_key` only — `consumer_secret` is commented out.
* The SDK **returns** error dicts (`{'error': [...]}`) rather than raising.
* `search_scrip` downloads and pandas-filters the whole F&O scrip-master CSV
  on every call, so results are cached per day here — re-downloading it every
  five minutes would be slow and rude.
* Scrip-master column quirks: the strike column is literally ``dStrikePrice;``
  (trailing semicolon) and its values are **multiplied by 100**.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from ..config import KotakCreds
from .base import DataSourceError
from .upstox_source import ChainRow  # shared flat-row shape

log = logging.getLogger("stradegiz.kotak")

SEG_FO = "nse_fo"

#: Underlying names as they appear in the scrip master's pSymbolName column.
FO_SYMBOL = {
    "NIFTY": "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "FINNIFTY": "FINNIFTY",
    "MIDCPNIFTY": "MIDCPNIFTY",
}

#: Scrip-master column names, including the trailing-semicolon quirk.
COL_TOKEN = "pSymbol"
COL_NAME = "pSymbolName"
COL_OPTION_TYPE = "pOptionType"
COL_EXPIRY = "pExpiryDate"
COL_STRIKE = "dStrikePrice;"

#: The scrip master stores strikes as paise-style integers (value * 100).
STRIKE_SCALE = Decimal(100)


def _pick(row: dict[str, Any], *keys: str) -> Any:
    """First present, non-null value among candidate keys (case-insensitive)."""
    lowered = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        v = lowered.get(key.lower())
        if v not in (None, ""):
            return v
    return None


def _dec(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(round(float(value), 4)))
    except (TypeError, ValueError, InvalidOperation):
        return None


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _check_error(resp: Any, what: str) -> None:
    """The SDK reports failures by returning them; surface those as errors."""
    if isinstance(resp, dict):
        if resp.get("error"):
            raise DataSourceError(f"Kotak {what} error: {str(resp['error'])[:200]}")
        if resp.get("Error"):
            raise DataSourceError(f"Kotak {what} error: {str(resp['Error'])[:200]}")


def _rows(resp: Any) -> list[dict[str, Any]]:
    """Normalise the SDK's varied return shapes to a list of dicts."""
    if resp is None:
        return []
    if isinstance(resp, list):
        return [r for r in resp if isinstance(r, dict)]
    if isinstance(resp, dict):
        # "No data found..." comes back as a bare message dict.
        if "message" in resp and "data" not in resp:
            return []
        for key in ("data", "result", "Success", "success"):
            inner = resp.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
        return [resp]
    return []


def _parse_expiry(value: Any) -> date | None:
    """search_scrip normalises expiry to '%d%b%Y' (e.g. 31JUL2026)."""
    if value in (None, ""):
        return None
    for fmt in ("%d%b%Y", "%d-%b-%Y", "%d%b%y"):
        try:
            return datetime.strptime(str(value).upper().strip(), fmt).date()
        except ValueError:
            continue
    return None


class KotakNeoSource:
    name = "kotak"

    def __init__(self, creds: KotakCreds) -> None:
        if not creds.consumer_key:
            raise DataSourceError(
                "KOTAK_CONSUMER_KEY is not set — market data needs the app token "
                "from Kotak Neo: Invest -> Trade API -> API Dashboard"
            )
        self._creds = creds
        self._api: Any = None
        # Instrument metadata per underlying, refreshed once per trading day.
        self._scrip_cache: dict[str, tuple[date, list[dict[str, Any]]]] = {}

    # --- client -------------------------------------------------------

    def _client(self) -> Any:
        if self._api is not None:
            return self._api

        try:
            from neo_api_client import NeoAPI
        except ImportError as exc:  # pragma: no cover
            raise DataSourceError(
                "neo_api_client is not installed — see requirements-recorder.txt"
            ) from exc

        # consumer_key alone authorises market data; no session is created,
        # so this cannot disturb another tool logged into the same account.
        self._api = NeoAPI(
            consumer_key=self._creds.consumer_key,
            environment="prod",
        )
        log.info("Kotak client ready (market-data mode, no session)")
        return self._api

    # --- instruments --------------------------------------------------

    def _instruments(self, symbol: str, today: date) -> list[dict[str, Any]]:
        """Option instruments for an underlying, cached for the trading day.

        search_scrip downloads the entire F&O scrip master and filters it in
        pandas, so this must not run on every five-minute snapshot.
        """
        cached = self._scrip_cache.get(symbol)
        if cached and cached[0] == today:
            return cached[1]

        resp = self._client().search_scrip(
            exchange_segment=SEG_FO,
            symbol=symbol,
            option_type="CE,PE",
        )
        _check_error(resp, "search_scrip")
        rows = _rows(resp)
        if not rows:
            raise DataSourceError(f"scrip master returned no {symbol} options")

        self._scrip_cache[symbol] = (today, rows)
        log.info("cached %d %s option instruments for %s", len(rows), symbol, today)
        return rows

    def expiries(self, underlying: str) -> list[date]:
        symbol = FO_SYMBOL.get(underlying)
        if symbol is None:
            raise DataSourceError(f"unknown underlying: {underlying}")

        today = datetime.now().date()
        found = {
            d
            for r in self._instruments(symbol, today)
            if (d := _parse_expiry(_pick(r, COL_EXPIRY))) is not None
        }
        return sorted(found)

    # --- chain --------------------------------------------------------

    def fetch_chain(
        self, underlying: str, expiry: date, ts: datetime
    ) -> list[ChainRow]:
        symbol = FO_SYMBOL.get(underlying)
        if symbol is None:
            raise DataSourceError(f"unknown underlying: {underlying}")

        # token -> (strike, option_type) for this expiry
        meta: dict[str, dict[str, Any]] = {}
        for r in self._instruments(symbol, ts.date()):
            if _parse_expiry(_pick(r, COL_EXPIRY)) != expiry:
                continue

            token = _pick(r, COL_TOKEN)
            opt = _pick(r, COL_OPTION_TYPE)
            raw_strike = _dec(_pick(r, COL_STRIKE, "dStrikePrice"))
            if token is None or raw_strike is None or opt is None:
                continue

            opt = str(opt).upper().strip()
            if opt not in ("CE", "PE"):
                continue

            meta[str(token)] = {
                "strike": raw_strike / STRIKE_SCALE,
                "option_type": opt,
            }

        if not meta:
            raise DataSourceError(
                f"no {underlying} option instruments for expiry {expiry}"
            )

        rows: list[ChainRow] = []
        for token, quote in self._quotes(list(meta)).items():
            info = meta.get(str(token))
            if info is None:
                continue

            oi = _int(_pick(quote, "open_interest", "oi", "openInterest", "OI"))
            volume = _int(_pick(quote, "volume", "v", "trade_volume", "vol"))
            # A strike with neither OI nor volume carries no signal; skipping
            # keeps the archive free of empty far-out strikes.
            if oi == 0 and volume == 0:
                continue

            rows.append(
                ChainRow(
                    underlying=underlying,
                    expiry=expiry,
                    strike=info["strike"],
                    option_type=info["option_type"],
                    ts=ts,
                    oi=oi,
                    prev_oi=_int(_pick(quote, "prev_oi", "previous_oi")) or None,
                    volume=volume,
                    ltp=_dec(_pick(quote, "last_traded_price", "ltp", "last_price")),
                    iv=_dec(_pick(quote, "iv", "implied_volatility")),
                    spot=_dec(_pick(quote, "underlying_spot_price", "spot")),
                )
            )
        return rows

    def _quotes(self, tokens: list[str]) -> dict[str, dict[str, Any]]:
        """Quotes keyed by instrument token.

        Batched because the SDK encodes every token into the request URL, and
        a full index chain would otherwise build an unreasonably long one.
        """
        out: dict[str, dict[str, Any]] = {}
        for batch in _chunks(tokens, 50):
            instruments = [
                {"instrument_token": t, "exchange_segment": SEG_FO} for t in batch
            ]
            resp = self._client().quotes(
                instrument_tokens=instruments, quote_type="all"
            )
            _check_error(resp, "quotes")
            for q in _rows(resp):
                token = _pick(q, "instrument_token", COL_TOKEN, "token", "tk")
                if token is not None:
                    out[str(token)] = q
        return out


def _chunks(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]
