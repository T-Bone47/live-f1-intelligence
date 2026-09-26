/**
 * Command Center UI state (Phase 11). Server state (the timeline) is separate
 * and immutable; this reducer only holds the cursor, playback and selection.
 *
 * Replay clock: a cursor over the backend's lap frames. Playing advances one
 * frame per tick at `speed` frames (leader laps) per second - labelled as
 * laps per second, never as race time.
 */

import { useEffect, useReducer } from "react";

export const SPEEDS = [1, 2, 5, 10] as const;
export type Density = "standard" | "compact";

export interface UiState {
  index: number;            // cursor frame
  last: number;             // last frame index (frames.length - 1)
  playing: boolean;
  speed: number;            // frames per second
  driver: number | null;    // selected driver
  battle: string | null;    // selected battle "ahead-behind"
  rcKey: string | null;     // selected race-control message
  density: Density;
}

export type UiAction =
  | { type: "load"; last: number; index: number }
  | { type: "seek"; index: number }
  | { type: "step"; by: number }
  | { type: "play" } | { type: "pause" } | { type: "toggle" } | { type: "tick" }
  | { type: "speed"; speed: number }
  | { type: "driver"; driver: number | null }
  | { type: "battle"; key: string | null }
  | { type: "event"; key: string | null; index?: number }
  | { type: "density"; density: Density }
  | { type: "clear" };

const clamp = (s: UiState, i: number) => Math.max(0, Math.min(s.last, Math.trunc(i)));

export function initialUi(partial: Partial<UiState> = {}): UiState {
  return { index: 0, last: 0, playing: false, speed: 2, driver: null, battle: null,
           rcKey: null, density: "standard", ...partial };
}

export function uiReducer(s: UiState, a: UiAction): UiState {
  switch (a.type) {
    case "load": return { ...s, last: a.last, index: Math.max(0, Math.min(a.last, a.index)), playing: false };
    case "seek": return { ...s, index: clamp(s, a.index), playing: false };
    case "step": return { ...s, index: clamp(s, s.index + a.by), playing: false };
    case "play": return s.index >= s.last ? { ...s, index: 0, playing: true } : { ...s, playing: true };
    case "pause": return { ...s, playing: false };
    case "toggle": return uiReducer(s, { type: s.playing ? "pause" : "play" });
    case "tick": {
      if (!s.playing) return s;
      const next = clamp(s, s.index + 1);
      return { ...s, index: next, playing: next < s.last };
    }
    case "speed": return { ...s, speed: a.speed };
    case "driver": return { ...s, driver: a.driver };
    case "battle": return { ...s, battle: a.key };
    case "event": return a.index == null
      ? { ...s, rcKey: a.key }
      : { ...s, rcKey: a.key, index: clamp(s, a.index), playing: false };
    case "density": return { ...s, density: a.density };
    case "clear": return { ...s, driver: null, battle: null, rcKey: null };
    default: return s;
  }
}

/** Advances the cursor while playing; one timer, cleared on pause/unmount. */
export function usePlayback(playing: boolean, speed: number, dispatch: (a: UiAction) => void): void {
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => dispatch({ type: "tick" }), Math.round(1000 / speed));
    return () => window.clearInterval(id);
  }, [playing, speed, dispatch]);
}

export function useUi(init: Partial<UiState>) {
  return useReducer(uiReducer, init, initialUi);
}

// ------------------------------------------------------------------ URL --

export interface CommandUrl { session: string | null; lap: string | null; driver: number | null }

export function readUrl(search: string): CommandUrl {
  const q = new URLSearchParams(search);
  const d = Number(q.get("driver"));
  return {
    session: q.get("session"),
    lap: q.get("lap"),
    driver: q.get("driver") && Number.isInteger(d) && d > 0 ? d : null,
  };
}

export function writeUrl(u: CommandUrl): string {
  const q = new URLSearchParams();
  if (u.session) q.set("session", u.session);
  if (u.lap) q.set("lap", u.lap);
  if (u.driver != null) q.set("driver", String(u.driver));
  const s = q.toString();
  return s ? `?${s}` : "";
}
