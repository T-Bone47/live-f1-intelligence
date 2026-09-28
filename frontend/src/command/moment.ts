/**
 * ONE SESSION MOMENT. Every Command Center panel reads the same object, built
 * from the timeline and the one cursor, race time t (Phase 12B). The frame is
 * the last lap frame at or before t; race control, pit stops and weather are
 * the items timestamped at or before t; engine events keep the frame the
 * engine first knew them at (`frame_index`), because their own timestamp can
 * precede that. Nothing is computed from values - only selected, ordered and
 * grouped.
 */

import type {
  Battle, DriverIdentity, Frame, PitStop, RaceControlMessage, Stint, Timeline,
  TimelineEvent, TimingRow, WeatherSample,
} from "./types";

export interface VisibleStint extends Stint {
  /** The row's current stint at this frame (open-ended at the cursor). */
  current: boolean;
  /** Last lap to draw: lap_end for a closed stint, the driver's completed laps for the current one. */
  drawEnd: number | null;
}

export interface Moment {
  timeline: Timeline;
  index: number;
  frame: Frame;
  /** The frame's own time (ISO) - what "as of" labels name. */
  frameAt: string | null;
  /** The content time (epoch ms): the latest timestamped item or frame at or before the cursor. */
  knownAt: number;
  isFinal: boolean;
  isStart: boolean;
  /** Leader-lap label for this frame and the recorded maximum. */
  lap: number | null;
  totalLaps: number | null;
  rows: TimingRow[];                       // by position, unpositioned last
  row: Map<number, TimingRow>;
  driver: Map<number, DriverIdentity>;
  battles: Battle[];
  stints: Map<number, VisibleStint[]>;
  pits: PitStop[];
  raceControl: RaceControlMessage[];
  weather: WeatherSample[];
  events: TimelineEvent[];
}

const byPosition = (a: TimingRow, b: TimingRow) =>
  (a.position ?? 999) - (b.position ?? 999) || a.driver_number - b.driver_number;

export function clampIndex(t: Timeline, index: number): number {
  return Math.max(0, Math.min(t.frames.length - 1, Math.trunc(index)));
}

/** Memo-friendly: identity maps are built once per timeline. */
const identityCache = new WeakMap<Timeline, Map<number, DriverIdentity>>();
function identities(t: Timeline): Map<number, DriverIdentity> {
  let m = identityCache.get(t);
  if (!m) {
    m = new Map(t.drivers.map((d) => [d.driver_number, d]));
    identityCache.set(t, m);
  }
  return m;
}

const timesCache = new WeakMap<Timeline, number[]>();
/**
 * Each frame's `at` as epoch ms, for the race-time cursor. A frame without a
 * time is never placed at a guessed moment: it takes the next timed frame's
 * time, so the cursor always shows that later frame instead (the untimed one
 * is skipped); after the last timed frame it takes the previous one's, so the
 * newest frame of a live timeline stays reachable at the end.
 */
export function frameTimes(t: Timeline): number[] {
  let ms = timesCache.get(t);
  if (!ms) {
    const out = t.frames.map((f) => (f.at == null ? Number.NaN : Date.parse(f.at)));
    for (let i = out.length - 2; i >= 0; i -= 1) if (Number.isNaN(out[i])) out[i] = out[i + 1];
    for (let i = 1; i < out.length; i += 1) if (Number.isNaN(out[i])) out[i] = out[i - 1];
    ms = out.map((x) => (Number.isNaN(x) ? 0 : x));
    timesCache.set(t, ms);
  }
  return ms;
}

/** Index of the last value <= x in an ascending list, -1 when none. */
function lastAtOrBefore(xs: number[], x: number): number {
  let lo = 0, hi = xs.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] <= x) lo = mid + 1; else hi = mid;
  }
  return lo - 1;
}

/** The frame a panel shows at race time t: the last frame at or before t (START before all). */
export function frameIndexAt(frames: number[], t: number): number {
  return Math.max(0, lastAtOrBefore(frames, t));
}

const stampsCache = new WeakMap<Timeline, number[]>();
function stamps(t: Timeline): number[] {
  let ms = stampsCache.get(t);
  if (!ms) {
    ms = [...t.race_control, ...t.pit_stops, ...t.weather]
      .filter((x) => x.ts != null).map((x) => Date.parse(x.ts!)).sort((a, b) => a - b);
    stampsCache.set(t, ms);
  }
  return ms;
}

