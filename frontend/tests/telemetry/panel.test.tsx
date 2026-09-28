/**
 * Car telemetry panel and map ghost (Phase 12C), on the real Dutch GP samples.
 * The panel draws stored samples at or before the cursor, labels gaps, and
 * reports the hovered sample's own time; the ghost is that driver's own
 * location sample at or before the hovered time (within 2 s), never an
 * interpolated point.
 */

import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fmtClockTenths } from "../../src/command/format";
import { CarTelemetryPanel } from "../../src/components/telemetry/CarTelemetryPanel";
import { fetchTrace } from "../../src/spatial/api";
import { channelView, toSamples } from "../../src/telemetry/select";
import { CHANNELS, type Channel, type ChannelView, type Sample } from "../../src/telemetry/types";
import { useGhost } from "../../src/telemetry/useGhost";
import type { TelemetryView } from "../../src/telemetry/useTelemetryWindow";
import { track } from "../spatial/fixture";
import { CURSOR, DRIVER_A, json, pair, SID } from "./fixture";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const TRACK_ID = track().track_id;

function samples(): Record<Channel, Sample[]> {
  const series = pair().telemetry.series;
  return Object.fromEntries(CHANNELS.map((c) => [c, toSamples(series[c] ?? [])])) as Record<Channel, Sample[]>;
}

function viewAt(t: number, all = samples()): TelemetryView {
  const channels = Object.fromEntries(CHANNELS.map((c) =>
    [c, channelView(all[c], t - 60_000, t, all[c].length > 0)])) as Record<Channel, ChannelView>;
  return { status: "ready", view: { from: t - 60_000, to: t, channels }, dataSource: "recording",
           provenanceClass: "B", reason: null, error: null, retry: () => {} };
}

const panel = (telemetry: TelemetryView, over: Partial<Parameters<typeof CarTelemetryPanel>[0]> = {}) =>
  render(<CarTelemetryPanel telemetry={telemetry} driver={DRIVER_A} ident={undefined} playing={false}
                            hovered={null} onHover={() => {}} ghostStatus="idle" {...over} />);

describe("CarTelemetryPanel", () => {
  it("asks to select a driver when none is selected", () => {
    panel({ ...viewAt(CURSOR), status: "idle", view: null }, { driver: null });
    expect(screen.getByText("Select a driver to see car telemetry")).toBeTruthy();
  });

  it("renders every channel up to the cursor, with a hidden table", () => {
    const all = samples();
    panel(viewAt(CURSOR, all));
    const shown = all.speed.filter((s) => s.t <= CURSOR && s.t >= CURSOR - 60_000);
    for (const label of ["Speed", "Throttle", "Brake", "Gear", "RPM"]) {
      expect(screen.getByRole("group", { name: new RegExp(`^${label}`) })).toBeTruthy();
    }
    const table = screen.getByRole("table", { name: /car telemetry samples/i });
    expect(within(table).getAllByRole("row")).toHaveLength(shown.length + 1);   // + header
    expect(screen.getByTestId("latest-speed").textContent).toBe(`${shown.at(-1)!.value} kph`);
  });

  it("says DRS is not in this data when every sample is null", () => {
    panel(viewAt(CURSOR));
    expect(screen.getByText(/DRS: not in this data/)).toBeTruthy();
  });

  it("never draws a sample after the cursor", () => {
    const { container } = panel(viewAt(CURSOR - 17_300));
    const drawn = [...container.querySelectorAll("[data-t]")].map((e) => Number(e.getAttribute("data-t")));
    expect(drawn.length).toBeGreaterThan(0);
    expect(Math.max(...drawn)).toBeLessThanOrEqual(CURSOR - 17_300);
  });

  it("labels a gap between two stored samples", () => {
    const all = samples();
    const i = all.speed.findIndex((s) => s.t > CURSOR - 30_000);
    const [a, b] = [all.speed[i - 1], all.speed[i + 20]];
    const cut = Object.fromEntries(CHANNELS.map((c) =>
      [c, all[c].filter((s) => s.t <= a.t || s.t >= b.t)])) as Record<Channel, Sample[]>;   // real samples, a stretch removed
    panel(viewAt(CURSOR, cut));
    expect(screen.getAllByText(`No samples ${fmtClockTenths(a.t)}–${fmtClockTenths(b.t)}`).length).toBeGreaterThan(0);
  });

  it("steps the hovered sample by keyboard and clears it with Esc", () => {
    const onHover = vi.fn();
    const all = samples();
    const shown = all.speed.filter((s) => s.t <= CURSOR && s.t >= CURSOR - 60_000);
    panel(viewAt(CURSOR, all), { onHover });
    const chart = screen.getByRole("group", { name: /telemetry chart/i });
    fireEvent.keyDown(chart, { key: "End" });
    expect(onHover).toHaveBeenLastCalledWith(shown.at(-1)!.t);
    fireEvent.keyDown(chart, { key: "Home" });
    expect(onHover).toHaveBeenLastCalledWith(shown[0].t);
    fireEvent.keyDown(chart, { key: "Escape" });
    expect(onHover).toHaveBeenLastCalledWith(null);
  });

  it("a narrow panel stacks each label and value above a full-width plot (browser QA)", () => {
    const { container } = panel(viewAt(CURSOR));   // jsdom width falls back to 420 px: narrow
    const svg = container.querySelector("svg.ct-chart")!;
    const width = Number(svg.getAttribute("width"));
    const line = container.querySelector(".ct-speed polyline")!;
    const xs = line.getAttribute("points")!.split(" ").map((p) => Number(p.split(",")[0]));
    expect(Math.max(...xs)).toBeGreaterThan(width * 0.9);          // the plot reaches the right edge
    const value = screen.getByTestId("latest-speed");
    const label = container.querySelector(".ct-speed .ct-label")!;
    expect(Number(value.getAttribute("y"))).toBe(Number(label.getAttribute("y")));   // one header line
    const ys = line.getAttribute("points")!.split(" ").map((p) => Number(p.split(",")[1]));
    expect(Math.min(...ys)).toBeGreaterThan(Number(label.getAttribute("y")));        // the plot sits below it
    const axis = [...container.querySelectorAll(".ct-axis")].map((t) => Number(t.getAttribute("x")));
    expect(axis[1] - axis[0]).toBeGreaterThan(250);                                  // start and cursor labels apart
  });

  it("reads out the hovered sample at its own time", () => {
    const all = samples();
    const s = all.speed.filter((x) => x.t <= CURSOR).at(-5)!;
    panel(viewAt(CURSOR, all), { hovered: s.t, ghostStatus: "ready" });
    const out = screen.getByRole("status", { name: /hovered sample/i });
    expect(out.textContent).toContain(fmtClockTenths(s.t));
    expect(out.textContent).toContain(`${s.value} kph`);
    expect(out.textContent).toContain("shown on the map");
  });
});

