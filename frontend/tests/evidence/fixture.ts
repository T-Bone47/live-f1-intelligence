/**
 * Test helpers. The evidence fixture is the REAL, byte-locked golden file
 * produced by the backend (docs/evidence/evidence_v1_singapore.json) — not a
 * hand-written sample — so a contract change on the backend reaches these
 * tests directly.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { vi } from "vitest";
import type { LapComparisonEvidenceV1 } from "../../src/evidence/types";

// vitest runs from frontend/ (npm test); import.meta.url is rewritten to /@fs/ here.
const docs = (name: string) => resolve(process.cwd(), "..", "docs", "evidence", name);

export const GOLDEN_TEXT = readFileSync(docs("evidence_v1_singapore.json"), "utf-8");
export const SCHEMA = JSON.parse(readFileSync(docs("evidence_v1.schema.json"), "utf-8"));

/** A fresh deep copy each call, so a test can tamper without leaking. */
export function golden(): LapComparisonEvidenceV1 {
  return JSON.parse(GOLDEN_TEXT) as LapComparisonEvidenceV1;
}

export const REAL_SEARCH =
  "?session=openf1%3A9161&driver_a=55&lap_a=19&driver_b=63&lap_b=16&lap_length_m=4940"
  + "&lap_length_source=Wikipedia%2C+2023+Singapore+Grand+Prix%3A+course+length+4.940+km+%28Marina+Bay+2023-2024+layout%29";

export function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(typeof body === "string" ? body : JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json", ...headers },
  });
}

/** fetch mock: evidence route -> the given evidence; telemetry route -> the given handler. */
export function mockFetch(opts: {
  evidence?: () => Response;
  telemetry?: (url: string) => Response;
} = {}) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/evidence/lap-comparison")) {
      if (opts.evidence) return opts.evidence();
      const ev = golden();
      return jsonResponse(ev, 200, { "X-Evidence-Id": ev.evidence_id, "Server-Timing": "db;dur=1.0" });
    }
    if (url.includes("/telemetry/")) {
      if (opts.telemetry) return opts.telemetry(url);
      return jsonResponse({ detail: "not mocked" }, 404);
    }
    return jsonResponse({ detail: "unknown route" }, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}
