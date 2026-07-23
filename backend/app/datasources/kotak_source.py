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

SEG_NSE_FO = "nse_fo"
SEG_BSE_FO = "bse_fo"

#: underlying -> exchange segment. SENSEX/BANKEX are BSE contracts, so they
#: live in a different scrip master from the NSE indices.
UNDERLYINGS = {
    "NIFTY": SEG_NSE_FO,
    "BANKNIFTY": SEG_NSE_FO,
    "FINNIFTY": SEG_NSE_FO,
    "MIDCPNIFTY": SEG_NSE_FO,
    "SENSEX": SEG_BSE_FO,
    "BANKEX": SEG_BSE_FO,
}


def segment_for(underlying: str) -> str:
    seg = UNDERLYINGS.get(underlying)
    if seg is None:
        raise DataSourceError(
            f"unknown underlying: {underlying} "
            f"(known: {', '.join(sorted(UNDERLYINGS))})"
        )
    return seg

#: Quote-response field names, confirmed against a live payload. These match
#: neither the published docs nor the scrip-master naming, so they are pinned
#: here rather than guessed: the token arrives as `exchange_token`, open
#: interest as `open_int`, and volume as `last_volume`.
Q_TOKEN = ("exchange_token", "instrument_token", "token")
Q_OI = ("open_int", "open_interest", "oi")
Q_VOLUME = ("last_volume", "volume", "trade_volume")
Q_LTP = ("ltp", "last_traded_price", "last_price")

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


#: Keys Kotak uses to report failures. It returns these rather than raising,
#: and the spelling varies by endpoint ("Error Message" bit us once already).
ERROR_KEYS = ("error", "Error", "Error Message", "errorMessage", "emsg")


def _check_error(resp: Any, what: str) -> None:
    """The SDK reports failures by returning them; surface those as errors."""
    if not isinstance(resp, dict):
        return
    for key in ERROR_KEYS:
        if resp.get(key):
            raise DataSourceError(f"Kotak {what}: {str(resp[key])[:250]}")


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
        missing = creds.missing()
        if missing:
            raise DataSourceError(
                f"Kotak credentials missing in .env: {', '.join(missing)}"
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
            import pyotp
            from neo_api_client import NeoAPI
        except ImportError as exc:  # pragma: no cover
            raise DataSourceError(
                "neo_api_client/pyotp not installed — see requirements-recorder.txt"
            ) from exc

        api = NeoAPI(consumer_key=self._creds.consumer_key, environment="prod")

        # The 2FA session is mandatory even for market data: without it the
        # scrip and quote endpoints answer "Complete the 2fa process".
        # The TOTP secret is a static seed, so this runs unattended.
        totp = pyotp.TOTP(self._creds.totp_secret).now()
        login = api.totp_login(
            mobile_number=self._creds.mobile, ucc=self._creds.ucc, totp=totp
        )
        _check_error(login, "totp_login")

        session = api.totp_validate(mpin=self._creds.mpin)
        _check_error(session, "totp_validate")

        self._api = api
        log.info("Kotak session established")
        return self._api

    def _reset(self) -> None:
        """Drop the session so the next call logs in afresh."""
        self._api = None

    def _call(self, method: str, what: str, **kwargs: Any) -> Any:
        """Invoke an SDK method, re-logging-in once if the session has lapsed.

        Sessions expire (roughly daily), so one transparent re-login keeps the
        long-running recorder going without a restart.
        """
        for attempt in (1, 2):
            try:
                resp = getattr(self._client(), method)(**kwargs)
                _check_error(resp, what)
                return resp
            except DataSourceError as exc:
                expired = "2fa" in str(exc).lower() or "session" in str(exc).lower()
                if attempt == 2 or not expired:
                    raise
                log.warning("Kotak session lapsed — re-logging in")
                self._reset()

    # --- instruments --------------------------------------------------

    def _instruments(self, underlying: str, today: date) -> list[dict[str, Any]]:
        """Option instruments for an underlying, cached for the trading day.

        search_scrip downloads the entire F&O scrip master and filters it in
        pandas, so this must not run on every five-minute snapshot.
        """
        cached = self._scrip_cache.get(underlying)
        if cached and cached[0] == today:
            return cached[1]

        segment = segment_for(underlying)
        resp = self._call(
            "search_scrip",
            "search_scrip",
            exchange_segment=segment,
            # The SDK lowercases the column then applies str.contains with the
            # symbol verbatim, so an uppercase term would never match.
            symbol=underlying.lower(),
            option_type="CE,PE",
        )
        rows = _rows(resp)

        # That filter is a substring match, so "nifty" also pulls in
        # BANKNIFTY/FINNIFTY/MIDCPNIFTY. Narrow to the exact underlying or the
        # chain would blend strikes from several indices.
        rows = [
            r
            for r in rows
            if str(_pick(r, COL_NAME) or "").strip().upper() == underlying
        ]
        if not rows:
            raise DataSourceError(
                f"scrip master returned no {underlying} options in {segment}"
            )

        self._scrip_cache[underlying] = (today, rows)
        log.info(
            "cached %d %s option instruments (%s) for %s",
            len(rows),
            underlying,
            segment,
            today,
        )
        return rows

    def expiries(self, underlying: str) -> list[date]:
        segment_for(underlying)  # validate early
        today = datetime.now().date()
        found = {
            d
            for r in self._instruments(underlying, today)
            if (d := _parse_expiry(_pick(r, COL_EXPIRY))) is not None
        }
        return sorted(found)

    # --- chain --------------------------------------------------------

    def fetch_chain(
        self, underlying: str, expiry: date, ts: datetime
    ) -> list[ChainRow]:
        segment = segment_for(underlying)

        # token -> (strike, option_type) for this expiry
        meta: dict[str, dict[str, Any]] = {}
        for r in self._instruments(underlying, ts.date()):
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
        for token, quote in self._quotes(list(meta), segment).items():
            info = meta.get(str(token))
            if info is None:
                continue

            oi = _int(_pick(quote, *Q_OI))
            volume = _int(_pick(quote, *Q_VOLUME))
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
                    # Kotak's quote carries no previous-day OI; OI change is
                    # derived from consecutive snapshots, which is the point
                    # of keeping this archive.
                    prev_oi=None,
                    volume=volume,
                    ltp=_dec(_pick(quote, *Q_LTP)),
                    # Neither implied volatility nor the underlying spot are
                    # present in this payload; both columns stay nullable.
                    iv=None,
                    spot=None,
                )
            )
        return rows

    def _quotes(self, tokens: list[str], segment: str) -> dict[str, dict[str, Any]]:
        """Quotes keyed by instrument token.

        Batched because the SDK encodes every token into the request URL, and
        a full index chain would otherwise build an unreasonably long one.
        """
        out: dict[str, dict[str, Any]] = {}
        for batch in _chunks(tokens, 50):
            instruments = [
                {"instrument_token": t, "exchange_segment": segment} for t in batch
            ]
            resp = self._call(
                "quotes",
                "quotes",
                instrument_tokens=instruments,
                quote_type="all",
            )
            for q in _rows(resp):
                token = _pick(q, *Q_TOKEN)
                if token is not None:
                    out[str(token)] = q
        return out


def _chunks(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]
