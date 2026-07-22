"""Live option-chain snapshots from the Upstox market-data API.

Data access only — no order placement anywhere in this project.

Endpoint: GET https://api.upstox.com/v2/option/chain
    ?instrument_key=NSE_INDEX|Nifty 50&expiry_date=YYYY-MM-DD
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx

from .base import DataSourceError

BASE_URL = "https://api.upstox.com/v2"

# Upstox identifies underlyings by instrument key, not plain symbol.
INSTRUMENT_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
}


@dataclass(frozen=True)
class ChainRow:
    """One strike, one side, at one instant."""

    underlying: str
    expiry: date
    strike: Decimal
    option_type: str  # CE | PE
    ts: datetime
    oi: int
    prev_oi: int | None
    volume: int
    ltp: Decimal | None
    iv: Decimal | None
    spot: Decimal | None


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(round(float(value), 4)))
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


class UpstoxOptionChain:
    """Fetches the full option chain for one underlying and expiry."""

    name = "upstox"

    def __init__(self, access_token: str, timeout: float = 10.0) -> None:
        if not access_token:
            # Failing loudly here beats a confusing 401 later.
            raise DataSourceError(
                "UPSTOX_ACCESS_TOKEN is not set — the recorder cannot authenticate"
            )
        self._token = access_token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }

    def expiries(self, underlying: str) -> list[date]:
        """Contract expiries currently available for the underlying."""
        key = INSTRUMENT_KEYS.get(underlying)
        if key is None:
            raise DataSourceError(f"unknown underlying: {underlying}")

        try:
            resp = httpx.get(
                f"{BASE_URL}/option/contract",
                params={"instrument_key": key},
                headers=self._headers(),
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise DataSourceError(f"contract request failed: {exc}") from exc

        payload = self._payload(resp)
        seen = {
            row.get("expiry")
            for row in payload
            if isinstance(row, dict) and row.get("expiry")
        }
        return sorted(date.fromisoformat(e) for e in seen)

    def fetch_chain(
        self, underlying: str, expiry: date, ts: datetime
    ) -> list[ChainRow]:
        """The full chain as flat rows, one per (strike, side).

        `ts` is passed in rather than read here so every row in a snapshot
        shares one timestamp — otherwise rows drift across a bucket boundary
        and the 5-minute grouping splits a single snapshot in two.
        """
        key = INSTRUMENT_KEYS.get(underlying)
        if key is None:
            raise DataSourceError(f"unknown underlying: {underlying}")

        try:
            resp = httpx.get(
                f"{BASE_URL}/option/chain",
                params={"instrument_key": key, "expiry_date": expiry.isoformat()},
                headers=self._headers(),
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise DataSourceError(f"chain request failed: {exc}") from exc

        rows: list[ChainRow] = []
        for strike_row in self._payload(resp):
            if not isinstance(strike_row, dict):
                continue

            strike = _dec(strike_row.get("strike_price"))
            if strike is None:
                continue
            spot = _dec(strike_row.get("underlying_spot_price"))

            for field, side in (("call_options", "CE"), ("put_options", "PE")):
                leg = strike_row.get(field) or {}
                market = leg.get("market_data") or {}
                greeks = leg.get("option_greeks") or {}

                # A strike with no OI and no traded volume carries no signal;
                # skipping keeps the archive from filling with empty far strikes.
                oi = _int(market.get("oi"))
                volume = _int(market.get("volume"))
                if oi == 0 and volume == 0:
                    continue

                rows.append(
                    ChainRow(
                        underlying=underlying,
                        expiry=expiry,
                        strike=strike,
                        option_type=side,
                        ts=ts,
                        oi=oi,
                        prev_oi=_int(market.get("prev_oi")) or None,
                        volume=volume,
                        ltp=_dec(market.get("ltp")),
                        iv=_dec(greeks.get("iv")),
                        spot=spot,
                    )
                )
        return rows

    @staticmethod
    def _payload(resp: httpx.Response) -> list[Any]:
        if resp.status_code == 401:
            raise DataSourceError(
                "Upstox returned 401 — the access token is expired or invalid. "
                "Upstox tokens expire daily and must be regenerated."
            )
        if resp.status_code == 429:
            raise DataSourceError("Upstox rate limit hit (429)")
        if resp.status_code >= 400:
            raise DataSourceError(f"Upstox HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            body = resp.json()
        except ValueError as exc:
            raise DataSourceError("Upstox returned a non-JSON body") from exc

        data = body.get("data")
        if data is None:
            raise DataSourceError(f"unexpected Upstox payload: {str(body)[:200]}")
        return data if isinstance(data, list) else [data]