// ------------------------------------------------------------- ghost

const trace = () => pair().trace;

function serveTrace(u: URL): Response {
  const from = Date.parse(u.searchParams.get("from")!), to = Date.parse(u.searchParams.get("to")!);
  const t = trace();
  const samplesIn = t.samples.filter((s) => { const ms = Date.parse(s.ts); return ms >= from && ms <= to; });
  return json({ ...t, from_ts: u.searchParams.get("from"), to_ts: u.searchParams.get("to"), samples: samplesIn },
              200, { "X-Spatial-Contract": "spatial_trace_v1" });
}

function mockTrace(handler: (u: URL) => Response = serveTrace) {
  const fn = vi.fn(async (input: RequestInfo | URL) => handler(new URL(String(input), "http://localhost")));
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("fetchTrace (fail closed)", () => {
  const from = CURSOR - 2000, to = CURSOR;
  const req = new URL(`http://x/?from=${new Date(from).toISOString()}&to=${new Date(to).toISOString()}`);

  it("accepts the real trace", async () => {
    mockTrace();
    const tr = await fetchTrace(SID, DRIVER_A, from, to, TRACK_ID);
    expect(tr.samples.length).toBeGreaterThan(0);
  });

  it.each([
    ["another driver", (b: Record<string, unknown>) => { b.driver_number = 1; }],
    ["another track", (b: Record<string, unknown>) => { b.track_id = "trk1_other"; }],
    ["another session", (b: Record<string, unknown>) => { b.session_id = "openf1:9161"; }],
    ["another window", (b: Record<string, unknown>) => { b.from_ts = new Date(from - 1000).toISOString(); }],
  ])("refuses %s", async (_n, tamper) => {
    const body = await serveTrace(req).json();
    tamper(body);
    mockTrace(() => json(body, 200, { "X-Spatial-Contract": "spatial_trace_v1" }));
    await expect(fetchTrace(SID, DRIVER_A, from, to, TRACK_ID)).rejects.toMatchObject({ kind: "unsupported" });
  });
});

describe("useGhost", () => {
  beforeEach(() => vi.useFakeTimers());
  const wait = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
  type P = { sid: string; driver: number | null; hovered: number | null; trackId: string | null };
  const mount = (p: Partial<P>) => renderHook((q: P) => useGhost(q), {
    initialProps: { sid: SID, driver: DRIVER_A, hovered: null, trackId: TRACK_ID, ...p } as P });

  it("sits at the driver's own location sample at or before the hovered time", async () => {
    const f = mockTrace();
    const tau = samples().speed.filter((s) => s.t <= CURSOR).at(-7)!.t;
    const h = mount({ hovered: tau });
    await wait(120);
    const own = trace().samples.filter((s) => Date.parse(s.ts) <= tau).at(-1)!;
    expect(h.result.current.status).toBe("ready");
    expect(h.result.current.ghost).toEqual({ driver: DRIVER_A, hovered: tau, at: Date.parse(own.ts),
                                              x: own.x, y: own.y });
    expect(Date.parse(own.ts)).toBeGreaterThanOrEqual(tau - 2000);
    const q = new URL(String(f.mock.calls[0][0]), "http://localhost").searchParams;
    expect(Date.parse(q.get("from")!)).toBe(tau - 2000);
    expect(Date.parse(q.get("to")!)).toBe(tau);
  });

  it("shows no ghost when no location sample lies within 2 s", async () => {
    // transport scaffolding: the real trace document with no sample in the requested 2 s
    mockTrace((u) => json({ ...trace(), from_ts: u.searchParams.get("from"), to_ts: u.searchParams.get("to"),
                            samples: [] }, 200, { "X-Spatial-Contract": "spatial_trace_v1" }));
    const h = mount({ hovered: CURSOR });
    await wait(120);
    expect(h.result.current.ghost).toBeNull();
    expect(h.result.current.status).toBe("none");
  });

  it("no hover, no driver or no validated track: no request", async () => {
    const f = mockTrace();
    mount({ hovered: null });
    mount({ driver: null, hovered: CURSOR });
    const noTrack = mount({ trackId: null, hovered: CURSOR });
    await wait(500);
    expect(f).not.toHaveBeenCalled();
    expect(noTrack.result.current.status).toBe("unavailable");
  });
});
