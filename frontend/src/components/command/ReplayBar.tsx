/**
 * Replay command bar. The replay clock is the ONE cursor, race time t
 * (Phase 12B): the scrubber runs over seconds of the recording, segmented by
 * the backend's session phase of each frame interval; the thumb is a real
 * <input type="range"> so keyboard and screen readers work natively. Rates are
 * multiples of race time. Previous/next step between the backend's lap frames.
 */

import { memo, useMemo } from "react";
import { fmtClockTenths, phaseLabel, phaseTone } from "../../command/format";
import { frameTimes, type Moment } from "../../command/moment";
import { RATES } from "../../command/state";
import type { Timeline } from "../../command/types";
import { Icon } from "./ui";

const PhaseTrack = memo(function PhaseTrack({ t }: { t: Timeline }) {
  const segments = useMemo(() => {
    const times = frameTimes(t);
    const t0 = times[0], span = times[times.length - 1] - t0;
    const pct = (ms: number) => (span <= 0 ? 0 : ((ms - t0) / span) * 100);
    const out: { from: number; to: number; tone: string; phase: string }[] = [];
    t.frames.forEach((f, i) => {
      // frame i is what the cursor shows from its own time to the next frame's
      const from = pct(times[i]), to = pct(times[Math.min(i + 1, times.length - 1)]);
      const tone = phaseTone(f.phase);
      const last = out[out.length - 1];
      if (last && last.tone === tone) last.to = to;
      else out.push({ from, to, tone, phase: f.phase });
    });
    return out;
  }, [t]);
  return (
    <div className="cc-scrub-track" aria-hidden="true">
      {segments.map((s) => (
        <span key={s.from} className={`cc-scrub-seg cc-scrub-${s.tone}`} title={phaseLabel(s.phase)}
              style={{ left: `${s.from}%`, width: `${Math.max(s.to - s.from, 0.6)}%` }} />
      ))}
    </div>
  );
});

function frameLabel(m: Moment): string {
  if (m.isStart) return "START";
  if (m.isFinal) return "FINAL";
  return `LAP ${m.lap}`;
}

export function ReplayBar({ moment, t, playing, rate, live, onSeekTime, onSeekFrame, onStep, onToggle, onRate }: {
  moment: Moment; t: number; playing: boolean; rate: number; live: boolean;
  onSeekTime: (ms: number) => void; onSeekFrame: (i: number) => void; onStep: (by: number) => void;
  onToggle: () => void; onRate: (r: number) => void;
}) {
  const times = frameTimes(moment.timeline);
  const last = times.length - 1;
  const t0 = times[0], span = times[last] - t0;
  const atStart = t <= t0, atEnd = t >= times[last];
  const total = moment.totalLaps;
  const clock = fmtClockTenths(t);
  const valueText = `${frameLabel(moment)}${total ? ` of ${total}` : ""}, ${phaseLabel(moment.frame.phase)}, ${clock}`;
  return (
    <div className="cc-replay" role="region" aria-label="Replay controls">
      <div className="cc-replay-controls">
        <button type="button" className="cc-tbtn" onClick={() => onSeekFrame(0)} disabled={atStart} aria-label="Go to start"><Icon name="skipBack" /></button>
        <button type="button" className="cc-tbtn" onClick={() => onStep(-1)} disabled={atStart} aria-label="Previous lap"><Icon name="chevronLeft" /></button>
        <button type="button" className="cc-tbtn cc-tbtn-play" onClick={onToggle} aria-label={playing ? "Pause replay" : "Play replay"} aria-pressed={playing}>
          <Icon name={playing ? "pause" : "play"} size={15} />
        </button>
        <button type="button" className="cc-tbtn" onClick={() => onStep(1)} disabled={atEnd} aria-label="Next lap"><Icon name="chevronRight" /></button>
        <button type="button" className="cc-tbtn" onClick={() => onSeekFrame(last)} disabled={atEnd} aria-label={live ? "Return to live" : "Go to the end"}>
          <Icon name="skipForward" />
        </button>
      </div>
      <div className="cc-replay-readout" aria-live="polite">
        <span className="cc-replay-lap">{frameLabel(moment)}{total && !moment.isFinal ? <span className="cc-replay-total"> / {total}</span> : null}</span>
        <span className="cc-replay-time">{clock}</span>
      </div>
      <div className="cc-scrub">
        <PhaseTrack t={moment.timeline} />
        <div className="cc-scrub-fill" style={{ width: `${span > 0 ? ((t - t0) / span) * 100 : 0}%` }} aria-hidden="true" />
        <input type="range" className="cc-scrub-input" min={0} max={span / 1000} step={0.1} value={(t - t0) / 1000}
               aria-label="Session moment, seconds of race time" aria-valuetext={valueText}
               onChange={(e) => onSeekTime(t0 + Number(e.target.value) * 1000)} />
      </div>
      <div className="cc-replay-speed" role="group" aria-label="Replay rate, multiples of race time">
        {RATES.map((r) => (
          <button key={r} type="button" className="cc-seg-btn" aria-pressed={rate === r} onClick={() => onRate(r)}>{r}×</button>
        ))}
        <span className="cc-small cc-muted">race time</span>
      </div>
    </div>
  );
}
