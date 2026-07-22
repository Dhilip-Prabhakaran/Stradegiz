import type { Interpretation, OiRow, SideRow } from './api';
import { bucketLabel, inr, signed, signedInt, intervalMinutes } from './format';

const BADGE_CLASS: Record<Interpretation, string> = {
  'Long Build Up': 'b-long-build',
  'Short Build Up': 'b-short-build',
  'Short Covering': 'b-short-cover',
  'Long Unwinding': 'b-long-unwind',
  Neutral: 'b-neutral',
};

const ARROW: Record<Interpretation, string> = {
  'Long Build Up': '↑',
  'Short Build Up': '↓',
  'Short Covering': '↑',
  'Long Unwinding': '↓',
  Neutral: '',
};

function Badge({ value }: { value: Interpretation }) {
  return (
    <span className={`badge ${BADGE_CLASS[value]}`}>
      {value} {ARROW[value]}
    </span>
  );
}

/** Colour a numeric cell by sign; null renders neutral. */
function Num({
  value,
  kind = 'int',
}: {
  value: number | null;
  kind?: 'int' | 'dec';
}) {
  const cls = value === null || value === 0 ? '' : value > 0 ? 'up' : 'down';
  return (
    <td className={`num ${cls}`}>
      {kind === 'int' ? signedInt(value) : signed(value)}
    </td>
  );
}

export function OiTable({
  rows,
  strike,
  interval,
}: {
  rows: OiRow[];
  strike: number;
  interval: string;
}) {
  const mins = intervalMinutes(interval);
  const blank: SideRow = {
    oi: 0,
    oi_change: null,
    ltp: null,
    ltp_change: null,
    volume: 0,
    interpretation: 'Neutral',
  };

  return (
    <div className="table-wrap">
      <table className="oi">
        <thead>
          <tr>
            <th className="side-c" colSpan={5}>
              CALLS
            </th>
            <th className="strike-col">STRIKE</th>
            <th className="side-p" colSpan={5}>
              PUTS
            </th>
          </tr>
          <tr>
            <th>Time</th>
            <th>Call OI</th>
            <th>Chng in OI</th>
            <th>LTP</th>
            <th>Interpretation</th>
            <th className="strike-col">{inr(strike)}</th>
            <th>Interpretation</th>
            <th>LTP</th>
            <th>Chng in OI</th>
            <th>Put OI</th>
            <th>Spot</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const c = r.call ?? blank;
            const p = r.put ?? blank;
            return (
              <tr key={r.time}>
                <td className="time">{bucketLabel(r.time, mins)}</td>
                <td className="num">{inr(c.oi)}</td>
                <Num value={c.oi_change} />
                <td className="num">
                  {c.ltp?.toFixed(2) ?? '—'}
                  <span className={`delta ${c.ltp_change && c.ltp_change > 0 ? 'up' : 'down'}`}>
                    {signed(c.ltp_change)}
                  </span>
                </td>
                <td>
                  <Badge value={c.interpretation} />
                </td>
                <td className="strike-col num">{inr(strike)}</td>
                <td>
                  <Badge value={p.interpretation} />
                </td>
                <td className="num">
                  {p.ltp?.toFixed(2) ?? '—'}
                  <span className={`delta ${p.ltp_change && p.ltp_change > 0 ? 'up' : 'down'}`}>
                    {signed(p.ltp_change)}
                  </span>
                </td>
                <Num value={p.oi_change} />
                <td className="num">{inr(p.oi)}</td>
                <td className="num dim">{r.spot?.toFixed(2) ?? '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {rows.length === 0 && <div className="hint">No data for this selection.</div>}
    </div>
  );
}
