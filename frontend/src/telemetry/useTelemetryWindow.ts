/**
 * Car telemetry for the ONE cursor (Phase 12C). The hook loads RAW windows of
 * one driver's stored samples and SELECTS the ones at or before the cursor t;
 * it never interpolates, fills or computes a value, and never shows a sample
 * after t (the window reaches past t only so playback has data ready).
 *
 * - Paused or scrubbing: one request for [t - 60 s, t + 60 s] once the cursor
 *   has been still for DEBOUNCE_MS; only the latest request may land.
 * - Playing: the next window is fetched as soon as the cursor nears the end of
 *   the loaded one; it reaches further ahead at higher rates (aheadForRate), so
 *   requests stay rare under the API's 120 requests a minute.
 * - Every window is tagged with its session and driver: after a change nothing
 *   old is shown. A failed request stops requests until retry.
 * - Live sessions: unavailable (replay of stored or recorded sessions only).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../command/api";
import { fetchTelemetryWindow } from "./api";
import { channelView } from "./select";
import { CHANNELS, type Channel, type ChannelView, type DataSource, type TelemetryWindow } from "./types";

export const DEBOUNCE_MS = 120;
/** How much race time before the cursor the panel shows. */
export const TELEMETRY_BACK_MS = 60_000;

/**
 * Race time loaded ahead of the cursor per replay rate (ledger ruling): about
 * one request per 15-30 s of wall time at every rate, and back + ahead stays
 * under the route's 20-minute RAW cap.
 */
const AHEAD: [number, number][] = [[1, 60_000], [4, 120_000], [16, 480_000], [64, 1_080_000]];

export function aheadForRate(rate: number): number {
  let ahead = AHEAD[0][1];
  for (const [r, ms] of AHEAD) if (rate >= r) ahead = ms;
  return ahead;
}

export type TelemetryReason = "LIVE" | "NO_TELEMETRY";

export interface TelemetryView {
  status: "idle" | "loading" | "ready" | "unavailable" | "error";
  /** Samples in [from, to]; `to` is the cursor. */
  view: { from: number; to: number; channels: Record<Channel, ChannelView> } | null;
  dataSource: DataSource | null;
  provenanceClass: string | null;
  reason: TelemetryReason | null;
  error: ApiError | null;
  retry: () => void;
}

interface Flight { sid: string; driver: number; from: number; to: number; id: number; ctrl: AbortController }

const asApiError = (e: unknown): ApiError =>
  (e instanceof ApiError ? e : new ApiError("unexpected", (e as Error)?.message || "Unexpected error.", null));

export function useTelemetryWindow({ sid, driver, t, playing, rate, live }: {
  sid: string; driver: number | null; t: number | null; playing: boolean; rate: number; live: boolean;
}): TelemetryView {
  const [loaded, setLoaded] = useState<TelemetryWindow | null>(null);
  const [failed, setFailed] = useState<{ sid: string; driver: number; error: ApiError } | null>(null);
  const flight = useRef<Flight | null>(null);
  const seq = useRef(0);

  const mine = loaded && loaded.sid === sid && loaded.driver === driver ? loaded : null;
  const blocked = failed && failed.sid === sid && failed.driver === driver ? failed : null;
  const ahead = aheadForRate(playing ? rate : 1);

  useEffect(() => {
    if (live || driver == null || t == null || blocked) return undefined;
    const margin = playing ? ahead / 4 : 0;
    const covers = (w: { from: number; to: number }) => w.from <= t - TELEMETRY_BACK_MS && t <= w.to - margin;
    if (mine && covers(mine)) return undefined;
    const fl = flight.current;
    if (fl && fl.sid === sid && fl.driver === driver && covers(fl)) return undefined;
    const from = t - TELEMETRY_BACK_MS, to = t + ahead;
    const start = () => {
      flight.current?.ctrl.abort();
      const id = ++seq.current;
      const ctrl = new AbortController();
      flight.current = { sid, driver, from, to, id, ctrl };
      fetchTelemetryWindow(sid, driver, from, to, ctrl.signal).then((w) => {
        if (id !== seq.current) return;                  // a newer request owns the slot
        flight.current = null;
        setLoaded(w);
      }, (e: unknown) => {
        if ((e as Error)?.name === "AbortError" || id !== seq.current) return;
        flight.current = null;
        setFailed({ sid, driver, error: asApiError(e) });
      });
    };
    if (playing) {
      start();
      return undefined;
    }
    const timer = setTimeout(start, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [sid, driver, t, playing, ahead, live, mine, blocked]);

  const view = useMemo(() => {
    if (!mine || t == null || t < mine.from || t > mine.to) return null;
    const from = Math.max(mine.from, t - TELEMETRY_BACK_MS);
    const channels = {} as Record<Channel, ChannelView>;
    for (const c of CHANNELS) channels[c] = channelView(mine.samples[c], from, t, mine.available[c]);
    return { from, to: t, channels };
  }, [mine, t]);

  const retry = useCallback(() => setFailed(null), []);

  let status: TelemetryView["status"];
  let reason: TelemetryReason | null = null;
  if (live) {
    status = "unavailable";
    reason = "LIVE";
  } else if (driver == null) {
    status = "idle";
  } else if (blocked) {
    status = blocked.error.kind === "not_found" ? "unavailable" : "error";
    if (status === "unavailable") reason = "NO_TELEMETRY";
  } else {
    status = view ? "ready" : "loading";
  }
  return {
    status, view: live ? null : view, dataSource: mine?.dataSource ?? null,
    provenanceClass: mine?.provenanceClass ?? null, reason,
    error: status === "error" ? blocked!.error : null, retry,
  };
}
