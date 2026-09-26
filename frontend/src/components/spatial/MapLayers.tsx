/**
 * The static track layers (Phase 12B): the validated reference loop, the
 * three sector paths and the FINISH/S1/S2 timing lines - all from
 * track_reference_v1. Memoized per fit: they redraw on resize, never on a tick.
 */

import { memo } from "react";
import type { LineName, TrackReference } from "../../spatial/types";
import { headingDeg, LINE_TAG_DX, LINE_TAG_DY, lineTagBox, nudgeClear, outwardOffset, pathData, type Fit } from "./geometry";

const px = (fit: Fit, pts: number[][]) => pts.map(([x, y]) => fit.toPx(x, y));

export const CircuitLayer = memo(function CircuitLayer({ track, fit, hotSector, onSector }: {
  track: TrackReference; fit: Fit; hotSector: number | null; onSector: (s: number | null) => void;
}) {
  // sector names stay readable: never under a timing-line tag
  const tags = track.timing_lines.filter((l) => l.x != null && l.y != null)
    .map((l) => lineTagBox(fit.toPx(l.x!, l.y!), l.line));
  return (
    <g className="sm-layer-circuit">
      <path className="sm-circuit" d={pathData(px(fit, track.reference!.polyline!), true)} />
      {track.sectors.map((s) => (
        <path key={s.sector} className={`sm-sector${hotSector === s.sector ? " is-hot" : ""}`}
              data-sector={s.sector} d={pathData(px(fit, s.polyline))}
              onMouseEnter={() => onSector(s.sector)} onMouseLeave={() => onSector(null)} />
      ))}
      {track.sectors.map((s) => {
        const at = fit.toPx(s.label_point[0], s.label_point[1]);
        const path = px(fit, s.polyline);
        const k = Math.floor(path.length / 2);
        const [ox, oy] = outwardOffset(path[Math.max(0, k - 1)], path[Math.min(path.length - 1, k + 1)], 14);
        const [x, y] = nudgeClear([at[0] + ox, at[1] + oy], 16, tags);
        return (
          <text key={s.sector} className={`sm-sector-label${hotSector === s.sector ? " is-hot" : ""}`}
                x={x.toFixed(1)} y={y.toFixed(1)} dy="0.35em" textAnchor="middle">{`S${s.sector}`}</text>
        );
      })}
    </g>
  );
});

export const LineLayer = memo(function LineLayer({ track, fit, active, onLine }: {
  track: TrackReference; fit: Fit; active: LineName | null; onLine: (l: LineName | null) => void;
}) {
  return (
    <g className="sm-layer-lines">
      {track.timing_lines.map((l) => {
        if (l.x == null || l.y == null) return null;
        const at = fit.toPx(l.x, l.y);
        // the tick lies across the path: orient it by the sector path leaving this line
        const out = track.sectors.find((s) => s.from_line === l.line)?.polyline[1];
        const angle = out ? headingDeg(at, fit.toPx(out[0], out[1])) + 90 : 0;
        const on = active === l.line;
        const toggle = () => onLine(on ? null : l.line);
        const place = `translate(${at[0].toFixed(1)} ${at[1].toFixed(1)}) rotate(${angle.toFixed(1)})`;
        const box = lineTagBox(at, l.line);
        return (
          <g key={l.line} className={`sm-line${on ? " is-active" : ""}`} data-line={l.line} role="button" tabIndex={0}
             aria-pressed={on} aria-label={`${l.line} timing line, measured placement`}
             onClick={toggle} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } }}>
            <line className="sm-line-hit" x1={-12} x2={12} y1={0} y2={0} transform={place} />
            <line className="sm-line-tick" x1={-9} x2={9} y1={0} y2={0} transform={place} />
            <rect className="sm-line-tag-box" x={box.x0.toFixed(1)} y={box.y0.toFixed(1)} rx={2}
                  width={(box.x1 - box.x0).toFixed(1)} height={(box.y1 - box.y0).toFixed(1)} />
            <text className="sm-line-tag" x={(at[0] + LINE_TAG_DX).toFixed(1)} y={(at[1] + LINE_TAG_DY).toFixed(1)}>{l.line}</text>
          </g>
        );
      })}
    </g>
  );
});
