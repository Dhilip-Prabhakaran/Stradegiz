"""Daily bars from Yahoo Finance via the `yfinance` package.

Free and reliable enough for end-of-day data, which is all phase 1 needs.
Yahoo's intraday history is both delayed and shallow (~60 days), so this
provider deliberately declares daily support only.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import yfinance as yf

from .base import TF_DAILY, Bar, DataSource, DataSourceError


class YFinanceSource(DataSource):
    name = "yfinance"

    #: Yahoo suffixes Indian tickers by exchange. Keeping this mapping here
    #: means the rest of the system only ever sees canonical NSE symbols.
    _EXCHANGE_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}

    def __init__(self, exchange: str = "NSE") -> None:
        if exchange not in self._EXCHANGE_SUFFIX:
            raise ValueError(f"unsupported exchange: {exchange}")
        self.exchange = exchange

    def supports(self, timeframe: str) -> bool:
        return timeframe == TF_DAILY

    def _to_yahoo(self, symbol: str) -> str:
        return f"{symbol}{self._EXCHANGE_SUFFIX[self.exchange]}"

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        start: date,
        end: date,
    ) -> list[Bar]:
        if not self.supports(timeframe):
            raise DataSourceError(f"{self.name} does not serve timeframe {timeframe}")

        try:
            # Ticker.history returns flat columns, unlike download() which
            # switches to a MultiIndex depending on argument shape.
            # `end` is exclusive in Yahoo's API, so push it out a day to make
            # the caller's [start, end] range inclusive as documented.
            frame = yf.Ticker(self._to_yahoo(symbol)).history(
                start=start,
                end=end + timedelta(days=1),
                interval="1d",
                auto_adjust=False,  # keep raw traded prices
                actions=False,
            )
        except Exception as exc:  # yfinance raises a variety of network errors
            raise DataSourceError(f"{self.name} fetch failed for {symbol}: {exc}") from exc

        if frame is None or frame.empty:
            return []

        bars: list[Bar] = []
        for ts, row in frame.iterrows():
            # A missing OHLC value means a malformed row; skip rather than
            # storing a NaN that would silently poison later indicators.
            if row[["Open", "High", "Low", "Close"]].isna().any():
                continue

            bars.append(
                Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=ts.to_pydatetime(),
                    open=_dec(row["Open"]),
                    high=_dec(row["High"]),
                    low=_dec(row["Low"]),
                    close=_dec(row["Close"]),
                    volume=int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
                )
            )
        return bars


def _dec(value: float) -> Decimal:
    """Convert via str so we get the decimal the float was printed as,
    not its full binary expansion."""
    return Decimal(str(round(float(value), 4)))
