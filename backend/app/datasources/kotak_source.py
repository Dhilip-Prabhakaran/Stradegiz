"""Live option-chain snapshots from the Kotak Neo API.

Data access only — this project never places orders, even though these
credentials could. The account credentials grant full trading access, so they
come from the environment (gitignored .env) and are never logged.

Kotak has no dedicated option-chain endpoint, so the chain is assembled:
    search_scrip(nse_fo, NIFTY, expiry) -> option instrument tokens
    quotes(tokens, "all")               -> OI / LTP / volume per instrument

Auth is via a TOTP secret (a static seed), so unlike Upstox's interactive
OAuth the recorder can generate today's code with pyotp and log in unattended
each morning.

NOTE (verify on first live run): the exact quote field names below are parsed
defensively because the SDK docs did not include a sample payload. The
_pick / _pick_num helpers tolerate several spellings; confirm against a real
response and tighten once seen.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pyotp

from ..config import KotakCreds
from .base import DataSourceError
from .upstox_source import ChainRow  # shared flat-row shape

log = logging.getLogger("stradegiz.kotak")

# Kotak exchange-segment codes.
SEG_FO = "nse_fo"

# Underlying symbols as they appear in the F&O scrip master.
FO_SYMBOL = {
    "NIFTY": "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "FINNIFTY": "FINNIFTY",
    "MIDCPNIFTY": "MIDCPNIFTY",
}


def _pick(row: dict[str, Any], *keys: str) -> Any:
    """First present, non-null value among candidate keys (case-insensitive)."""
    lowered = {k.lower(): v for k, v in row.items()}
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


class KotakNeoSource:
    name = "kotak"

    def __init__(self, creds: KotakCreds) -> None:
        if not creds.is_complete():
            raise DataSourceError(
                "Kotak credentials are incomplete — set KOTAK_* in .env "
                "(consumer_key, consumer_secret, mobile, ucc, mpin, totp_secret)"
            )
        self._creds = creds
        self._client: Any = None

    # --- session ------------------------------------------------------

    def _login(self) -> Any:
        # Imported lazily so the module loads even where the SDK is absent
        # (e.g. running the unit tests), failing only if Kotak is actually used.
        try:
            from neo_api_client import NeoAPI
        except ImportError as exc:  # pragma: no cover
            raise DataSourceError(
                "neo-api-client is not installed — add it to requirements"
            ) from exc

        client = NeoAPI(
            consumer_key=self._creds.consumer_key,
            consumer_secret=self._creds.consumer_secret,
            environment="prod",
        )
        try:
            totp = pyotp.TOTP(self._creds.totp_secret).now()
            client.totp_login(
                mobilenumber=self._creds.mobile, ucc=self._creds.ucc, totp=totp
            )
            client.totp_validate(mpin=self._creds.mpin)
        except Exception as exc:  # SDK raises assorted exception types
            raise DataSourceError(f"Kotak login failed: {exc}") from exc

        log.info("Kotak session established")
        return client

    def _ensure_client(self) -> Any:
        if self._client is None:
            self._client = self._login()
        return self._client

    def _call(self, method: str, **kwargs: Any) -> Any:
        """Invoke an SDK method, re-logging-in once if the session has lapsed.

        Kotak sessions expire (roughly daily), so a single transparent
        re-login keeps the long-running recorder going without a restart.
        """
        for attempt in (1, 2):
            client = self._ensure_client()
            try:
                return getattr(client, method)(**kwargs)
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    raise DataSourceError(f"Kotak {method} failed: {exc}") from exc
                log.warning("Kotak %s failed (%s) — re-logging in", method, exc)
                self._client = None  # force a fresh login on retry

    # --- data ---------------------------------------------------------

    def expiries(self, underlying: str) -> list[date]:
        """Distinct expiries available for the underlying's options."""
        symbol = FO_SYMBOL.get(underlying)
        if symbol is None:
            raise DataSourceError(f"unknown underlying: {underlying}")

        rows = self._scrip_rows(symbol)
        out: set[date] = set()
        for r in rows:
            d = _parse_expiry(_pick(r, "pExpiryDate", "expiry", "pExpiry"))
            if d is not None:
                out.add(d)
        return sorted(out)

    def fetch_chain(
        self, underlying: str, expiry: date, ts: datetime
    ) -> list[ChainRow]:
        symbol = FO_SYMBOL.get(underlying)
        if symbol is None:
            raise DataSourceError(f"unknown underlying: {underlying}")

        # Instruments for this expiry, mapped by token so quote responses can
        # be joined back to their strike and option type.
        meta: dict[str, dict[str, Any]] = {}
        for r in self._scrip_rows(symbol):
            if _parse_expiry(_pick(r, "pExpiryDate", "expiry", "pExpiry")) != expiry:
                continue
            token = _pick(r, "pSymbol", "instrument_token", "pTrdSymbol")
            opt = _pick(r, "pOptionType", "option_type", "optionType")
            strike = _dec(_pick(r, "dStrikePrice", "strike_price", "pStrikePrice"))
            if token is None or opt not in ("CE", "PE") or strike is None:
                continue
            meta[str(token)] = {"strike": strike, "option_type": opt}

        if not meta:
            raise DataSourceError(
                f"no {underlying} option instruments found for expiry {expiry}"
            )

        rows: list[ChainRow] = []
        for token, quote in self._quotes(list(meta.keys())).items():
            info = meta.get(str(token))
            if info is None:
                continue

            oi = _int(_pick(quote, "open_interest", "oi", "openInterest"))
            volume = _int(_pick(quote, "volume", "v", "trade_volume"))
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

    # --- SDK plumbing -------------------------------------------------

    def _scrip_rows(self, symbol: str) -> list[dict[str, Any]]:
        resp = self._call(
            "search_scrip", exchange_segment=SEG_FO, symbol=symbol
        )
        return _as_rows(resp)

    def _quotes(self, tokens: list[str]) -> dict[str, dict[str, Any]]:
        """Quotes keyed by instrument token.

        Requested in batches: a full index chain is a few hundred instruments
        and a single unbounded request risks a provider-side limit.
        """
        by_token: dict[str, dict[str, Any]] = {}
        for batch in _chunks(tokens, 100):
            instruments = [
                {"instrument_token": t, "exchange_segment": SEG_FO} for t in batch
            ]
            resp = self._call("quotes", instrument_tokens=instruments, quote_type="all")
            for q in _as_rows(resp):
                token = _pick(q, "instrument_token", "pSymbol", "token")
                if token is not None:
                    by_token[str(token)] = q
        return by_token