/**
 * The content time of the cursor: the frame's own time or the latest
 * timestamped item at or before t, whichever is later. It changes only when
 * what the moment lists changes, so the moment can be reused between ticks.
 */
export function knownTime(t: Timeline, index: number, at: number): number {
  const frameMs = frameTimes(t)[clampIndex(t, index)];
  const xs = stamps(t);
  const k = lastAtOrBefore(xs, at);
  return k >= 0 ? Math.max(frameMs, xs[k]) : frameMs;
}

export function buildMoment(t: Timeline, rawIndex: number, at?: number): Moment {
  const index = clampIndex(t, rawIndex);
  const frame = t.frames[index];
  const cut = at ?? frameTimes(t)[index];
  const rows = [...frame.rows].sort(byPosition);
  const row = new Map(rows.map((r) => [r.driver_number, r]));

  const stints = new Map<number, VisibleStint[]>();
  for (const s of t.stints) {
    const r = row.get(s.driver_number);
    if (!r || r.stint_number == null || s.stint_number > r.stint_number) continue;
    const current = s.stint_number === r.stint_number;
    const list = stints.get(s.driver_number) ?? [];
    list.push({ ...s, current, drawEnd: current ? r.lap_number : s.lap_end });
    stints.set(s.driver_number, list);
  }
  for (const list of stints.values()) list.sort((a, b) => a.stint_number - b.stint_number);

  const known = <T extends { frame_index: number }>(xs: T[]) => xs.filter((x) => x.frame_index <= index);
  const knownAt = <T extends { frame_index: number; ts: string | null }>(xs: T[]) =>
    xs.filter((x) => (x.ts != null ? Date.parse(x.ts) <= cut : x.frame_index <= index));

  return {
    timeline: t,
    index,
    frame,
    frameAt: frame.at,
    knownAt: cut,
    isFinal: frame.kind === "FINAL",
    isStart: frame.kind === "START",
    lap: frame.kind === "START" ? 0 : frame.lap,
    totalLaps: t.laps_completed_max,
    rows,
    row,
    driver: identities(t),
    battles: frame.active_battles,
    stints,
    pits: knownAt(t.pit_stops),
    raceControl: knownAt(t.race_control),
    weather: knownAt(t.weather),
    events: known(t.events),
  };
}

/** Frame index for a URL lap token: "start", "final" or a lap number. */
export function indexForLapToken(t: Timeline, token: string | null): number | null {
  if (!token) return null;
  if (token === "start") return t.frames.findIndex((f) => f.kind === "START");
  if (token === "final") return t.frames.length - 1;
  const n = Number(token);
  if (!Number.isInteger(n)) return null;
  const i = t.frames.findIndex((f) => f.kind === "LAP" && f.lap === n);
  return i >= 0 ? i : null;
}

export function lapTokenForIndex(t: Timeline, index: number): string {
  const f = t.frames[clampIndex(t, index)];
  if (f.kind === "START") return "start";
  if (f.kind === "FINAL") return "final";
  return String(f.lap);
}

/** Position of every driver at every frame up to `upTo` (inclusive). null = not reported. */
export function positionHistory(t: Timeline, upTo: number): Map<number, (number | null)[]> {
  const out = new Map<number, (number | null)[]>();
  for (const d of t.drivers) out.set(d.driver_number, []);
  for (let i = 0; i <= upTo; i += 1) {
    const f = t.frames[i];
    const seen = new Map(f.rows.map((r) => [r.driver_number, r.position]));
    for (const [num, series] of out) series.push(seen.get(num) ?? null);
  }
  return out;
}

/**
 * Measured interval between a pair at each frame up to `upTo`: the behind
 * car's own `interval_s` when the backend places it directly behind the
 * other car; null when they are not neighbours (nothing is computed).
 */
export function pairIntervalHistory(t: Timeline, ahead: number, behind: number, upTo: number):
  { index: number; lap: number | null; interval: number | null; adjacent: boolean }[] {
  const out = [];
  for (let i = 0; i <= upTo; i += 1) {
    const f = t.frames[i];
    const a = f.rows.find((r) => r.driver_number === ahead);
    const b = f.rows.find((r) => r.driver_number === behind);
    const adjacent = !!a && !!b && a.position != null && b.position === a.position + 1;
    out.push({
      index: i, lap: f.kind === "START" ? 0 : f.lap,
      interval: adjacent ? b!.interval_s : null, adjacent,
    });
  }
  return out;
}

export const battleKey = (b: Pick<Battle, "ahead" | "behind">) => `${b.ahead}-${b.behind}`;
