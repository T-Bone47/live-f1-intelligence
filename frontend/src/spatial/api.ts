/**
 * Spatial API client (Phase 12B). Three read-only calls on the recording's
 * validated spatial evidence:
 *   GET /api/v1/sessions/{sid}/track                        track_reference_v1
 *   GET /api/v1/sessions/{sid}/spatial?at=                  spatial_state_v1
 *   GET /api/v1/sessions/{sid}/spatial/window?from&to&step  spatial_window_v1
 *
 * Fail closed: a response is refused unless it carries its contract (header
 * and body), belongs to the requested session and the loaded track, answers
 * the request it was sent for, and lists each driver once in order. HTTP
 * errors keep the backend's message; a 409 carries the gate's reasons.
 */

import { ApiError, getJson, sessionPath } from "../command/api";
import {
  STATE_CONTRACT, TRACK_CONTRACT, WINDOW_CONTRACT,
  type DriverState, type SpatialState, type SpatialWindow, type TrackReference,
} from "./types";

const refuse = (message: string): never => { throw new ApiError("unsupported", message, 200); };

function checkHeader(response: Response, contract: string): void {
  const header = response.headers.get("X-Spatial-Contract");
  if (header !== contract) refuse(`Server declared ${header ?? "no contract"}, not ${contract}.`);
}

function checkDrivers(drivers: unknown, where: string): void {
  if (!Array.isArray(drivers)) refuse(`${where} has no driver list.`);
  const nums = (drivers as DriverState[]).map((d) => d?.driver_number);
  if (!nums.every((n, i) => Number.isInteger(n) && (i === 0 || n > nums[i - 1]))) {
    refuse(`${where} lists drivers out of order or twice.`);
  }
}

export function checkTrack(body: unknown, sid: string): TrackReference {
  const t = body as Partial<TrackReference> | null;
  if (!t || t.contract_version !== TRACK_CONTRACT || typeof t.track_id !== "string") {
    refuse(`Response is not ${TRACK_CONTRACT}.`);
  }
  if (t!.session?.session_id !== sid) refuse(`Track belongs to ${t!.session?.session_id ?? "an unknown session"}, not ${sid}.`);
  if (!Array.isArray(t!.timing_lines) || !Array.isArray(t!.sectors) || !t!.validation) refuse("Track is malformed.");
  const polyline = t!.reference?.polyline ?? null;
  if (t!.status === "VALIDATED_MAP_SECTOR") {
    if (!Array.isArray(polyline) || polyline.length < 3) refuse("Validated track has no reference polyline.");
    if (t!.sectors!.length !== 3) refuse("Validated track does not have three sectors.");
  } else if (t!.status === "UNVALIDATED") {
    if (polyline != null || t!.sectors!.length > 0) refuse("Unvalidated track publishes geometry.");
  } else {
    refuse(`Unknown track status ${String(t!.status)}.`);
  }
  return t as TrackReference;
}

export async function fetchTrack(sid: string, signal?: AbortSignal, f: typeof fetch = fetch): Promise<TrackReference> {
  const { body, response } = await getJson(`${sessionPath(sid)}/track`, signal, f);
  checkHeader(response, TRACK_CONTRACT);
  return checkTrack(body, sid);
}

function checkIdentity(d: { session_id?: string; track_id?: string }, sid: string, trackId: string, what: string) {
  if (d.session_id !== sid) refuse(`${what} belongs to ${d.session_id ?? "an unknown session"}, not ${sid}.`);
  if (d.track_id !== trackId) refuse(`${what} is for track ${d.track_id ?? "?"}, not the loaded ${trackId}.`);
}

const iso = (ms: number) => new Date(ms).toISOString();

export async function fetchStateAt(sid: string, atMs: number, trackId: string, signal?: AbortSignal,
                                   f: typeof fetch = fetch): Promise<SpatialState> {
  const q = new URLSearchParams({ at: iso(atMs) });
  const { body, response } = await getJson(`${sessionPath(sid)}/spatial?${q}`, signal, f);
  checkHeader(response, STATE_CONTRACT);
  const d = body as Partial<SpatialState> | null;
  if (!d || d.contract_version !== STATE_CONTRACT) refuse(`Response is not ${STATE_CONTRACT}.`);
  checkIdentity(d!, sid, trackId, "Spatial state");
  if (Date.parse(d!.at ?? "") !== Date.parse(iso(atMs))) {
    refuse(`Spatial state is for ${d!.at}, not the requested ${iso(atMs)}.`);
  }
  checkDrivers(d!.drivers, "Spatial state");
  return d as SpatialState;
}

export async function fetchWindow(sid: string, fromMs: number, toMs: number, stepS: number, trackId: string,
                                  signal?: AbortSignal, f: typeof fetch = fetch): Promise<SpatialWindow> {
  const q = new URLSearchParams({ from: iso(fromMs), to: iso(toMs), step: String(stepS) });
  const { body, response } = await getJson(`${sessionPath(sid)}/spatial/window?${q}`, signal, f);
  checkHeader(response, WINDOW_CONTRACT);
  const w = body as Partial<SpatialWindow> | null;
  if (!w || w.contract_version !== WINDOW_CONTRACT) refuse(`Response is not ${WINDOW_CONTRACT}.`);
  checkIdentity(w!, sid, trackId, "Spatial window");
  if (Date.parse(w!.from_ts ?? "") !== Date.parse(iso(fromMs)) || w!.step_s !== stepS) {
    refuse("Spatial window does not answer the request.");
  }
  if (!Array.isArray(w!.states) || w!.states.length === 0) refuse("Spatial window has no states.");
  let prev = -Infinity;
  for (const s of w!.states!) {
    const at = Date.parse(s?.at ?? "");
    if (!(at > prev)) refuse("Spatial window states are out of order.");
    prev = at;
    checkDrivers(s.drivers, "Spatial window state");
  }
  return w as SpatialWindow;
}

/**
 * Window span and step per replay rate (ledger ruling, from the measured
 * route cost on the real recording: 120 s at 0.5 s = 1.88 MB). Every request
 * stays near or under 1 MB and states arrive at a steady wall-clock interval:
 * 1x 500 ms, 4x 250 ms, 16x 125 ms, 64x 62 ms.
 */
const PLANS: [number, { spanS: number; stepS: number }][] = [
  [1, { spanS: 60, stepS: 0.5 }], [4, { spanS: 120, stepS: 1 }],
  [16, { spanS: 120, stepS: 2 }], [64, { spanS: 120, stepS: 4 }],
];

export function windowForRate(rate: number): { spanS: number; stepS: number } {
  let plan = PLANS[0][1];
  for (const [r, p] of PLANS) if (rate >= r) plan = p;
  return { ...plan };
}
