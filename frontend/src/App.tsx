import { useEffect, useState } from 'react';
import { CaptureBanner } from './CaptureBanner';
import { EmptyState } from './EmptyState';
import { OiTable } from './OiTable';
import {
  fetchCoverage,
  fetchExpiries,
  fetchOiAnalysis,
  fetchStrikes,
  type Coverage,
  type OiAnalysis,
} from './api';

const UNDERLYINGS = ['NIFTY', 'BANKNIFTY', 'SENSEX'];
const INTERVALS = ['1min', '3min', '5min', '15min', '30min', '60min', '1day'];

/** The daily interval spans trading days (backfilled EOD data) rather than
 *  buckets within one day, so it swaps the single date for a range. */
const DAILY = '1day';
const DEFAULT_RANGE_DAYS = 90;

/** How often Live mode re-polls. The recorder writes every 5 min, so a
 *  30s refresh picks up a new snapshot well within one bucket. */
const LIVE_REFRESH_MS = 30_000;

/** Today in IST, regardless of where the viewer's machine is. */
const todayIST = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());

/** An ISO date `days` before today (IST). */
const daysAgoIST = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(d);
};

export default function App() {
  const [underlying, setUnderlying] = useState('NIFTY');
  const [expiries, setExpiries] = useState<string[]>([]);
  const [expiry, setExpiry] = useState('');
  const [strikes, setStrikes] = useState<number[]>([]);
  const [strike, setStrike] = useState<number | null>(null);
  const [on, setOn] = useState(todayIST());
  const [from, setFrom] = useState(daysAgoIST(DEFAULT_RANGE_DAYS));
  const [interval, setIntervalV] = useState('5min');
  const [live, setLive] = useState(true);

  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [data, setData] = useState<OiAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);

  useEffect(() => {
    fetchExpiries(underlying)
      .then((e) => {
        setExpiries(e);
        setExpiry(e[0] ?? '');
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, [underlying]);

  useEffect(() => {
    if (!expiry) return;
    fetchStrikes(underlying, expiry)
      .then((s) => {
        setStrikes(s);
        // Default to the middle strike, usually nearest the money.
        setStrike(s.length ? s[Math.floor(s.length / 2)] : null);
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, [underlying, expiry]);

  // Coverage drives the empty state, and only changes as new days are
  // recorded, so it is fetched per underlying rather than per query.
  useEffect(() => {
    fetchCoverage(underlying).then(setCoverage).catch(() => setCoverage(null));
  }, [underlying]);

  const isDaily = interval === DAILY;

  // Live always reads today (IST); Historical uses the chosen date. Daily
  // spans a range instead, so Live has no meaning there.
  const effectiveDate = live && !isDaily ? todayIST() : on;

  const load = () => {
    if (!expiry || strike === null) return;
    setLoading(true);
    setError(null);
    const range = isDaily
      ? { start: from, end: on }
      : { on: effectiveDate };
    fetchOiAnalysis({ underlying, expiry, strike, ...range, interval })
      .then((d) => {
        setData(d);
        setUpdatedAt(
          new Intl.DateTimeFormat('en-GB', {
            timeZone: 'Asia/Kolkata',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
          }).format(new Date()),
        );
      })
      .catch((e) => {
        setError(String(e.message ?? e));
        setData(null);
      })
      .finally(() => setLoading(false));
  };

  // Load once the selection is complete, and on any change to it.
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [underlying, expiry, strike, effectiveDate, from, interval, live]);

  // Poll only in Live mode. Historical and daily data never change.
  useEffect(() => {
    if (!live || isDaily) return;
    const id = window.setInterval(load, LIVE_REFRESH_MS);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, underlying, expiry, strike, interval]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          Stradegiz <span className="tag">OI Analysis</span>
        </div>
      </header>

      <CaptureBanner />

      <section className="controls">
        <div className="mode">
          <span>Mode</span>
          <div className="radios">
            <label className="radio">
              <input
                type="radio"
                checked={live && !isDaily}
                disabled={isDaily}
                onChange={() => setLive(true)}
              />
              Live data
            </label>
            <label className="radio">
              <input
                type="radio"
                checked={!live || isDaily}
                disabled={isDaily}
                onChange={() => setLive(false)}
              />
              Historical
            </label>
          </div>
        </div>

        <label>
          <span>Name</span>
          <select value={underlying} onChange={(e) => setUnderlying(e.target.value)}>
            {UNDERLYINGS.map((u) => (
              <option key={u}>{u}</option>
            ))}
          </select>
        </label>

        <label>
          <span>Expiry</span>
          <select value={expiry} onChange={(e) => setExpiry(e.target.value)}>
            {expiries.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </label>

        <label>
          <span>Strike</span>
          <select
            value={strike ?? ''}
            onChange={(e) => setStrike(Number(e.target.value))}
          >
            {strikes.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>

        {isDaily && (
          <label>
            <span>From</span>
            <input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </label>
        )}

        <label>
          <span>{isDaily ? 'To' : 'Date'}</span>
          <input
            type="date"
            value={effectiveDate}
            disabled={live && !isDaily}
            onChange={(e) => setOn(e.target.value)}
          />
        </label>

        <label>
          <span>Interval</span>
          <select value={interval} onChange={(e) => setIntervalV(e.target.value)}>
            {INTERVALS.map((i) => (
              <option key={i}>{i}</option>
            ))}
          </select>
        </label>

        <button onClick={load} disabled={loading}>
          {loading ? '…' : 'Go'}
        </button>

        <div className="updated">
          {live && <span className="live-dot" />}
          {updatedAt ? `Updated ${updatedAt} IST` : ''}
        </div>
      </section>

      <main className="content">
        {error && <div className="error">{error}</div>}

        {/* A single row is not a variation to read — it is the lone
            end-of-day figure — so intraday treats that as empty too. */}
        {!error && !loading && !isDaily && data && data.rows.length <= 1 && (
          <EmptyState
            coverage={coverage}
            date={effectiveDate}
            onUseDaily={() => {
              setLive(false);
              setIntervalV(DAILY);
            }}
          />
        )}

        {!error && data && (isDaily || data.rows.length > 1) && (
          <OiTable rows={data.rows} strike={data.strike} interval={data.interval} />
        )}
      </main>
    </div>
  );
}
