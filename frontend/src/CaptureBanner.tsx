import { useEffect, useState } from 'react';
import { fetchCaptureHealth, type CaptureHealth } from './api';

const POLL_MS = 60_000;

/** Human "2h 14m" from a seconds count. */
function humanLeft(seconds: number): string {
  if (seconds <= 0) return 'expired';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/**
 * Turns the silent, unrecoverable failure mode (token expired → nothing
 * recorded all day) into a visible banner. Only shows when something needs
 * attention; stays out of the way when capture is healthy.
 */
export function CaptureBanner() {
  const [health, setHealth] = useState<CaptureHealth | null>(null);

  useEffect(() => {
    const load = () => fetchCaptureHealth().then(setHealth).catch(() => setHealth(null));
    load();
    const id = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(id);
  }, []);

  if (!health) return null;

  const { token, captures, market_open, healthy } = health;

  // Nothing wrong — say nothing.
  if (healthy && !captures.some((c) => c.status === 'error')) return null;

  let level: 'warn' | 'error' = 'warn';
  let message = '';

  if (!token.present) {
    level = 'error';
    message =
      'No Upstox token stored. Recording is stopped — paste today’s token to start capturing.';
  } else if (!token.valid) {
    level = 'error';
    message = market_open
      ? 'Upstox token has expired. Recording is stopped during market hours — paste a fresh token now.'
      : 'Upstox token has expired. Paste a fresh one before the next session (09:15 IST).';
  } else {
    const failing = captures.filter((c) => c.status === 'error');
    if (failing.length) {
      level = 'warn';
      const which = failing.map((c) => c.underlying).join(', ');
      message = `Last capture failed for ${which}: ${failing[0].detail ?? 'unknown error'}`;
    }
  }

  if (!message) return null;

  return (
    <div className={`capture-banner ${level}`} role="alert">
      <span className="banner-icon">{level === 'error' ? '⛔' : '⚠️'}</span>
      <span className="banner-msg">{message}</span>
      {token.valid && token.seconds_left != null && (
        <span className="banner-meta">token valid {humanLeft(token.seconds_left)}</span>
      )}
      <code className="banner-cmd">
        docker compose run --rm backend python -m app.set_token &lt;TOKEN&gt;
      </code>
    </div>
  );
}
