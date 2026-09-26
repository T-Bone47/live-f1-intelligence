/**
 * Replay command bar (Phase 11). The replay clock is a cursor over the
 * backend's lap frames (START, each leader lap end, FINAL). The scrubber track
 * is segmented by the backend's session phase per frame; the thumb is a real
 * <input type="range"> so keyboard and screen readers work natively.
 * Speed is frames (leader laps) per second - not race time.
 */

import { memo, useMemo } from "react";
import { fmtClockUtc, phaseLabel, phaseTone } from "../../command/format";
import type { Moment } from "../../command/moment";
import { SPEEDS } from "../../command/state";
import type { Timeline } from "../../command/types";
import { Icon } from "./ui";

const PhaseTrack = memo(function PhaseTrack({ t }: { t: Timeline }) {
  const n = t.frames.length;
  const segments = useMemo(() => {
    const out: { from: number; to: number; tone: string; phase: string }[] = [];
    t.frames.forEach((f, i) => {
      const tone = phaseTone(f.phase);
      const last = out[out.length - 1];
      if (last && last.tone === tone) last.to = i;
      else out.push({ from: i, to: i, tone, phase: f.phase });
    });
    return out;
  }, [t]);
  const pct = (i: number) => (n <= 1 ? 0 : (i / (n - 1)) * 100);
  return (
    <div className="cc-scrub-track" aria-hidden="true">
      {segments.map((s) => (
        <span key={s.from} className={`cc-scrub-seg cc-scrub-${s.tone}`} title={phaseLabel(s.phase)}
              style={{ left: `${pct(s.from)}%`, width: `${Math.max(pct(s.to) - pct(s.from), 0.6)}%` }} />
      ))}
    </div>
  );
});

function frameLabel(m: Moment): string {
  if (m.isStart) return "START";
  if (m.isFinal) return "FINAL";
  return `LAP ${m.lap}`;
}

export function ReplayBar({ moment, playing, speed, live, onSeek, onStep, onToggle, onSpeed }: {
  moment: Moment; playing: boolean; speed: number; live: boolean;
  onSeek: (i: number) => void; onStep: (by: number) => void; onToggle: () => void; onSpeed: (s: number) => void;
}) {
  const t = moment.timeline;
  const last = t.frames.length - 1;
  const total = moment.totalLaps;
  const valueText = `${frameLabel(moment)}${total ? ` of ${total}` : ""}, ${phaseLabel(moment.frame.phase)}`;
  return (
    <div className="cc-replay" role="region" aria-label="Replay controls">
      <div className="cc-replay-controls">
        <button type="button" className="cc-tbtn" onClick={() => onSeek(0)} disabled={moment.index === 0} aria-label="Go to start"><Icon name="skipBack" /></button>
        <button type="button" className="cc-tbtn" onClick={() => onStep(-1)} disabled={moment.index === 0} aria-label="Previous lap"><Icon name="chevronLeft" /></button>
        <button type="button" className="cc-tbtn cc-tbtn-play" onClick={onToggle} aria-label={playing ? "Pause replay" : "Play replay"} aria-pressed={playing}>
          <Icon name={playing ? "pause" : "play"} size={15} />
        </button>
        <button type="button" className="cc-tbtn" onClick={() => onStep(1)} disabled={moment.index === last} aria-label="Next lap"><Icon name="chevronRight" /></button>
        <button type="button" className="cc-tbtn" onClick={() => onSeek(last)} disabled={moment.index === last} aria-label={live ? "Return to live" : "Go to the end"}>
          <Icon name="skipForward" />
        </button>
      </div>
      <div className="cc-replay-readout" aria-live="polite">
        <span className="cc-replay-lap">{frameLabel(moment)}{total && !moment.isFinal ? <span className="cc-replay-total"> / {total}</span> : null}</span>
        <span className="cc-replay-time">{fmtClockUtc(moment.frame.at)}</span>
      </div>
      <div className="cc-scrub">
        <PhaseTrack t={t} />
        <div className="cc-scrub-fill" style={{ width: `${last ? (moment.index / last) * 100 : 0}%` }} aria-hidden="true" />
        <input type="range" className="cc-scrub-input" min={0} max={last} step={1} value={moment.index}
               aria-label="Session moment" aria-valuetext={valueText}
               onChange={(e) => onSeek(Number(e.target.value))} />
      </div>
      <div className="cc-replay-speed" role="group" aria-label="Replay speed, laps per second">
        {SPEEDS.map((s) => (
          <button key={s} type="button" className="cc-seg-btn" aria-pressed={speed === s} onClick={() => onSpeed(s)}>{s}</button>
        ))}
        <span className="cc-small cc-muted">laps/s</span>
      </div>
    </div>
  );
}
