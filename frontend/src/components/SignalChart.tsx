import { useState, type PointerEvent } from 'react';
import type { SeriesRow } from '../api';

const WIDTH = 640;
const HEIGHT = 240;
const PAD = { left: 44, right: 64, top: 12, bottom: 28 };
const TICKS = [-20, -40, -60, -80, -100];
const LABEL_GAP = 13;

/** AP names that have at least one numeric reading, in a fixed order so each AP keeps its color. */
export function apNames(series: SeriesRow[]) {
  const names = new Set(series.flatMap(row => Object.keys(row).filter(key => key !== 'time')));
  return [...names].filter(ap => series.some(row => typeof row[ap] === 'number')).sort();
}

function timeOf(row: SeriesRow | undefined, index: number) {
  return String(row?.time ?? '').slice(11, 19) || `測定 ${index + 1}`;
}

export function SignalChart({ series }: { series: SeriesRow[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const aps = apNames(series);
  const last = Math.max(1, series.length - 1);
  const x = (i: number) => PAD.left + (series.length > 1 ? i / last : 0.5) * (WIDTH - PAD.left - PAD.right);
  const y = (rssi: number) => PAD.top + (Math.min(-20, Math.max(-110, rssi)) + 20) / -90 * (HEIGHT - PAD.top - PAD.bottom);

  // A missing reading breaks the line instead of drawing a false straight segment.
  const paths = aps.map(ap => {
    let d = '';
    let open = false;
    series.forEach((row, i) => {
      const value = row[ap];
      if (typeof value !== 'number') { open = false; return; }
      d += `${open ? 'L' : 'M'}${x(i).toFixed(1)},${y(value).toFixed(1)} `;
      open = true;
    });
    return d;
  });

  // Direct labels at each line's last reading, nudged apart so they never overlap or leave the plot.
  const labels = aps.map(ap => {
    let index = series.length - 1;
    while (index > 0 && typeof series[index][ap] !== 'number') index -= 1;
    return { ap, y: y(series[index][ap] as number) };
  }).sort((a, b) => a.y - b.y);
  labels.forEach((label, i) => { if (i > 0) label.y = Math.max(label.y, labels[i - 1].y + LABEL_GAP); });
  for (let i = labels.length - 1; i >= 0; i -= 1) {
    const limit = i === labels.length - 1 ? HEIGHT - PAD.bottom : labels[i + 1].y - LABEL_GAP;
    labels[i].y = Math.min(labels[i].y, limit);
  }
  // With one or two measurements the start, middle and end ticks would repeat the same time.
  const ticks = [...new Set([0, Math.floor(last / 2), series.length - 1])];

  function onPointerMove(event: PointerEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    if (!box.width || series.length < 2) return;
    const position = (event.clientX - box.left) / box.width * WIDTH;
    const index = Math.round((position - PAD.left) / (WIDTH - PAD.left - PAD.right) * last);
    setHover(Math.max(0, Math.min(series.length - 1, index)));
  }

  const hoverRow = hover === null ? undefined : series[hover];
  return (
    <figure className="chart">
      <div className="chart-plot">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img"
          aria-label={`模擬RSSI時系列、${aps.join('、')}、${series.length}回の測定`}
          onPointerMove={onPointerMove} onPointerLeave={() => setHover(null)}>
          {TICKS.map(tick => (
            <g key={tick}>
              <line className="chart-grid" x1={PAD.left} x2={WIDTH - PAD.right} y1={y(tick)} y2={y(tick)} />
              <text className="chart-axis" x={PAD.left - 8} y={y(tick) + 4} textAnchor="end">{tick}</text>
            </g>
          ))}
          {ticks.map(i => (
            <text key={i} className="chart-axis" x={x(i)} y={HEIGHT - 8}
              textAnchor={series.length < 2 ? 'middle' : i === 0 ? 'start' : i === series.length - 1 ? 'end' : 'middle'}>
              {timeOf(series[i], i)}
            </text>
          ))}
          {paths.map((d, slot) => <path key={aps[slot]} className={`chart-line s${slot + 1}`} d={d} />)}
          {labels.map(label => (
            <text key={label.ap} className="chart-label" x={WIDTH - PAD.right + 8} y={label.y + 4}>{label.ap}</text>
          ))}
          {hoverRow && hover !== null && (
            <g>
              <line className="chart-cursor" x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={HEIGHT - PAD.bottom} />
              {aps.map((ap, slot) => typeof hoverRow[ap] === 'number' && (
                <circle key={ap} className={`chart-dot s${slot + 1}`} cx={x(hover)} cy={y(hoverRow[ap] as number)} r="4" />
              ))}
            </g>
          )}
        </svg>
        {hoverRow && hover !== null && (
          <div className={`chart-tip ${hover > series.length / 2 ? 'is-left' : ''}`} style={{ left: `${x(hover) / WIDTH * 100}%` }}>
            <strong>{timeOf(hoverRow, hover)}</strong>
            {aps.map((ap, slot) => (
              <span key={ap}><i className={`swatch s${slot + 1}`} />{ap}<b>{typeof hoverRow[ap] === 'number' ? `${(hoverRow[ap] as number).toFixed(1)} dBm` : '受信なし'}</b></span>
            ))}
          </div>
        )}
      </div>
      <figcaption className="chart-legend">
        {aps.map((ap, slot) => <span key={ap}><i className={`swatch s${slot + 1}`} />{ap}</span>)}
      </figcaption>
    </figure>
  );
}
