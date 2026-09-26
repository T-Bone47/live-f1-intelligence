/**
 * Spatial test helpers. Both documents are REAL backend output from the 2026
 * Dutch GP recording:
 * - docs/spatial/track_reference_v1_dutch_gp_2026.json (the locked golden)
 * - tests/fixtures/spatial/dutch_gp_states.json (scripts/spatial_fixture.py:
 *   spatial_state_v1 at LAP 2, 10, 40 and FINAL, and a 10 s window at LAP 40)
 *
 * `echoWindow` is transport scaffolding for request-count tests only: it
 * answers any window request with the real LAP 40 driver states re-timed to
 * the requested grid. It is never used as evidence of a position.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { vi } from "vitest";
import type { SpatialState, SpatialWindow, TrackReference } from "../../src/spatial/types";

const TRACK = readFileSync(resolve(process.cwd(), "..", "docs", "spatial",
  "track_reference_v1_dutch_gp_2026.json"), "utf-8");
const STATES = readFileSync(resolve(process.cwd(), "tests", "fixtures", "spatial",
  "dutch_gp_states.json"), "utf-8");

export const SID = "openf1:11353";

interface StatesFixture { provenance: Record<string, string>; states_at: SpatialState[]; window: SpatialWindow }

/** Fresh deep copies each call, so a test can tamper without leaking. */
export const track = (): TrackReference => JSON.parse(TRACK) as TrackReference;
export const fixture = (): StatesFixture => JSON.parse(STATES) as StatesFixture;
/** The real states: [LAP 2, LAP 10, LAP 40, FINAL]. */
export const stateAt = (i: 0 | 1 | 2 | 3): SpatialState => fixture().states_at[i];

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

export const contractHeader = (c: string) => ({ "X-Spatial-Contract": c });

export function echoWindow(url: URL): SpatialWindow {
  const w = fixture().window;
  const from = Date.parse(url.searchParams.get("from")!);
  const to = Date.parse(url.searchParams.get("to")!);
  const step = Number(url.searchParams.get("step"));
  const drivers = w.states[0].drivers;
  const states = [];
  for (let ms = from; ms <= to + 1e-6; ms += step * 1000) states.push({ at: new Date(ms).toISOString(), drivers });
  return { ...w, from_ts: new Date(from).toISOString(), to_ts: new Date(to).toISOString(), step_s: step, states };
}

/** fetch mock for the spatial routes; `state` answers /spatial?at=. */
export function mockSpatial(opts: {
  track?: () => Response | Promise<Response>;
  state?: (url: URL) => Response | Promise<Response>;
  window?: (url: URL) => Response | Promise<Response>;
} = {}) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    const path = decodeURIComponent(url.pathname);
    if (path.endsWith("/track")) {
      return opts.track ? opts.track() : json(track(), 200, contractHeader("track_reference_v1"));
    }
    if (path.endsWith("/spatial/window")) {
      return opts.window ? opts.window(url) : json(echoWindow(url), 200, contractHeader("spatial_window_v1"));
    }
    if (path.endsWith("/spatial")) {
      return opts.state ? opts.state(url) : json(stateAt(2), 200, contractHeader("spatial_state_v1"));
    }
    return json({ detail: "not mocked" }, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export const calls = (fn: ReturnType<typeof mockSpatial>, suffix: string) =>
  fn.mock.calls.map((c) => new URL(String(c[0]), "http://localhost"))
    .filter((u) => decodeURIComponent(u.pathname).endsWith(suffix));
