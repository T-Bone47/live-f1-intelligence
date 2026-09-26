/**
 * Command Center UI state. Server state (the timeline) is separate and
 * immutable; this reducer only holds the cursor, playback and selection.
 *
 * The ONE cursor is race time `t` (epoch ms, UTC; Phase 12B). The lap frame a
 * panel shows is derived from it (the last frame at or before t). Playing
 * advances t at `rate` x race time from one requestAnimationFrame loop; each
 * tick is capped so a hidden tab never jumps the race.
 */

import { useEffect, useReducer } from "react";
import { frameIndexAt } from "./moment";

export const RATES = [1, 4, 16, 64] as const;
export const TICK_CAP_MS = 250;
export const NUDGE_MS = 10_000;
export type Density = "standard" | "compact";

export interface UiState {
  t: number;                // cursor, race time (epoch ms)
  frames: number[];         // each frame's `at` (epoch ms), in order: the bounds and the lap frames
  playing: boolean;
  rate: number;             // x race time
  driver: number | null;    // selected driver
  battle: string | null;    // selected battle "ahead-behind"
  rcKey: string | null;     // selected race-control message
  density: Density;
}

export type UiAction =
  | { type: "load"; frames: number[]; t: number }
  | { type: "seekTime"; t: number }
  | { type: "seekFrame"; index: number }
  | { type: "step"; by: number }
  | { type: "nudge"; ms: number }
  | { type: "play" } | { type: "pause" } | { type: "toggle" }
  | { type: "tick"; wallMs: number }
  | { type: "rate"; rate: number }
  | { type: "driver"; driver: number | null }
  | { type: "battle"; key: string | null }
  | { type: "event"; key: string | null; t?: number }
  | { type: "density"; density: Density }
  | { type: "clear" };

const tMin = (s: UiState) => s.frames[0] ?? 0;
const tMax = (s: UiState) => s.frames[s.frames.length - 1] ?? 0;
const clampT = (s: UiState, t: number) => Math.max(tMin(s), Math.min(tMax(s), t));
const frameT = (s: UiState, i: number) =>
  s.frames[Math.max(0, Math.min(s.frames.length - 1, Math.trunc(i)))] ?? 0;

export function initialUi(partial: Partial<UiState> = {}): UiState {
  return { t: 0, frames: [], playing: false, rate: 16, driver: null, battle: null,
           rcKey: null, density: "standard", ...partial };
}

export function uiReducer(s: UiState, a: UiAction): UiState {
  switch (a.type) {
    case "load": {
      const next = { ...s, frames: a.frames, playing: false };
      return { ...next, t: clampT(next, a.t) };
    }
    case "seekTime": return { ...s, t: clampT(s, a.t), playing: false };
    case "seekFrame": return { ...s, t: frameT(s, a.index), playing: false };
    case "step": {
      const i = frameIndexAt(s.frames, s.t);
      const target = a.by < 0 && s.t > s.frames[i] ? i + a.by + 1 : i + a.by;
      return { ...s, t: frameT(s, target), playing: false };
    }
    case "nudge": return { ...s, t: clampT(s, s.t + a.ms), playing: false };
    case "play": return s.t >= tMax(s) ? { ...s, t: tMin(s), playing: true } : { ...s, playing: true };
    case "pause": return { ...s, playing: false };
    case "toggle": return uiReducer(s, { type: s.playing ? "pause" : "play" });
    case "tick": {
      if (!s.playing) return s;
      const t = clampT(s, s.t + Math.min(Math.max(a.wallMs, 0), TICK_CAP_MS) * s.rate);
      return { ...s, t, playing: t < tMax(s) };
    }
    case "rate": return { ...s, rate: a.rate };
    case "driver": return { ...s, driver: a.driver };
    case "battle": return { ...s, battle: a.key };
    case "event": return a.t == null
      ? { ...s, rcKey: a.key }
      : { ...s, rcKey: a.key, t: clampT(s, a.t), playing: false };
    case "density": return { ...s, density: a.density };
    case "clear": return { ...s, driver: null, battle: null, rcKey: null };
    default: return s;
  }
}

/** The one replay clock: a requestAnimationFrame loop dispatching the wall
 * time elapsed since the previous frame. Cancelled on pause and unmount. */
export function usePlayback(playing: boolean, dispatch: (a: UiAction) => void): void {
  useEffect(() => {
    if (!playing) return;
    let id = 0;
    let last = performance.now();
    const loop = (now: number) => {
      dispatch({ type: "tick", wallMs: now - last });
      last = now;
      id = requestAnimationFrame(loop);
    };
    id = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(id);
  }, [playing, dispatch]);
}

export function useUi(init: Partial<UiState>) {
  return useReducer(uiReducer, init, initialUi);
}

// ------------------------------------------------------------------ URL --

export interface CommandUrl { session: string | null; lap: string | null; t: string | null; driver: number | null }

export function readUrl(search: string): CommandUrl {
  const q = new URLSearchParams(search);
  const d = Number(q.get("driver"));
  return {
    session: q.get("session"),
    lap: q.get("lap"),
    t: q.get("t"),
    driver: q.get("driver") && Number.isInteger(d) && d > 0 ? d : null,
  };
}

export function writeUrl(u: CommandUrl): string {
  const q = new URLSearchParams();
  if (u.session) q.set("session", u.session);
  if (u.lap) q.set("lap", u.lap);
  if (u.t) q.set("t", u.t);
  if (u.driver != null) q.set("driver", String(u.driver));
  const s = q.toString();
  return s ? `?${s}` : "";
}

const HAS_OFFSET = /(Z|[+-]\d\d:\d\d)$/;

/** A URL time: ISO-8601 with an explicit UTC offset, inside the recording's
 * frames. Anything else is ignored (null), never guessed. */
export function parseUrlTime(value: string | null, frames: number[]): number | null {
  if (!value || !HAS_OFFSET.test(value) || frames.length === 0) return null;
  const ms = Date.parse(value);
  if (!Number.isFinite(ms) || ms < frames[0] || ms > frames[frames.length - 1]) return null;
  return ms;
}
