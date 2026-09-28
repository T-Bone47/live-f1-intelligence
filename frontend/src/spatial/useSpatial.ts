/**
 * Spatial server state for the ONE cursor (Phase 12B). The hook selects the
 * backend's spatial state for race time t; it never computes, interpolates or
 * extrapolates a position.
 *
 * - Track: loaded once per session. Every value is tagged with its session
 *   (and track), so a session change shows nothing old - not even for a frame.
 * - Paused or scrubbing: one exact `?at=t` request once the cursor has been
 *   still for DEBOUNCE_MS; only the latest request may land.
 * - Playing: batched windows (windowForRate) fetched ahead of t; the shown
 *   state is the window state with the largest time at or before t. The
 *   API allows 120 requests a minute, so a request per tick is impossible.
 * - Live sessions: spatial evidence is built from recordings only.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../command/api";
import { fetchStateAt, fetchTrack, fetchWindow, windowForRate } from "./api";
import type { DriverState, SpatialWindow, TrackReference } from "./types";

export const DEBOUNCE_MS = 120;
const WINDOWS_KEPT = 3;

export type SpatialReason = "RECORDING_ONLY" | "NO_RECORDING" | "UNVALIDATED";

export interface Shown { at: number; drivers: DriverState[] }

export interface SpatialView {
  status: "loading" | "ready" | "unavailable" | "error";
  track: TrackReference | null;
  shown: Shown | null;
  /** The shown state is further from the cursor than one window step. */
  lagging: boolean;
  reason: SpatialReason | null;
  reasons: string[];
  error: ApiError | null;
  retry: () => void;
}

/** The window state with the largest time at or before t (selection only). */
export function selectState(w: SpatialWindow, t: number): Shown | null {
  let lo = 0, hi = w.states.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (Date.parse(w.states[mid].at) <= t) lo = mid + 1; else hi = mid;
  }
  if (lo === 0) return null;
  const s = w.states[lo - 1];
  return { at: Date.parse(s.at), drivers: s.drivers };
}

const asApiError = (e: unknown): ApiError =>
  (e instanceof ApiError ? e : new ApiError("unexpected", (e as Error)?.message || "Unexpected error.", null));

interface Pending { sid: string; trackId: string; from: number; step: number; reload: number }

