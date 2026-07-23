/** Indian digit grouping (1,08,30,170) — the convention F&O traders read in. */
export const inr = (n: number | null | undefined): string =>
  n === null || n === undefined ? '—' : n.toLocaleString('en-IN');

export const signed = (n: number | null | undefined, digits = 2): string => {
  if (n === null || n === undefined) return '—';
  const s = n.toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return n > 0 ? `+${s}` : s;
};

export const signedInt = (n: number | null | undefined): string => {
  if (n === null || n === undefined) return '—';
  const s = Math.abs(n).toLocaleString('en-IN');
  return n > 0 ? `+${s}` : n < 0 ? `-${s}` : s;
};

/** NSE trades in IST. Times are pinned to it rather than the viewer's clock,
 *  so a user outside India still reads real session times. */
const IST = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Kolkata',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

const IST_DATE = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Kolkata',
  day: '2-digit',
  month: 'short',
  year: 'numeric',
});

export const hhmm = (iso: string): string => IST.format(new Date(iso));

/** Daily rows are one trading day, so they read as a date, not a time span. */
export const dayLabel = (iso: string): string => IST_DATE.format(new Date(iso));

/** Bucket start -> the "14:20-14:25" range label the intraday screens use. */
export const bucketLabel = (iso: string, minutes: number): string => {
  const start = new Date(iso);
  const end = new Date(start.getTime() + minutes * 60_000);
  return `${IST.format(start)}-${IST.format(end)}`;
};

export const isDailyInterval = (interval: string): boolean => interval === '1day';

export const intervalMinutes = (interval: string): number =>
  isDailyInterval(interval) ? 1440 : parseInt(interval.replace('min', ''), 10) || 5;
