/**
 * Weather (Phase 11): the engine's latest weather at the cursor frame, plus a
 * compact trace of the recorded samples up to the cursor. A missing reading
 * shows "—", never 0. No weather effect on pace is claimed.
 */

import { useMemo } from "react";
import { fmtClockUtc, fmtPct, fmtTemp, fmtWindKmh } from "../../command/format";
import type { Moment } from "../../command/moment";
import { EmptyState, Icon, Panel, type IconName } from "./ui";
import { useWidth } from "./useWidth";

function Cell({ icon, label, value, sub }: { icon: IconName; label: string; value: string; sub?: string }) {
  return (
    <div className="cc-wx-cell">
      <dt className="cc-label"><Icon name={icon} size={12} /> {label}</dt>
      <dd className="cc-wx-value">{value}</dd>
      {sub && <dd className="cc-readout-sub">{sub}</dd>}
    </div>
  );
}

export function WeatherPanel({ moment }: { moment: Moment }) {
  const [wrap, width] = useWidth<HTMLDivElement>(300);
  const w = moment.frame.weather;
  const samples = moment.weather;
  const last = samples[samples.length - 1];
  const series = useMemo(() => samples.filter((s) => s.track_temp_c != null || s.air_temp_c != null), [samples]);
  const has = Object.keys(w).length > 0;
  const H = 54;
  const vals = series.flatMap((s) => [s.track_temp_c, s.air_temp_c]).filter((v): v is number => v != null);
  const lo = Math.min(...vals, Infinity);
  const hi = Math.max(...vals, -Infinity);
  const span = hi - lo || 1;
  const x = (i: number) => (series.length < 2 ? 0 : (i / (series.length - 1)) * (width - 4)) + 2;
  const y = (v: number) => 4 + (1 - (v - lo) / span) * (H - 8);
  const line = (key: "track_temp_c" | "air_temp_c") => series
    .map((s, i) => (s[key] == null ? null : `${x(i).toFixed(1)},${y(s[key] as number).toFixed(1)}`))
    .filter(Boolean).join(" ");
  const rain = w.rainfall == null ? "—" : w.rainfall ? "Yes" : "No";

  return (
    <Panel id="cc-weather" title="Weather" className="cc-weather"
      meta={<span>{last ? `last sample ${fmtClockUtc(last.ts)}` : "no samples yet"}</span>}>
      {!has ? (
        <EmptyState title="Weather unavailable" why="No weather sample has been recorded up to this lap." />
      ) : (
        <>
          <dl className="cc-wx-grid">
            <Cell icon="thermometer" label="Track" value={fmtTemp(w.track_temp_c)} />
            <Cell icon="thermometer" label="Air" value={fmtTemp(w.air_temp_c)} />
            <Cell icon="droplet" label="Humidity" value={fmtPct(w.humidity_pct)} />
            <Cell icon="wind" label="Wind" value={fmtWindKmh(w.wind_speed_mps)}
                  sub={w.wind_direction_deg != null ? `from ${w.wind_direction_deg}°` : undefined} />
            <Cell icon="rain" label="Rain" value={rain} sub="rainfall flag" />
          </dl>
          {series.length > 1 && (
            <div ref={wrap} className="cc-wx-trace">
              <svg width={width} height={H} role="img" aria-label={`Track and air temperature over ${series.length} samples, ${lo.toFixed(1)} to ${hi.toFixed(1)} °C`}>
                <polyline points={line("track_temp_c")} fill="none" className="cc-wx-track" />
                <polyline points={line("air_temp_c")} fill="none" className="cc-wx-air" />
              </svg>
              <p className="cc-small cc-muted">
                <span className="cc-key cc-key-track" aria-hidden="true" /> track
                <span className="cc-key cc-key-air" aria-hidden="true" /> air · {lo.toFixed(1)}–{hi.toFixed(1)} °C · {series.length} samples
              </p>
            </div>
          )}
        </>
      )}
    </Panel>
  );
}
