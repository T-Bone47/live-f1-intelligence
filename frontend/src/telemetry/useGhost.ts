/**
 * The map ghost for a hovered telemetry sample (Phase 12C). For the hovered
 * sample's own time tau, the driver's classified location samples in
 * [tau - 2 s, tau] are requested (spatial_trace_v1) once the hover has rested
 * for DEBOUNCE_MS, and the ghost sits at the LAST of them: a real observation
 * of that driver at or before tau, never interpolated or moved onto the line.
 * No sample in those 2 s: no ghost, and the panel says so.
 */

import { useEffect, useRef, useState } from "react";
import { ApiError } from "../command/api";
import { fetchTrace } from "../spatial/api";
import { MAX_GAP_MS } from "./types";
import { DEBOUNCE_MS } from "./useTelemetryWindow";

export interface MapGhost {
  driver: number;
  /** The hovered telemetry sample's time. */
  hovered: number;
  /** The location sample's own time (at or before `hovered`, at most 2 s earlier). */
  at: number;
  x: number;
  y: number;
}

export interface GhostView {
  status: "idle" | "loading" | "ready" | "none" | "unavailable" | "error";
  ghost: MapGhost | null;
  error: ApiError | null;
}

interface Result { key: string; ghost: MapGhost | null; error: ApiError | null }

const IDLE: GhostView = { status: "idle", ghost: null, error: null };

export function useGhost({ sid, driver, hovered, trackId }: {
  sid: string; driver: number | null; hovered: number | null; trackId: string | null;
}): GhostView {
  const [result, setResult] = useState<Result | null>(null);
  const seq = useRef(0);
  const key = driver == null || hovered == null || trackId == null ? null : `${sid}|${trackId}|${driver}|${hovered}`;

  useEffect(() => {
    if (key == null || result?.key === key) return undefined;
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      const id = ++seq.current;
      fetchTrace(sid, driver!, hovered! - MAX_GAP_MS, hovered!, trackId!, ctrl.signal).then((tr) => {
        if (id !== seq.current) return;
        const own = tr.samples.filter((s) => Date.parse(s.ts) <= hovered!).at(-1);
        setResult({ key, error: null, ghost: own ? { driver: driver!, hovered: hovered!, at: Date.parse(own.ts),
                                                     x: own.x, y: own.y } : null });
      }, (e: unknown) => {
        if ((e as Error)?.name === "AbortError" || id !== seq.current) return;
        const error = e instanceof ApiError ? e : new ApiError("unexpected", (e as Error)?.message || "Unexpected error.", null);
        setResult({ key, ghost: null, error });
      });
    }, DEBOUNCE_MS);
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, [key, result?.key, sid, driver, hovered, trackId]);

  if (driver == null || hovered == null) return IDLE;
  if (trackId == null) return { status: "unavailable", ghost: null, error: null };
  if (result?.key !== key) return { status: "loading", ghost: null, error: null };
  if (result.error) return { status: "error", ghost: null, error: result.error };
  return { status: result.ghost ? "ready" : "none", ghost: result.ghost, error: null };
}
