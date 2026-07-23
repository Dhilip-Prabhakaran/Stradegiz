"""Stradegiz HTTP API."""

from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import oi_queries, queries, status
from .datasources.base import TF_DAILY

app = FastAPI(title="Stradegiz API", version="0.1.0")

# The Vite dev server runs on a different origin during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5273", "http://127.0.0.1:5273"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/capture")
def capture_health() -> dict:
    """Token validity + last capture per underlying, for the UI staleness banner."""
    return status.capture_health()


@app.get("/api/symbols")
def symbols() -> list[dict]:
    return queries.list_symbols()


@app.get("/api/ohlcv")
def ohlcv(
    symbol: str = Query(..., min_length=1, max_length=32),
    timeframe: str = Query(TF_DAILY),
    start: date | None = Query(None),
    end: date | None = Query(None),
    limit: int = Query(5000, ge=1, le=20000),
) -> dict:
    bars = queries.get_ohlcv(symbol.upper(), timeframe, start, end, limit)
    if not bars:
        raise HTTPException(
            status_code=404,
            detail=f"no {timeframe} bars for {symbol.upper()}",
        )
    return {"symbol": symbol.upper(), "timeframe": timeframe, "bars": bars}


# --- F&O open interest -------------------------------------------------


@app.get("/api/oi/expiries")
def oi_expiries(underlying: str = Query("NIFTY")) -> list[str]:
    return oi_queries.available_expiries(underlying.upper())


@app.get("/api/oi/coverage")
def oi_coverage(underlying: str = Query("NIFTY")) -> dict:
    """Which history exists, so the UI can explain an empty intraday view."""
    return oi_queries.coverage(underlying.upper())


@app.get("/api/oi/strikes")
def oi_strikes(
    underlying: str = Query("NIFTY"),
    expiry: date = Query(...),
) -> list[float]:
    return oi_queries.available_strikes(underlying.upper(), expiry)


@app.get("/api/oi/analysis")
def oi_analysis(
    underlying: str = Query("NIFTY"),
    expiry: date = Query(...),
    strike: float = Query(...),
    on: date | None = Query(None, description="single trading day (intraday)"),
    start: date | None = Query(None, description="range start (daily)"),
    end: date | None = Query(None, description="range end (daily)"),
    interval: str = Query("5min"),
) -> dict:
    # `on` stays supported for the intraday screen; a start/end pair drives
    # the daily view over the bhavcopy backfill.
    if start is None or end is None:
        if on is None:
            raise HTTPException(
                status_code=400, detail="provide either 'on' or 'start' and 'end'"
            )
        start = end = on

    try:
        rows = oi_queries.oi_analysis(
            underlying.upper(), expiry, strike, start, end, interval
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "underlying": underlying.upper(),
        "expiry": expiry.isoformat(),
        "strike": strike,
        "date": start.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "interval": interval,
        "rows": rows,
    }
