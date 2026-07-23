async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export type Interpretation =
  | 'Long Build Up'
  | 'Short Build Up'
  | 'Short Covering'
  | 'Long Unwinding'
  | 'Neutral';

export interface SideRow {
  oi: number;
  oi_change: number | null;
  ltp: number | null;
  ltp_change: number | null;
  volume: number;
  interpretation: Interpretation;
}

export interface OiRow {
  time: string;
  spot: number | null;
  call: SideRow | null;
  put: SideRow | null;
}

export interface OiAnalysis {
  underlying: string;
  expiry: string;
  strike: number;
  date: string;
  interval: string;
  rows: OiRow[];
}

export interface AuthStatus {
  mode: 'auto-login' | 'manual-token';
  provider: string;
  manual_action_needed: boolean;
  /** Present only for manual-token providers (Upstox). */
  present?: boolean;
  valid?: boolean;
  issued_at?: string | null;
  expires_at?: string | null;
  seconds_left?: number | null;
}

export interface CaptureEntry {
  underlying: string;
  ts: string | null;
  status: string;
  rows_written: number;
  detail: string | null;
}

export interface CaptureHealth {
  now_ist: string;
  market_open: boolean;
  healthy: boolean;
  stale: boolean;
  data_source: string;
  auth: AuthStatus;
  last_success: string | null;
  captures: CaptureEntry[];
}

export const fetchCaptureHealth = () =>
  getJson<CaptureHealth>('/api/health/capture');

export const fetchExpiries = (underlying: string) =>
  getJson<string[]>(`/api/oi/expiries?underlying=${underlying}`);

export const fetchStrikes = (underlying: string, expiry: string) =>
  getJson<number[]>(`/api/oi/strikes?underlying=${underlying}&expiry=${expiry}`);

export const fetchOiAnalysis = (p: {
  underlying: string;
  expiry: string;
  strike: number;
  /** Single trading day, for intraday intervals. */
  on?: string;
  /** Date range, for the daily interval. */
  start?: string;
  end?: string;
  interval: string;
}) => {
  const range =
    p.start && p.end ? `&start=${p.start}&end=${p.end}` : `&on=${p.on}`;
  return getJson<OiAnalysis>(
    `/api/oi/analysis?underlying=${p.underlying}&expiry=${p.expiry}` +
      `&strike=${p.strike}${range}&interval=${p.interval}`,
  );
};
