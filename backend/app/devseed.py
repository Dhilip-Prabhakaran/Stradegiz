"""Generate SYNTHETIC option-chain snapshots for development.

This is fabricated data for exercising the UI and queries before live
credentials exist. It is not market data and must never be presented as such.

    docker compose run --rm backend python -m app.devseed
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .db import connection

IST = ZoneInfo("Asia/Kolkata")
UNDERLYING = "NIFTY"
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def generate(day: date, expiry: date, spot0: float = 24150.0) -> int:
    random.seed(42)  # reproducible so repeated runs are comparable

    strikes = [spot0 + (i * 50) for i in range(-5, 6)]
    start = datetime.combine(day, MARKET_OPEN, tzinfo=IST)
    end = datetime.combine(day, MARKET_CLOSE, tzinfo=IST)

    # Seed each (strike, side) with a starting OI and premium.
    state = {
        (k, side): {
            "oi": random.randint(20_000, 400_000) * 25,
            "ltp": max(0.05, abs(spot0 - k) * 0.12 + random.uniform(5, 60)),
        }
        for k in strikes
        for side in ("CE", "PE")
    }

    rows = []
    spot = spot0
    ts = start
    while ts <= end:
        spot += random.uniform(-18, 18)
        for k in strikes:
            for side in ("CE", "PE"):
                s = state[(k, side)]
                s["oi"] = max(0, s["oi"] + random.randint(-60_000, 60_000))
                # Calls gain when spot rises, puts when it falls.
                drift = (spot - spot0) * (0.05 if side == "CE" else -0.05)
                s["ltp"] = max(0.05, s["ltp"] + drift * 0.1 + random.uniform(-2, 2))
                rows.append(
                    (
                        UNDERLYING,
                        expiry,
                        Decimal(str(k)),
                        side,
                        ts,
                        s["oi"],
                        None,
                        random.randint(1_000, 90_000),
                        Decimal(str(round(s["ltp"], 2))),
                        Decimal(str(round(random.uniform(9, 22), 2))),
                        Decimal(str(round(spot, 2))),
                    )
                )
        ts += timedelta(minutes=5)

    with connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO options_chain (underlying, expiry, strike, option_type,
                    ts, oi, prev_oi, volume, ltp, iv, spot)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (underlying, expiry, strike, option_type, ts)
                DO UPDATE SET oi = EXCLUDED.oi, ltp = EXCLUDED.ltp,
                              volume = EXCLUDED.volume, iv = EXCLUDED.iv,
                              spot = EXCLUDED.spot
                """,
                rows,
            )
    return len(rows)


def main() -> None:
    today = datetime.now(IST).date()
    expiry = today + timedelta(days=(1 - today.weekday()) % 7)  # next Tuesday
    n = generate(today, expiry)
    print(f"SYNTHETIC: wrote {n} rows for {UNDERLYING} {today} expiry {expiry}")


if __name__ == "__main__":
    main()
