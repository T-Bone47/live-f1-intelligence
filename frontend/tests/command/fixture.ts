/**
 * Command-center test helpers. The timeline fixture is the REAL, byte-locked
 * golden produced by the backend from the 2026 Dutch GP recording
 * (docs/timeline/session_timeline_v1_dutch_gp_2026.json) - not a sample.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { vi } from "vitest";
import type { SessionCatalog, Timeline } from "../../src/command/types";
import { contractHeader, echoWindow, fixture as spatialFixture, track as spatialTrack } from "../spatial/fixture";

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

/** The real spatial state at exactly the requested time (fixture: LAP 2, 10, 40, FINAL), else 404. */
export function spatialAt(url: URL): Response {
  const at = Date.parse(url.searchParams.get("at")!);
  const s = spatialFixture().states_at.find((x) => Date.parse(x.at) === at);
  return s ? json(s, 200, contractHeader("spatial_state_v1"))
    : json({ detail: "no recorded spatial fixture at this time" }, 404);
}

/** fetch mock for the command-center routes, including the Phase 12B spatial ones. */
export function mockApi(opts: {
  timeline?: () => Response; catalog?: () => Response;
  track?: () => Response; state?: (url: URL) => Response; window?: (url: URL) => Response;
} = {}) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const u = new URL(url, "http://localhost");
    const path = decodeURIComponent(u.pathname);
    if (path.endsWith("/track")) {
      return opts.track ? opts.track() : json(spatialTrack(), 200, contractHeader("track_reference_v1"));
    }
    if (path.endsWith("/spatial/window")) {
      return opts.window ? opts.window(u) : json(echoWindow(u), 200, contractHeader("spatial_window_v1"));
    }
    if (path.endsWith("/spatial")) return opts.state ? opts.state(u) : spatialAt(u);
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