def _as_rows(resp: Any) -> list[dict[str, Any]]:
    """Normalise the SDK's varied return shapes to a list of dicts."""
    if resp is None:
        return []
    if isinstance(resp, dict):
        # SDK commonly wraps results under 'data'/'result'/'Success'.
        for key in ("data", "result", "Success", "success"):
            inner = resp.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
        return [resp]
    if isinstance(resp, list):
        return [r for r in resp if isinstance(r, dict)]
    return []


def _parse_expiry(value: Any) -> date | None:
    """Kotak encodes expiry variously (epoch seconds, or 'DDMMMYYYY')."""
    if value in (None, ""):
        return None
    # Numeric epoch (seconds since 1980 in some Kotak feeds, or unix seconds).
    try:
        epoch = int(float(value))
        if epoch > 10_000_000:  # plausibly a timestamp, not a small id
            # Kotak F&O expiry epochs are seconds from 1980-01-01.
            from datetime import timedelta, timezone

            base = datetime(1980, 1, 1, tzinfo=timezone.utc)
            return (base + timedelta(seconds=epoch)).date()
    except (TypeError, ValueError):
        pass
    for fmt in ("%d%b%Y", "%d-%b-%Y", "%d%b%y"):
        try:
            return datetime.strptime(str(value).upper(), fmt).date()
        except ValueError:
            continue
    return None


def _chunks(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]
