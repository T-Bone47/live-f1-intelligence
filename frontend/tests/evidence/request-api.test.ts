import { afterEach, describe, expect, it, vi } from "vitest";
import {
  EMPTY_DRAFT, REAL_PAIR_PRESET, draftFromSearch, evidenceUrl, searchFromState, swapDraft, validateDraft,
} from "../../src/evidence/request";
import {
  EvidenceError, fetchLapComparisonEvidence, fetchTelemetryReference, isSupportedReference, telemetryUrl,
} from "../../src/evidence/api";
import { golden, jsonResponse } from "./fixture";

afterEach(() => vi.unstubAllGlobals());

describe("request validation mirrors backend validate_request", () => {
  it("accepts the real preset", () => {
    expect(validateDraft(REAL_PAIR_PRESET.draft).ok).toBe(true);
  });
  it("refuses a missing lap length or citation — a length is never guessed", () => {
    const v = validateDraft({ ...REAL_PAIR_PRESET.draft, lapLengthM: "", lapLengthSource: "" });
    expect(v.ok).toBe(false);
    if (!v.ok) { expect(v.errors.lapLengthM).toBeTruthy(); expect(v.errors.lapLengthSource).toBeTruthy(); }
  });
  it("refuses car numbers outside 1-99, laps < 1, the same lap twice and bad session ids", () => {
    const v = validateDraft({ ...REAL_PAIR_PRESET.draft, driverA: "100", lapA: "0", sessionId: "a/b" });
    expect(v.ok).toBe(false);
    if (!v.ok) expect(Object.keys(v.errors).sort()).toEqual(["driverA", "lapA", "sessionId"]);
    expect(validateDraft({ ...REAL_PAIR_PRESET.draft, driverB: "55", lapB: "19" }).ok).toBe(false);
    expect(validateDraft(EMPTY_DRAFT).ok).toBe(false);
  });
  it("round-trips through the URL and swaps A/B without touching values", () => {
    const v = validateDraft(REAL_PAIR_PRESET.draft);
    if (!v.ok) throw new Error("preset invalid");
    const search = searchFromState(v.request, "R09");
    expect(draftFromSearch(search)).toEqual(REAL_PAIR_PRESET.draft);
    expect(new URLSearchParams(search).get("seg")).toBe("R09");
    const s = swapDraft(REAL_PAIR_PRESET.draft);
    expect([s.driverA, s.lapA, s.driverB, s.lapB]).toEqual(["63", "16", "55", "19"]);
    expect(evidenceUrl(v.request)).toContain("/api/v1/sessions/openf1%3A9161/evidence/lap-comparison?driver_a=55&lap_a=19");
  });
});

describe("fetchLapComparisonEvidence classifies the HTTP contract and fails closed", () => {
  const req = (() => { const v = validateDraft(REAL_PAIR_PRESET.draft); if (!v.ok) throw new Error(); return v.request; })();
  const call = (r: Response | Error) => fetchLapComparisonEvidence(req, undefined,
    vi.fn(async () => { if (r instanceof Error) throw r; return r; }) as unknown as typeof fetch);

  it("returns the evidence unchanged on 200", async () => {
    const ev = golden();
    const out = await call(jsonResponse(ev, 200, { "X-Evidence-Id": ev.evidence_id }));
    expect(out.evidence).toEqual(ev);
  });
  it.each([
    [422, "invalid"], [404, "not_found"], [500, "withheld"], [429, "rate_limited"], [503, "unavailable"], [418, "unexpected"],
  ] as const)("HTTP %i -> %s, backend detail kept verbatim", async (status, kind) => {
    await expect(call(jsonResponse({ detail: "driver 55 lap 99 unknown" }, status)))
      .rejects.toMatchObject({ kind, message: "driver 55 lap 99 unknown", status });
  });
  it("network failure -> unavailable", async () => {
    await expect(call(new TypeError("fetch failed"))).rejects.toMatchObject({ kind: "unavailable" });
  });
  it("a 200 body that is not evidence_v1 is refused", async () => {
    await expect(call(jsonResponse({ ...golden(), contract_version: "evidence_v2" })))
      .rejects.toMatchObject({ kind: "unsupported" });
  });
  it("an X-Evidence-Id header that disagrees with the body is refused", async () => {
    await expect(call(jsonResponse(golden(), 200, { "X-Evidence-Id": "ev1_tampered" })))
      .rejects.toMatchObject({ kind: "unsupported" });
  });
});

describe("drill-down follows only the existing telemetry route", () => {
  const ref = golden().attribution.segments[8].telemetry_references[0];
  it("builds a RAW request for exactly the referenced window and channels", () => {
    const u = new URL(telemetryUrl(ref), "http://x");
    expect(u.pathname).toBe("/api/v1/sessions/openf1:9161/telemetry/55");
    expect(u.searchParams.get("start")).toBe(ref.start);
    expect(u.searchParams.get("end")).toBe(ref.end);
    expect(u.searchParams.get("frequency")).toBe("RAW");
    expect(u.searchParams.get("fields")).toBe("speed,throttle,brake,gear,drs");
  });
  it("refuses a reference outside the telemetry route shape", async () => {
    const bad = { ...ref, route: "https://evil.example/api/v1/sessions/x/telemetry/55" };
    expect(isSupportedReference(bad)).toBe(false);
    await expect(fetchTelemetryReference(bad)).rejects.toBeInstanceOf(EvidenceError);
  });
  it("refuses telemetry for another driver (identity guard)", async () => {
    const f = vi.fn(async () => jsonResponse({ driver_number: 63, series: {} })) as unknown as typeof fetch;
    await expect(fetchTelemetryReference(ref, undefined, f)).rejects.toMatchObject({ kind: "unsupported" });
  });
});
