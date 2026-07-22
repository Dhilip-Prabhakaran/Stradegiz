"""The contract every price-data provider must satisfy.

Adding a new provider (Bhavcopy, an intraday feed, a paid vendor) means adding
a file that implements `DataSource` — nothing in the ingestion pipeline changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

# Timeframe identifiers stored in ohlcv.timeframe.
TF_DAILY = "1d"
TF_1MIN = "1m"
TF_5MIN = "5m"
TF_15MIN = "15m"


@dataclass(frozen=True)
class Bar:
    """A single OHLCV candle, provider-agnostic.

    Prices are Decimal rather than float: these are monetary values and float
    rounding compounds badly once indicators and P&L are computed on top.
    """

    symbol: str
    timeframe: str
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class DataSourceError(RuntimeError):
    """Raised when a provider cannot serve a request.

    Providers wrap their own failures in this so the ingestion loop can record
    a per-symbol error and continue rather than aborting the whole run.
    """


@runtime_checkable
class DataSource(Protocol):
    """A provider of historical price bars."""

    #: Stable identifier recorded in ingestion_state.source.
    name: str

    def supports(self, timeframe: str) -> bool:
        """Whether this provider can serve the given timeframe."""
        ...

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        start: date,
        end: date,
    ) -> list[Bar]:
        """Return bars for `symbol` in [start, end].

        `symbol` is always the canonical exchange symbol (e.g. "RELIANCE").
        Any provider-specific renaming is the provider's own concern.
        """
        ...
