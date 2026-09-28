/**
 * Telemetry test helpers. tests/fixtures/evidence/dutch_gp_pair.json is REAL
 * backend output (scripts/evidence_fixture.py, 2026 Dutch GP recording):
 * driver A's RAW car telemetry for 120 s centred on the LAP 40 frame, the
 * matching spatial trace, and the pair's evidence.
 *
 * `serveTelemetry` is transport scaffolding: it answers a telemetry request
 * with the fixture's real samples that fall inside the requested window and
 * echoes the window, as the route does. Beyond the fixture's 120 s it has no
 * samples; tests keep the cursor inside it.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { vi } from "vitest";
import type { TelemetryDoc } from "../../src/telemetry/types";

const PAIR = readFileSync(resolve(process.cwd(), "tests", "fixtures", "evidence",
  "dutch_gp_pair.json"), "utf-8");

export interface PairFixture {
  provenance: { pair: [number, number][]; cursor: string; session_id: string };
  telemetry: TelemetryDoc;
  trace: { samples: { ts: string; x: number; y: number }[]; driver_number: number };
  evidence: Record<string, unknown>;
  evidence_spatial: Record<string, unknown>;
  catalog: Record<string, unknown>;
  recorded_session: Record<string, unknown>;
}

export const pair = (): PairFixture => JSON.parse(PAIR) as PairFixture;
export const SID = "openf1:11353";
export const CURSOR = Date.parse(pair().provenance.cursor);
export const DRIVER_A = pair().provenance.pair[0][0];
export const DRIVER_B = pair().provenance.pair[1][0];

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

export const SOURCE = { "X-Data-Source": "recording" };

export function serveTelemetry(url: URL): Response {
  const driver = Number(decodeURIComponent(url.pathname).split("/").pop());
  const doc = pair().telemetry;
  if (driver !== doc.driver_number) return json({ detail: "no stored telemetry for this driver/session" }, 404);
  const start = url.searchParams.get("start")!, end = url.searchParams.get("end")!;
  const from = Date.parse(start), to = Date.parse(end);
  const series: TelemetryDoc["series"] = {};
  for (const [k, pts] of Object.entries(doc.series)) {
    series[k as keyof TelemetryDoc["series"]] = pts!.filter((p) => {
      const t = Date.parse(p.ts);
      return t >= from && t <= to;
    });
  }
  return json({ ...doc, window: { start, end }, series }, 200, SOURCE);
}

export function mockTelemetry(handler: (url: URL) => Response | Promise<Response> = serveTelemetry) {
  const fn = vi.fn(async (input: RequestInfo | URL) => handler(new URL(String(input), "http://localhost")));
  vi.stubGlobal("fetch", fn);
  return fn;
}

export const requests = (fn: ReturnType<typeof mockTelemetry>) =>
  fn.mock.calls.map((c) => new URL(String(c[0]), "http://localhost"));
