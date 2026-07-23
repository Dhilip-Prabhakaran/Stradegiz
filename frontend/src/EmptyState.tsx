import type { Coverage } from './api';
import { dayLabel } from './format';

/**
 * Explains an empty or single-row intraday view.
 *
 * Intraday OI cannot be backfilled from any source — it exists only for days
 * the recorder was running — so a blank table is the expected state for older
 * dates, not a fault. Saying so plainly beats showing an empty grid.
 */
export function EmptyState({
  coverage,
  date,
  onUseDaily,
}: {
  coverage: Coverage | null;
  date: string;
  onUseDaily: () => void;
}) {
  const from = coverage?.intraday_from ?? null;
  const iso = (d: string) => dayLabel(`${d}T12:00:00+05:30`);

  let title: string;
  let detail: string;

  if (!from) {
    title = 'No intraday data recorded yet';
    detail =
      'The recorder captures every 5 minutes during market hours (09:15–15:30 IST). ' +
      'Intraday rows will appear here after the next session it runs through.';
  } else if (date < from) {
    title = `No intraday data for ${iso(date)}`;
    detail =
      `Intraday recording began ${iso(from)}. Earlier dates hold only the ` +
      'end-of-day figure, because 5-minute open interest cannot be sourced ' +
      'retrospectively — it has to be recorded live.';
  } else {
    title = `No intraday data for ${iso(date)}`;
    detail =
      'This may be a trading holiday, or the recorder was not running that day. ' +
      'Capture gaps are listed on the health endpoint.';
  }

  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      <p className="empty-detail">{detail}</p>
      <button className="empty-action" onClick={onUseDaily}>
        Show daily history instead
      </button>
      {coverage?.history_from && (
        <p className="empty-meta">
          Daily history available {iso(coverage.history_from)}
          {coverage.history_to ? ` – ${iso(coverage.history_to)}` : ''}
        </p>
      )}
    </div>
  );
}
