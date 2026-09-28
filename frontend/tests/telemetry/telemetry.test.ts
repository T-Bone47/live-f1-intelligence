/**
 * Car telemetry at the cursor (Phase 12C): a fail-closed client for the RAW
 * telemetry route, pure selection (samples at or before t, runs split where
 * two samples are more than 2 s apart), and a window hook for the one cursor.
 * Real Dutch GP samples throughout; nothing is interpolated or filled.
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchTelemetryWindow } from "../../src/telemetry/api";
import { channelView, splitRuns, toSamples } from "../../src/telemetry/select";
import { MAX_GAP_MS } from "../../src/telemetry/types";
import { aheadForRate, TELEMETRY_BACK_MS, useTelemetryWindow } from "../../src/telemetry/useTelemetryWindow";
import { CURSOR, DRIVER_A, DRIVER_B, json, mockTelemetry, pair, requests, serveTelemetry, SID, SOURCE } from "./fixture";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const FROM = CURSOR - 60_000, TO = CURSOR + 60_000;

describe("fetchTelemetryWindow (fail closed)", () => {
  it("accepts the real window and says where it came from", async () => {
    const f = mockTelemetry();
    const w = await fetchTelemetryWindow(SID, DRIVER_A, FROM, TO);
    expect(w.dataSource).toBe("recording");
    expect(w.samples.speed).toHaveLength(pair().telemetry.series.speed!.length);
    const q = requests(f)[0].searchParams;
    expect(q.get("frequency")).toBe("RAW");
    expect(q.get("fields")).toBe("speed,throttle,brake,gear,rpm,drs");
    expect(Date.parse(q.get("start")!)).toBe(FROM);
  });

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tampered: [string, (doc: Record<string, any>) => void, Record<string, string>?][] = [
    ["another session", (d) => { d.session_id = "openf1:9161"; }],
    ["another driver", (d) => { d.driver_number = DRIVER_B; }],
    ["another window", (d) => { d.window.start = new Date(FROM + 1000).toISOString(); }],
    ["not RAW", (d) => { d.frequency = "MEDIUM"; }],
    ["samples out of order", (d) => { d.series.speed.reverse(); }],
    ["a value that is not a number", (d) => { d.series.speed[3].value = null; }],
    ["no data source", () => {}, {}],
    ["an unknown data source", () => {}, { "X-Data-Source": "cache" }],
  ];
  it.each(tampered)("refuses %s", async (_name, tamper, headers = SOURCE) => {
    mockTelemetry(async (u) => {
      const body = await serveTelemetry(u).json();
      tamper(body);
      return json(body, 200, headers);
    });
    await expect(fetchTelemetryWindow(SID, DRIVER_A, FROM, TO)).rejects.toMatchObject({ kind: "unsupported" });
  });

  it("keeps the backend's message on 404", async () => {
    mockTelemetry();
    await expect(fetchTelemetryWindow(SID, DRIVER_B, FROM, TO))
      .rejects.toMatchObject({ kind: "not_found", message: "no stored telemetry for this driver/session" });
  });
});

describe("selection", () => {
  const samples = () => toSamples(pair().telemetry.series.speed!);

  it("never includes a sample after the cursor", () => {
    const s = samples();
    const t = s[100].t + 1;
    const v = channelView(s, t - 30_000, t, true);
    const shown = v.runs.flat();
    expect(shown.every((p) => p.t <= t)).toBe(true);
    expect(shown.at(-1)).toEqual(s[100]);
    expect(v.latest).toEqual(s[100]);
  });

  it("marks the stretch from the last sample to the cursor when it exceeds 2 s (final review)", () => {
    const s = samples();
    const last = s[100];
    expect(channelView(s.slice(0, 101), last.t - 30_000, last.t + MAX_GAP_MS, true).trailing).toBeNull();
    expect(channelView(s.slice(0, 101), last.t - 30_000, last.t + MAX_GAP_MS + 1, true).trailing)
      .toEqual({ from: last.t, to: last.t + MAX_GAP_MS + 1 });
  });

  it("splits at gaps over 2 s, and only there", () => {
    const s = samples();
    const cut = [...s.slice(0, 50), ...s.slice(70)];     // real samples, 20 removed
    const { runs, gaps } = splitRuns(cut);
    expect(runs).toHaveLength(2);
    expect(gaps).toEqual([{ from: s[49].t, to: s[70].t }]);
    const exact = [{ t: 0, value: 1 }, { t: MAX_GAP_MS, value: 2 }];
    expect(splitRuns(exact).runs).toHaveLength(1);        // exactly 2 s is not a gap
    expect(splitRuns([...exact, { t: 2 * MAX_GAP_MS + 1, value: 3 }]).gaps).toHaveLength(1);
  });

  it("reports DRS unavailable when every sample in the window is null", async () => {
    mockTelemetry();
    const w = await fetchTelemetryWindow(SID, DRIVER_A, FROM, TO);
    expect(w.samples.drs).toEqual([]);
    expect(w.available.drs).toBe(false);
    expect(w.available.speed && w.available.throttle && w.available.gear).toBe(true);
  });

  it("keeps nulls out of the series (never zero)", async () => {
    const doc = pair().telemetry;
    const gone = doc.series.speed![10].ts;
    doc.series.speed!.splice(10, 1);                     // the route omits a null sample
    mockTelemetry(async () => json({ ...doc, window: { start: new Date(FROM).toISOString(),
                                                       end: new Date(TO).toISOString() } }, 200, SOURCE));
    const w = await fetchTelemetryWindow(SID, DRIVER_A, FROM, TO);
    expect(w.samples.speed.find((p) => p.t === Date.parse(gone))).toBeUndefined();
    expect(w.samples.throttle.find((p) => p.t === Date.parse(gone))).toBeDefined();
    expect(w.samples.speed).toHaveLength(doc.series.speed!.length);
  });
});

type Props = { sid: string; driver: number | null; t: number | null; playing: boolean; rate: number; live: boolean };
const base: Props = { sid: SID, driver: DRIVER_A, t: CURSOR, playing: false, rate: 1, live: false };
const mount = (p: Partial<Props> = {}) =>
  renderHook((q: Props) => useTelemetryWindow(q), { initialProps: { ...base, ...p } });
const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });
const wait = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

describe("useTelemetryWindow", () => {
  beforeEach(() => vi.useFakeTimers());

  it("debounces rapid cursor moves to one request", async () => {
    const f = mockTelemetry();
    const h = mount({ t: CURSOR - 20_000 });
    for (const dt of [-15_000, -10_000, -5_000, 0]) {
      h.rerender({ ...base, t: CURSOR + dt });
      await wait(50);
    }
    expect(f).not.toHaveBeenCalled();
    await wait(120);
    expect(f).toHaveBeenCalledTimes(1);
    const q = requests(f)[0].searchParams;
    expect(Date.parse(q.get("start")!)).toBe(CURSOR - TELEMETRY_BACK_MS);
    expect(Date.parse(q.get("end")!)).toBe(CURSOR + aheadForRate(1));
    expect(h.result.current.status).toBe("ready");
    expect(h.result.current.dataSource).toBe("recording");
  });

  it("never draws a sample after the cursor after seeking back", async () => {
    mockTelemetry();
    const h = mount();
    await wait(120);
    expect(h.result.current.status).toBe("ready");
    const back = CURSOR - 20_000;
    h.rerender({ ...base, t: back });
    const check = () => {
      const v = h.result.current.view;
      if (!v) return;
      for (const ch of Object.values(v.channels)) {
        expect(ch.runs.flat().every((p) => p.t <= back)).toBe(true);
        if (ch.latest) expect(ch.latest.t).toBeLessThanOrEqual(back);
      }
      expect(v.to).toBe(back);
    };
    check();                                   // the old window, before the refetch
    await wait(120);
    check();                                   // the new window
    expect(h.result.current.view!.channels.speed.runs.flat().length).toBeGreaterThan(0);
  });

  it("drops a late window for a previous driver", async () => {
    let release!: () => void;
    const held = new Promise<void>((r) => { release = r; });
    mockTelemetry(async (u) => {
      if (u.pathname.endsWith(`/${DRIVER_A}`)) await held;
      return serveTelemetry(u);
    });
    const h = mount();
    await wait(120);                           // driver A requested, held back
    h.rerender({ ...base, driver: DRIVER_B });
    await wait(120);                           // driver B answered: no telemetry (404)
    release();
    await flush();
    expect(h.result.current.view).toBeNull();
    expect(h.result.current.status).toBe("unavailable");
  });

  it("after a driver change nothing of the previous driver is shown (mutation sweep)", async () => {
    let release!: () => void;
    const held = new Promise<void>((r) => { release = r; });
    mockTelemetry(async (u) => {
      if (u.pathname.endsWith(`/${DRIVER_B}`)) await held;
      return serveTelemetry(u);
    });
    const h = mount();
    await wait(120);
    expect(h.result.current.status).toBe("ready");      // driver A's window has landed
    h.rerender({ ...base, driver: DRIVER_B });
    await wait(120);                                     // driver B requested, not answered yet
    expect(h.result.current.view).toBeNull();
    expect(h.result.current.status).toBe("loading");
    release();
  });

  it("while playing, fetches ahead without a request per tick", async () => {
    const f = mockTelemetry();
    const h = mount({ playing: true, rate: 16, t: CURSOR - 50_000 });
    await flush();
    expect(f).toHaveBeenCalledTimes(1);
    expect(Date.parse(requests(f)[0].searchParams.get("end")!)).toBe(CURSOR - 50_000 + aheadForRate(16));
    for (let k = 1; k <= 30; k += 1) {           // 30 ticks, 1.6 s of race each
      h.rerender({ ...base, playing: true, rate: 16, t: CURSOR - 50_000 + k * 1600 });
      await flush();
    }
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("a failed window stops requests until retry", async () => {
    const f = mockTelemetry(async () => json({ detail: "boom" }, 500));
    const h = mount();
    await wait(120);
    expect(h.result.current.status).toBe("error");
    h.rerender({ ...base, t: CURSOR - 30_000 });
    await wait(500);
    expect(f).toHaveBeenCalledTimes(1);
    act(() => h.result.current.retry());
    await wait(120);
    expect(f).toHaveBeenCalledTimes(2);
  });

  it("no driver: idle, no request; live: unavailable, no request", async () => {
    const f = mockTelemetry();
    const idle = mount({ driver: null });
    const live = mount({ live: true });
    await wait(500);
    expect(idle.result.current.status).toBe("idle");
    expect(live.result.current.status).toBe("unavailable");
    expect(live.result.current.reason).toBe("LIVE");
    expect(f).not.toHaveBeenCalled();
  });
});
