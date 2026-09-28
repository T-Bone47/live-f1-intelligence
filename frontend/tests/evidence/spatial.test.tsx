/**
 * Evidence Workbench on the map (Phase 12C), on REAL backend output: the Dutch
 * GP pair's evidence_v1 and evidence_spatial_v1 (scripts/evidence_fixture.py)
 * and the locked Dutch GP track golden. Extents are drawn only where the
 * backend PLACED them; the browser never places anything.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LapPickers } from "../../src/components/evidence/LapPickers";
import { TrackContext } from "../../src/components/evidence/TrackContext";
import { EMPTY_DRAFT, type RequestDraft } from "../../src/evidence/request";
import { fetchEvidenceSpatial, type EvidenceSpatial, type TrackContextView } from "../../src/evidence/spatial";
import type { LapComparisonEvidenceV1 } from "../../src/evidence/types";
import { buildView } from "../../src/evidence/viewModel";
import { track } from "../spatial/fixture";
import { pair } from "../telemetry/fixture";
import { jsonResponse } from "./fixture";

afterEach(() => vi.unstubAllGlobals());

const evidence = () => pair().evidence as unknown as LapComparisonEvidenceV1;
const placed = () => pair().evidence_spatial as unknown as EvidenceSpatial;
const request = () => {
  const q = (pair() as unknown as { provenance: { request: Record<string, string | number> } }).provenance.request;
  return { sessionId: "openf1:11353", driverA: Number(q.driver_a), lapA: Number(q.lap_a),
           driverB: Number(q.driver_b), lapB: Number(q.lap_b), lapLengthM: Number(q.lap_length_m),
           lapLengthSource: String(q.lap_length_source) };
};
const HEADERS = () => ({ "X-Spatial-Contract": "evidence_spatial_v1", "X-Evidence-Id": evidence().evidence_id });

describe("fetchEvidenceSpatial (fail closed)", () => {
  const serve = (body: unknown, headers = HEADERS()) =>
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(body, 200, headers)));

  it("accepts the real document for the loaded evidence and track", async () => {
    serve(placed());
    const doc = await fetchEvidenceSpatial(request(), evidence(), track().track_id);
    expect(doc.segments.map((s) => s.label)).toEqual(evidence().attribution.segments.map((s) => s.label));
  });

  it.each([
    ["another evidence id", (d: EvidenceSpatial) => { d.evidence_id = "ev1_" + "0".repeat(24); }],
    ["another session", (d: EvidenceSpatial) => { d.session_id = "openf1:9161"; }],
    ["another track", (d: EvidenceSpatial) => { d.track_id = "trk1_other"; }],
    ["another driver", (d: EvidenceSpatial) => { d.driver_b = 1; }],
    ["segments reordered", (d: EvidenceSpatial) => { d.segments.reverse(); }],
    ["a NOT_PLACED extent with a path", (d: EvidenceSpatial) => {
      d.segments[10].a.polyline = d.segments[0].a.polyline; }],
    ["a PLACED extent without a path", (d: EvidenceSpatial) => { d.segments[0].a.polyline = null; }],
  ])("refuses %s", async (_n, tamper) => {
    const d = placed();
    tamper(d);
    serve(d);
    await expect(fetchEvidenceSpatial(request(), evidence(), track().track_id)).rejects.toMatchObject({ kind: "unsupported" });
  });

  it("refuses a response whose header names another evidence", async () => {
    serve(placed(), { ...HEADERS(), "X-Evidence-Id": "ev1_" + "1".repeat(24) });
    await expect(fetchEvidenceSpatial(request(), evidence(), track().track_id)).rejects.toMatchObject({ kind: "unsupported" });
  });
});

function ctx(over: Partial<TrackContextView> = {}): TrackContextView {
  return { status: "ready", track: track(), placed: placed(), reasons: [], message: null, retry: () => {}, ...over };
}

function draw(c: TrackContextView, selected: string | null = "R03", onSelect = vi.fn()) {
  const utils = render(<TrackContext ctx={c} view={buildView(evidence())} selected={selected} onSelect={onSelect} />);
  return { ...utils, onSelect };
}

describe("TrackContext", () => {
  it("draws the selected segment's two PLACED extents: A solid, B dashed", () => {
    const { container } = draw(ctx());
    const paths = [...container.querySelectorAll("path.tc-extent")];
    expect(paths.map((p) => p.getAttribute("data-side"))).toEqual(["a", "b"]);
    expect(container.querySelector("path.tc-extent.is-b")).not.toBeNull();
    expect(screen.getByText(/placed by each driver's own sample times/i)).toBeInTheDocument();
  });

  it("draws only PLACED extents and lists the rest with their reason", () => {
    const doc = placed();
    const seg = doc.segments.find((s) => s.label === "R03")!;
    seg.b = { ...seg.b, status: "NOT_PLACED", reason: "PIT_LANE", from_fraction: null, to_fraction: null,
              from_xy: null, to_xy: null, polyline: null };                      // tampered: B in the pit lane
    const { container } = draw(ctx({ placed: doc }));
    expect([...container.querySelectorAll("path.tc-extent")].map((p) => p.getAttribute("data-side"))).toEqual(["a"]);
    expect(screen.getByText(/R03 · B .*not placed: pit lane/i)).toBeInTheDocument();
    // the NO_DATA tail is listed, never drawn
    expect(screen.getByText(/R11 · A .*not placed: no telemetry/i)).toBeInTheDocument();
  });

  it("every placed segment is a named button that selects it", () => {
    const { onSelect } = draw(ctx());
    const ev = evidence();
    const a = ev.comparison.driver_a;
    const btn = screen.getByRole("button", { name: `R05, #${a.driver_number} lap ${a.lap_number}, placed by time` });
    fireEvent.click(btn);
    expect(onSelect).toHaveBeenCalledWith("R05");
    const placedCount = placed().segments.filter((s) => s.a.status === "PLACED").length;
    expect(screen.getAllByRole("button", { name: /placed by time$/ })).toHaveLength(placedCount);
  });

  it("without a validated track: unavailable, with the reason, and no map", () => {
    const { container } = draw(ctx({ status: "unavailable", track: null, placed: null,
                                     message: "no recording for openf1:9161", reasons: [] }));
    expect(screen.getByText("Track context unavailable")).toBeInTheDocument();
    expect(screen.getByText(/no recording for openf1:9161/)).toBeInTheDocument();
    expect(container.querySelector("svg")).toBeNull();
  });
});

describe("LapPickers", () => {
  const catalog = () => pair().catalog as unknown as { session_id: string; drivers: {
    driver_number: number; laps: { lap_number: number; duration_s: number | null; has_car_telemetry: boolean }[] }[] };

  function mockRoutes() {
    const fn = vi.fn(async (input: RequestInfo | URL) => {
      const path = decodeURIComponent(new URL(String(input), "http://localhost").pathname);
      if (path === "/api/v1/sessions") {
        return jsonResponse({ active: [], stored: [], stored_error: "database unavailable",
                              recorded: [pair().recorded_session] });
      }
      if (path.endsWith("/laps")) return jsonResponse(catalog(), 200, { "X-Data-Source": "recording" });
      if (path.endsWith("/track")) return jsonResponse(track(), 200, { "X-Spatial-Contract": "track_reference_v1" });
      return jsonResponse({ detail: "not mocked" }, 404);
    });
    vi.stubGlobal("fetch", fn);
    return fn;
  }

  it("loads nothing until opened, then works from recorded sessions with the database down", async () => {
    const fn = mockRoutes();
    let draft: RequestDraft = { ...EMPTY_DRAFT };
    const onChange = vi.fn((d: RequestDraft) => { draft = d; });
    const { rerender } = render(<LapPickers draft={draft} onChange={onChange} />);
    expect(fn).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /pick laps from a session/i }));
    const session = await screen.findByRole("combobox", { name: "Session" });
    expect(within(session).getByRole("option", { name: /Zandvoort/ })).toBeInTheDocument();
    fireEvent.change(session, { target: { value: "openf1:11353" } });
    rerender(<LapPickers draft={draft} onChange={onChange} />);
    await waitFor(() => expect(draft.lapLengthM).toBe(String(track().circuit.lap_length_m)));
    expect(draft.lapLengthSource).toBe(track().circuit.lap_length_source);
    expect(draft.sessionId).toBe("openf1:11353");
  });

  it("prefills even when the track answers after the laps (browser QA: the laps landing aborted the track)", async () => {
    const fn = mockRoutes();
    const base = fn.getMockImplementation()!;
    fn.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/track")) {
        await new Promise((r) => setTimeout(r, 60));
        // like a browser: an aborted request rejects instead of answering
        if (init?.signal?.aborted) throw new DOMException("The operation was aborted.", "AbortError");
      }
      return base(input);
    });
    let draft: RequestDraft = { ...EMPTY_DRAFT, sessionId: "openf1:11353" };
    const onChange = vi.fn((d: RequestDraft) => { draft = d; });
    render(<LapPickers draft={draft} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /pick laps from a session/i }));
    await waitFor(() => expect(draft.lapLengthM).toBe(String(track().circuit.lap_length_m)), { timeout: 2000 });
  });

  it("offers only laps with a time and stored car telemetry", async () => {
    mockRoutes();
    let draft: RequestDraft = { ...EMPTY_DRAFT, sessionId: "openf1:11353" };
    const onChange = vi.fn((d: RequestDraft) => { draft = d; });
    const { rerender } = render(<LapPickers draft={draft} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /pick laps from a session/i }));
    const [d0] = catalog().drivers;
    const carA = await screen.findByRole("combobox", { name: "Driver A car" });
    await waitFor(() => expect(within(carA).queryByRole("option", { name: new RegExp(`#${d0.driver_number}`) })).not.toBeNull());
    fireEvent.change(carA, { target: { value: String(d0.driver_number) } });
    rerender(<LapPickers draft={draft} onChange={onChange} />);
    const lapA = screen.getByRole("combobox", { name: "Driver A lap" });
    const offered = within(lapA).getAllByRole("option").filter((o) => (o as HTMLOptionElement).value !== "");
    const eligible = d0.laps.filter((l) => l.duration_s != null && l.has_car_telemetry);
    expect(offered.map((o) => Number((o as HTMLOptionElement).value))).toEqual(eligible.map((l) => l.lap_number));
    fireEvent.change(lapA, { target: { value: String(eligible[3].lap_number) } });
    expect(draft.driverA).toBe(String(d0.driver_number));
    expect(draft.lapA).toBe(String(eligible[3].lap_number));
  });
});
