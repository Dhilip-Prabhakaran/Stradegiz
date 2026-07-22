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

export const fetchExpiries = (underlying: string) =>
  getJson<string[]>(`/api/oi/expiries?underlying=${underlying}`);

export const fetchStrikes = (underlying: string, expiry: string) =>
  getJson<number[]>(`/api/oi/strikes?underlying=${underlying}&expiry=${expiry}`);

export const fetchOiAnalysis = (p: {
  underlying: string;
  expiry: string;
  strike: number;
  on: string;
  interval: string;
}) =>
  getJson<OiAnalysis>(
    `/api/oi/analysis?underlying=${p.underlying}&expiry=${p.expiry}` +
      `&strike=${p.strike}&on=${p.on}&interval=${p.interval}`,
  );
