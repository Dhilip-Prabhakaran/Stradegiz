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

interface Alert {
  level: 'warn' | 'error';
  message: string;
  /** Shown only when the fix is something the user must type. */
  command?: string;
}

/**
 * Decides what (if anything) needs the user's attention.
 *
 * The two providers fail differently: Upstox needs a token pasted by hand, so
 * its absence is the fault to report. Kotak logs itself in, so there is no
 * token to check — a broken login shows up as failing captures instead.
 */
function diagnose(h: CaptureHealth): Alert | null {
  const { auth, captures, market_open, stale } = h;
  const failing = captures.filter((c) => c.status === 'error');

  if (auth.mode === 'manual-token' && auth.manual_action_needed) {
    return {
      level: 'error',
      message: !auth.present
        ? 'No Upstox token stored. Recording is stopped — paste today’s token to start capturing.'
        : market_open
          ? 'Upstox token has expired. Recording is stopped during market hours — paste a fresh token now.'
          : 'Upstox token has expired. Paste a fresh one before the next session (09:15 IST).',
      command: 'docker compose run --rm backend python -m app.set_token <TOKEN>',
    };
  }

  if (failing.length) {
    const which = failing.map((c) => c.underlying).join(', ');
    return {
      level: 'error',
      message: `Capture failing for ${which}: ${failing[0].detail ?? 'unknown error'}`,
    };
  }

  if (stale) {
    return {
      level: 'warn',
      message:
        'No successful capture recently while the market is open — the recorder may be down.',
      command: 'docker compose up -d recorder',
    };
  }

  return null;
}

/**
 * Turns the silent, unrecoverable failure mode (capture stops → nothing
 * recorded all day) into a visible banner. Shows only when something needs
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

  const alert = diagnose(health);
  if (!alert) return null;

  const secondsLeft = health.auth.seconds_left;

  return (
    <div className={`capture-banner ${alert.level}`} role="alert">
      <span className="banner-icon">{alert.level === 'error' ? '⛔' : '⚠️'}</span>
      <span className="banner-msg">{alert.message}</span>
      {health.auth.mode === 'manual-token' && health.auth.valid && secondsLeft != null && (
        <span className="banner-meta">token valid {humanLeft(secondsLeft)}</span>
      )}
      {alert.command && <code className="banner-cmd">{alert.command}</code>}
    </div>
  );
}
