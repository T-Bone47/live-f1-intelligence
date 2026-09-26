/**
 * Command-center test helpers. The timeline fixture is the REAL, byte-locked
 * golden produced by the backend from the 2026 Dutch GP recording
 * (docs/timeline/session_timeline_v1_dutch_gp_2026.json) - not a sample.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { vi } from "vitest";
import type { SessionCatalog, Timeline } from "../../src/command/types";

const TEXT = readFileSync(resolve(process.cwd(), "..", "docs", "timeline",
  "session_timeline_v1_dutch_gp_2026.json"), "utf-8");

export const SID = "openf1:11353";

/** A fresh deep copy each call, so a test can tamper without leaking. */
export function golden(): Timeline {
  return JSON.parse(TEXT) as Timeline;
}

export function frameIndex(t: Timeline, lap: number): number {
  return t.frames.findIndex((f) => f.kind === "LAP" && f.lap === lap);
}

export const CATALOG: SessionCatalog = {
  active: [],
  stored: [{
    session_id: SID, provider: "openf1", provider_session_key: "11353", meeting_name: null,
    year: 2026, session_type: "Race", session_name: "Race", circuit_short_name: "Zandvoort",
    country_code: "NED", country_name: "Netherlands", location: "Zandvoort",
    date_start: "2026-08-23T13:00:00Z", date_end: "2026-08-23T15:00:00Z", status: "UNKNOWN",
    drivers: 22, laps: 1369, max_lap: 72, has_car_telemetry: true, timeline_available: true,
  }],
};

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

/** fetch mock for the three command-center routes. */
export function mockApi(opts: { timeline?: () => Response; catalog?: () => Response } = {}) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/timeline")) {
      return opts.timeline ? opts.timeline()
        : json(golden(), 200, { "X-Timeline-Contract": "session_timeline_v1" });
    }
    if (url.endsWith("/laps")) return json({ session_id: SID, drivers: [] });
    if (url.endsWith("/api/v1/sessions")) return opts.catalog ? opts.catalog() : json(CATALOG);
    return json({ detail: "not mocked" }, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export { json };
