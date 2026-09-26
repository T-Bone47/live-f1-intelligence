/**
 * Command Center API client (Phase 11). Three read-only calls:
 *   GET /api/v1/sessions                     discovery (active hubs + stored)
 *   GET /api/v1/sessions/{sid}/laps          stored drivers and laps
 *   GET /api/v1/sessions/{sid}/timeline      session_timeline_v1
 *
 * Errors keep the backend's own message. A timeline that is not
 * session_timeline_v1, or that belongs to another session, is refused here
 * (fail closed) and never rendered.
 */

import {
  TIMELINE_CONTRACT, type LapCatalog, type SessionCatalog, type Timeline,
} from "./types";

export type ApiErrorKind =
  | "not_found"      // 404: unknown session / no recording
  | "invalid"        // 422
  | "withheld"       // 500: backend refused to serve (fail closed)
  | "rate_limited"   // 429
  | "unavailable"    // network failure, 502/503/504
  | "unsupported"    // a 200 body that is not the expected contract
  | "unexpected";

export class ApiError extends Error {
  constructor(readonly kind: ApiErrorKind, message: string, readonly status: number | null) {
    super(message);
    this.name = "ApiError";
  }
}

const SID_OK = /^[^/\\\s]{1,64}$/;

function kindForStatus(status: number): ApiErrorKind {
  if (status === 404) return "not_found";
  if (status === 422) return "invalid";
  if (status === 429) return "rate_limited";
  if (status === 500) return "withheld";
  if (status === 502 || status === 503 || status === 504) return "unavailable";
  return "unexpected";
}

async function detailOf(r: Response): Promise<string> {
  try {
    const d = (await r.json())?.detail;
    if (typeof d === "string") return d;
  } catch { /* non-JSON body */ }
  return `HTTP ${r.status}`;
}

async function getJson(url: string, signal: AbortSignal | undefined, fetchImpl: typeof fetch):
  Promise<{ body: unknown; response: Response }> {
  let r: Response;
  try {
    r = await fetchImpl(url, { signal, headers: { Accept: "application/json" } });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") throw e;
    throw new ApiError("unavailable", "The API could not be reached.", null);
  }
  if (!r.ok) throw new ApiError(kindForStatus(r.status), await detailOf(r), r.status);
  try {
    return { body: await r.json(), response: r };
  } catch {
    throw new ApiError("unsupported", "The response was not JSON.", r.status);
  }
}

function sessionPath(sid: string): string {
  if (!SID_OK.test(sid)) throw new ApiError("invalid", "Session id may not contain slashes or spaces.", null);
  return `/api/v1/sessions/${encodeURIComponent(sid)}`;
}

export async function fetchSessionCatalog(signal?: AbortSignal, fetchImpl: typeof fetch = fetch):
  Promise<SessionCatalog> {
  const { body } = await getJson("/api/v1/sessions", signal, fetchImpl);
  const c = body as Partial<SessionCatalog> | null;
  if (!c || !Array.isArray(c.active) || !Array.isArray(c.stored)) {
    throw new ApiError("unsupported", "Session list has an unexpected shape.", 200);
  }
  return c as SessionCatalog;
}

export async function fetchLapCatalog(sid: string, signal?: AbortSignal, fetchImpl: typeof fetch = fetch):
  Promise<LapCatalog> {
  const { body } = await getJson(`${sessionPath(sid)}/laps`, signal, fetchImpl);
  const c = body as Partial<LapCatalog> | null;
  if (!c || c.session_id !== sid || !Array.isArray(c.drivers)) {
    throw new ApiError("unsupported", `Lap list is not for session ${sid}.`, 200);
  }
  return c as LapCatalog;
}

/** Structural checks the UI relies on; the backend has already validated. */
export function checkTimeline(body: unknown, sid: string): Timeline {
  const t = body as Partial<Timeline> | null;
  if (!t || t.contract_version !== TIMELINE_CONTRACT || !Array.isArray(t.frames) || t.frames.length === 0) {
    throw new ApiError("unsupported", `Response is not ${TIMELINE_CONTRACT}; nothing is rendered.`, 200);
  }
  if (t.session?.session_id !== sid) {
    throw new ApiError("unsupported",
      `Timeline belongs to ${t.session?.session_id ?? "an unknown session"}, not ${sid}.`, 200);
  }
  t.frames.forEach((f, i) => {
    if (f.index !== i || !Array.isArray(f.rows)) {
      throw new ApiError("unsupported", `Timeline frame ${i} is malformed.`, 200);
    }
  });
  for (const key of ["drivers", "stints", "pit_stops", "race_control", "weather", "events", "limitations"] as const) {
    if (!Array.isArray(t[key])) throw new ApiError("unsupported", `Timeline has no ${key} list.`, 200);
  }
  return t as Timeline;
}

export async function fetchTimeline(sid: string, signal?: AbortSignal, fetchImpl: typeof fetch = fetch):
  Promise<Timeline> {
  const { body, response } = await getJson(`${sessionPath(sid)}/timeline`, signal, fetchImpl);
  const header = response.headers.get("X-Timeline-Contract");
  if (header && header !== TIMELINE_CONTRACT) {
    throw new ApiError("unsupported", `Server declared contract ${header}.`, 200);
  }
  return checkTimeline(body, sid);
}