export function useSpatial({ sid, t, playing, rate, live }: {
  /** The cursor; null until it exists (nothing is requested for a time that is not the cursor). */
  sid: string; t: number | null; playing: boolean; rate: number; live: boolean;
}): SpatialView {
  const [reload, setReload] = useState(0);
  const [trackSlot, setTrackSlot] = useState<{ sid: string; track: TrackReference | null; error: ApiError | null } | null>(null);
  const [paused, setPaused] = useState<{ sid: string; trackId: string; shown: Shown | null; error: ApiError | null } | null>(null);
  const [wins, setWins] = useState<{ sid: string; trackId: string; list: SpatialWindow[] } | null>(null);
  const [pending, setPending] = useState<Pending[]>([]);
  const [failed, setFailed] = useState<(Pending & { error: ApiError })[]>([]);
  const seq = useRef(0);

  // ---- track: once per session (and on retry)
  useEffect(() => {
    if (live) return;
    const ctrl = new AbortController();
    fetchTrack(sid, ctrl.signal)
      .then((track) => setTrackSlot({ sid, track, error: null }))
      .catch((e: unknown) => { if (!ctrl.signal.aborted) setTrackSlot({ sid, track: null, error: asApiError(e) }); });
    return () => ctrl.abort();
  }, [sid, live, reload]);

  const mine = !live && trackSlot?.sid === sid ? trackSlot : null;
  const track = mine?.track ?? null;
  const trackId = track?.status === "VALIDATED_MAP_SECTOR" ? track.track_id : null;

  // ---- paused: one exact request per settled cursor; the latest wins
  useEffect(() => {
    if (!trackId || playing || t == null) return;
    const id = ++seq.current;
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      fetchStateAt(sid, t, trackId, ctrl.signal)
        .then((doc) => {
          if (id === seq.current) {
            setPaused({ sid, trackId, shown: { at: Date.parse(doc.at), drivers: doc.drivers }, error: null });
          }
        })
        .catch((e: unknown) => {
          if (id !== seq.current || ctrl.signal.aborted) return;
          setPaused((p) => ({ sid, trackId, error: asApiError(e),
                              shown: p && p.sid === sid && p.trackId === trackId ? p.shown : null }));
        });
    }, DEBOUNCE_MS);
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, [sid, trackId, t, playing, reload]);

  // ---- playing: windows ahead of the cursor
  const plan = windowForRate(rate);
  const stepMs = plan.stepS * 1000, spanMs = plan.spanS * 1000;
  const ours = <T extends { sid: string; trackId: string }>(x: T) => x.sid === sid && x.trackId === trackId;
  const list = wins && trackId && ours(wins) ? wins.list.filter((w) => w.step_s === plan.stepS) : [];
  const current = t == null ? null : list.find((w) => Date.parse(w.from_ts) <= t && t <= Date.parse(w.to_ts)) ?? null;
  const flight = pending.filter((p) => ours(p) && p.step === plan.stepS);
  const blocked = (from: number) => failed.some((f) => ours(f) && f.step === plan.stepS && f.from === from
                                                   && f.reload === reload);
  let need: number | null = null;
  if (playing && trackId && t != null) {
    if (!current) {
      const from = Math.floor(t / stepMs) * stepMs;
      if (!flight.some((p) => p.from <= t && t <= p.from + spanMs) && !blocked(from)) need = from;
    } else {
      const next = Date.parse(current.to_ts);
      if (t > Date.parse(current.from_ts) + spanMs / 2 && !list.some((w) => Date.parse(w.from_ts) === next)
          && !flight.some((p) => p.from === next) && !blocked(next)) need = next;
    }
  }

  useEffect(() => {
    if (need == null || !trackId) return;
    const entry: Pending = { sid, trackId, from: need, step: plan.stepS, reload };
    setPending((p) => [...p, entry]);
    fetchWindow(sid, need, need + spanMs, plan.stepS, trackId)
      .then((w) => setWins((prev) => ({
        sid, trackId,
        list: [...(prev && prev.sid === sid && prev.trackId === trackId ? prev.list : []), w].slice(-WINDOWS_KEPT),
      })))
      .catch((e: unknown) => setFailed((f) => [...f.slice(-8), { ...entry, error: asApiError(e) }]))
      .finally(() => setPending((p) => p.filter((x) => x !== entry)));
  }, [need, sid, trackId, plan.stepS, spanMs, reload]);

  // ---- what is shown: of the exact state and the window state, the latest at
  // or before the cursor (so starting playback never steps back in time); with
  // neither at or before it, the last exact state (flagged lagging)
  const exact = paused && trackId && ours(paused) ? paused.shown : null;
  const fromWindow = current && t != null ? selectState(current, t) : null;
  const latest = [exact, fromWindow].reduce<Shown | null>(
    (best, s) => (s != null && t != null && s.at <= t && (best == null || s.at > best.at) ? s : best), null);
  const shown = t == null ? null : latest ?? exact;
  const lagging = shown != null && t != null && Math.abs(t - shown.at) > stepMs;

  const retry = useCallback(() => setReload((r) => r + 1), []);

  // ---- status
  const base = { track, shown: trackId ? shown : null, lagging, retry, reasons: [] as string[], error: null };
  if (live) return { ...base, track: null, shown: null, lagging: false, status: "unavailable", reason: "RECORDING_ONLY" };
  if (mine?.error) {
    const e = mine.error;
    if (e.kind === "not_found") return { ...base, status: "unavailable", reason: "NO_RECORDING", error: e };
    if (e.kind === "unvalidated") return { ...base, status: "unavailable", reason: "UNVALIDATED", reasons: e.reasons, error: e };
    return { ...base, status: "error", reason: null, error: e };
  }
  if (!track) return { ...base, status: "loading", reason: null };
  if (!trackId) {
    return { ...base, status: "unavailable", reason: "UNVALIDATED", reasons: track.validation.reasons };
  }
  const stateError = playing
    ? failed.filter((f) => ours(f) && f.reload === reload).at(-1)?.error ?? null
    : paused && ours(paused) ? paused.error : null;
  if (stateError) {
    if (stateError.kind === "unvalidated") {
      return { ...base, status: "unavailable", reason: "UNVALIDATED", reasons: stateError.reasons, error: stateError };
    }
    if (stateError.kind === "not_found") return { ...base, status: "unavailable", reason: "NO_RECORDING", error: stateError };
    return { ...base, status: "error", reason: null, error: stateError };
  }
  return { ...base, status: shown ? "ready" : "loading", reason: null };
}
