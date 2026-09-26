/**
 * Spatial API client (Phase 12B) on the REAL track golden and REAL states:
 * every response is checked against its contract, its session, the loaded
 * track and the request it answers - anything else is refused (fail closed).
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../src/command/api";
import { fetchStateAt, fetchTrack, fetchWindow, windowForRate } from "../../src/spatial/api";
import { contractHeader, echoWindow, fixture, json, SID, stateAt, track } from "./fixture";

afterEach(() => vi.unstubAllGlobals());

const answer = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  vi.fn(async () => json(body, status, headers)) as unknown as typeof fetch;

const TRACK_ID = track().track_id;
const at = (s: { at: string }) => Date.parse(s.at);

describe("fetchTrack", () => {
  it("accepts the real validated track for its own session", async () => {
    const doc = await fetchTrack(SID, undefined, answer(track(), 200, contractHeader("track_reference_v1")));
    expect(doc.track_id).toBe("trk1_5c46f956e6753d06f8583341");
    expect(doc.status).toBe("VALIDATED_MAP_SECTOR");
    expect(doc.sectors).toHaveLength(3);
  });

  it.each([
    ["another session", (t: ReturnType<typeof track>) => { t.session.session_id = "openf1:1"; }],
    ["another contract", (t: ReturnType<typeof track>) => { (t as { contract_version: string }).contract_version = "x"; }],
    ["a validated track without a polyline", (t: ReturnType<typeof track>) => { t.reference!.polyline = null; }],
    ["a validated track without three sectors", (t: ReturnType<typeof track>) => { t.sectors = t.sectors.slice(1); }],
    ["an unvalidated track with a polyline", (t: ReturnType<typeof track>) => { t.status = "UNVALIDATED"; }],
  ])("refuses %s", async (_n, mutate) => {
    const t = track();
    mutate(t);
    await expect(fetchTrack(SID, undefined, answer(t, 200, contractHeader("track_reference_v1"))))
      .rejects.toMatchObject({ kind: "unsupported" });
  });

  it("refuses a wrong contract header", async () => {
    await expect(fetchTrack(SID, undefined, answer(track(), 200, contractHeader("spatial_state_v1"))))
      .rejects.toBeInstanceOf(ApiError);
  });
});

describe("fetchStateAt", () => {
  const s = stateAt(2);
  const ok = (body: unknown) => answer(body, 200, contractHeader("spatial_state_v1"));

  it("accepts the real state for its session, track and requested time", async () => {
    const doc = await fetchStateAt(SID, at(s), TRACK_ID, undefined, ok(s));
    expect(doc.drivers).toHaveLength(s.drivers.length);
  });

  it("asks for the exact time with a UTC offset", async () => {
    const f = ok(s);
    await fetchStateAt(SID, at(s), TRACK_ID, undefined, f);
    const url = new URL(String((f as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]), "http://x");
    expect(url.pathname).toBe(`/api/v1/sessions/${encodeURIComponent(SID)}/spatial`);
    expect(Date.parse(url.searchParams.get("at")!)).toBe(at(s));
    expect(url.searchParams.get("at")).toMatch(/Z$/);
  });

  it.each([
    ["another session", (d: ReturnType<typeof stateAt>) => { d.session_id = "openf1:1"; }],
    ["another track_id", (d: ReturnType<typeof stateAt>) => { d.track_id = "trk1_" + "0".repeat(24); }],
    ["another time than requested", (d: ReturnType<typeof stateAt>) => { d.at = stateAt(1).at; }],
    ["drivers out of order", (d: ReturnType<typeof stateAt>) => { d.drivers.reverse(); }],
    ["a duplicate driver", (d: ReturnType<typeof stateAt>) => { d.drivers.push(d.drivers[0]); }],
    ["another contract", (d: ReturnType<typeof stateAt>) => { (d as { contract_version: string }).contract_version = "spatial_trace_v1"; }],
  ])("refuses %s", async (_n, mutate) => {
    const d = stateAt(2);
    mutate(d);
    await expect(fetchStateAt(SID, at(s), TRACK_ID, undefined, ok(d))).rejects.toMatchObject({ kind: "unsupported" });
  });

  it("409 is 'unvalidated' and carries the gate reasons", async () => {
    const f = answer({ detail: { message: "spatial geometry not validated for this session",
                                 status: "UNVALIDATED", reasons: ["NO_CITED_LAP_LENGTH"] } }, 409);
    const err = await fetchStateAt(SID, at(s), TRACK_ID, undefined, f).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ kind: "unvalidated", status: 409, reasons: ["NO_CITED_LAP_LENGTH"] });
    expect(err.message).toBe("spatial geometry not validated for this session");
  });

  it.each([[404, "not_found"], [422, "invalid"], [500, "withheld"]])("HTTP %i is %s with the backend message", async (code, kind) => {
    const err = await fetchStateAt(SID, at(s), TRACK_ID, undefined, answer({ detail: "said the backend" }, code)).catch((e) => e);
    expect(err).toMatchObject({ kind, message: "said the backend" });
  });
});

describe("fetchWindow", () => {
  const w = fixture().window;
  const from = Date.parse(w.from_ts), to = Date.parse(w.to_ts);
  const ok = (body: unknown) => answer(body, 200, contractHeader("spatial_window_v1"));

  it("accepts the real window that answers the request", async () => {
    const doc = await fetchWindow(SID, from, to, 0.5, TRACK_ID, undefined, ok(w));
    expect(doc.states).toHaveLength(21);
  });

  it.each([
    ["another start", () => fetchWindow(SID, from + 500, to, 0.5, TRACK_ID, undefined, ok(w))],
    ["another step", () => fetchWindow(SID, from, to, 1, TRACK_ID, undefined, ok(w))],
    ["another track_id", () => fetchWindow(SID, from, to, 0.5, "trk1_other", undefined, ok(w))],
    ["states out of order", () => {
      const d = fixture().window; d.states.reverse();
      return fetchWindow(SID, from, to, 0.5, TRACK_ID, undefined, ok(d));
    }],
    ["no states", () => {
      const d = fixture().window; d.states = [];
      return fetchWindow(SID, from, to, 0.5, TRACK_ID, undefined, ok(d));
    }],
  ])("refuses %s", async (_n, call) => {
    await expect(call()).rejects.toMatchObject({ kind: "unsupported" });
  });

  it("the echo helper builds a window the client accepts (test scaffolding check)", async () => {
    const url = new URL(`http://x/w?from=${encodeURIComponent(w.from_ts)}&to=${encodeURIComponent(w.to_ts)}&step=2`);
    const doc = await fetchWindow(SID, from, to, 2, TRACK_ID, undefined, ok(echoWindow(url)));
    expect(doc.states).toHaveLength(6);
  });
});

describe("window plan per replay rate (ledger ruling, Task 3 measurement)", () => {
  it("keeps every window request near 1 MB and states at a steady wall interval", () => {
    expect(windowForRate(1)).toEqual({ spanS: 60, stepS: 0.5 });
    expect(windowForRate(4)).toEqual({ spanS: 120, stepS: 1 });
    expect(windowForRate(16)).toEqual({ spanS: 120, stepS: 2 });
    expect(windowForRate(64)).toEqual({ spanS: 120, stepS: 4 });
    for (const r of [1, 4, 16, 64]) {
      const { spanS, stepS } = windowForRate(r);
      expect(spanS).toBeLessThanOrEqual(120);
      expect(stepS).toBeGreaterThanOrEqual(0.25);
      expect(spanS / stepS + 1).toBeLessThanOrEqual(481);
    }
  });
});
