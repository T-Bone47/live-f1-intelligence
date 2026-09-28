/**
 * useSpatial (Phase 12B): the one cursor t selects the spatial state; the hook
 * never computes one. Paused: one exact ?at= request after a 120 ms debounce,
 * latest request wins. Playing: batched windows only. A session change clears
 * everything before anything new is shown. Real track golden, real states.
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { selectState, useSpatial } from "../../src/spatial/useSpatial";
import { calls, contractHeader, fixture, json, mockSpatial, SID, stateAt, track } from "./fixture";

beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const LAP10 = Date.parse(stateAt(1).at);
const LAP40 = Date.parse(stateAt(2).at);

/** Answers ?at= with the real fixture state at exactly that time, else 404. */
const byTime = (url: URL) => {
  const at = Date.parse(url.searchParams.get("at")!);
  const s = fixture().states_at.find((x) => Date.parse(x.at) === at);
  return s ? json(s, 200, contractHeader("spatial_state_v1")) : json({ detail: "no fixture state" }, 404);
};

type Props = { sid: string; t: number; playing: boolean; rate: number; live: boolean };
const base: Props = { sid: SID, t: LAP40, playing: false, rate: 16, live: false };

function mount(props: Partial<Props> = {}) {
  return renderHook((p: Props) => useSpatial(p), { initialProps: { ...base, ...props } });
}
const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });
const wait = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

describe("paused cursor", () => {
  it("debounces rapid cursor moves to one exact ?at request", async () => {
    const f = mockSpatial({ state: byTime });
    const h = mount({ t: LAP40 - 4000 });
    await flush();
    for (const dt of [-3000, -2000, -1000, 0]) {
      h.rerender({ ...base, t: LAP40 + dt });
      await wait(50);
    }
    expect(calls(f, "/spatial")).toHaveLength(0);
    await wait(120);
    const at = calls(f, "/spatial");
    expect(at).toHaveLength(1);
    expect(Date.parse(at[0].searchParams.get("at")!)).toBe(LAP40);
    expect(h.result.current.status).toBe("ready");
    expect(h.result.current.shown?.at).toBe(LAP40);
    expect(h.result.current.shown?.drivers).toEqual(stateAt(2).drivers);
    expect(h.result.current.lagging).toBe(false);
  });

  it("an old response arriving late never replaces the newer one", async () => {
    let release!: () => void;
    const late = new Promise<void>((r) => { release = r; });
    mockSpatial({
      state: async (url) => {
        if (Date.parse(url.searchParams.get("at")!) === LAP10) await late;
        return byTime(url);
      },
    });
    const h = mount({ t: LAP10 });
    await flush();
    await wait(120);                                   // LAP 10 requested, held back
    h.rerender({ ...base, t: LAP40 });
    await wait(120);                                   // LAP 40 answered
    expect(h.result.current.shown?.at).toBe(LAP40);
    release();
    await flush();
    expect(h.result.current.shown?.at).toBe(LAP40);
  });

  it("says when the shown positions trail the cursor", async () => {
    mockSpatial({ state: byTime });
    const h = mount();
    await flush();
    await wait(120);
    expect(h.result.current.lagging).toBe(false);
    h.rerender({ ...base, t: LAP40 + 5000 });
    expect(h.result.current.lagging).toBe(true);
    expect(h.result.current.shown?.at).toBe(LAP40);    // never moved by the browser
  });
});

describe("sessions and availability", () => {
  it("a session change clears the map before the new track arrives", async () => {
    mockSpatial({
      state: byTime,
      track: () => new Promise<Response>(() => {}),     // the new session never answers
    });
    const f = vi.mocked(fetch);
    f.mockImplementationOnce(async () => json(track(), 200, contractHeader("track_reference_v1")));
    const h = mount();
    await flush();
    await wait(120);
    expect(h.result.current.track?.track_id).toBe(track().track_id);
    expect(h.result.current.shown).not.toBeNull();
    h.rerender({ ...base, sid: "openf1:9999" });
    expect(h.result.current.track).toBeNull();
    expect(h.result.current.shown).toBeNull();
    expect(h.result.current.status).toBe("loading");
  });

  it("asks for no state before the cursor exists (browser QA finding: a request at 1970)", async () => {
    const f = mockSpatial({ state: byTime });
    const h = renderHook((p: Omit<Props, "t"> & { t: number | null }) => useSpatial(p),
                         { initialProps: { ...base, t: null } });
    await flush();
    await wait(500);
    expect(calls(f, "/spatial")).toHaveLength(0);
    expect(h.result.current.shown).toBeNull();
    h.rerender({ ...base, t: LAP40 });
    await wait(120);
    expect(calls(f, "/spatial")).toHaveLength(1);
  });

  it("live sessions are unavailable without a request", async () => {
    const f = mockSpatial();
    const h = mount({ live: true });
    await flush();
    await wait(500);
    expect(f).not.toHaveBeenCalled();
    expect(h.result.current).toMatchObject({ status: "unavailable", reason: "RECORDING_ONLY", track: null });
  });

  it("an unvalidated track is unavailable with its reasons and asks for no state", async () => {
    const t = track();
    t.status = "UNVALIDATED";
    t.reference!.polyline = null;
    t.sectors = [];
    t.timing_lines.forEach((l) => Object.assign(l, { loop_fraction: null, distance_m: null, x: null, y: null }));
    t.validation.reasons = ["P95_ABOVE_THRESHOLD:S1"];
    const f = mockSpatial({ track: () => json(t, 200, contractHeader("track_reference_v1")) });
    const h = mount();
    await flush();
    await wait(500);
    expect(h.result.current).toMatchObject({ status: "unavailable", reason: "UNVALIDATED",
                                             reasons: ["P95_ABOVE_THRESHOLD:S1"] });
    expect(calls(f, "/spatial")).toHaveLength(0);
  });

  it("no recording is unavailable; a withheld state is an error that can be retried", async () => {
    mockSpatial({ track: () => json({ detail: "no recording for openf1:11353" }, 404) });
    const gone = mount();
    await flush();
    expect(gone.result.current).toMatchObject({ status: "unavailable", reason: "NO_RECORDING" });
    gone.unmount();

    let fail = true;
    const f = mockSpatial({ state: (url) => (fail ? json({ detail: "spatial output withheld" }, 500) : byTime(url)) });
    const h = mount();
    await flush();
    await wait(120);
    expect(h.result.current.status).toBe("error");
    expect(h.result.current.error?.kind).toBe("withheld");
    fail = false;
    act(() => h.result.current.retry());
    await flush();
    await wait(120);
    expect(h.result.current.status).toBe("ready");
    expect(calls(f, "/spatial").length).toBeGreaterThanOrEqual(2);
  });

  it("409 on a state is unavailable with the gate reasons", async () => {
    mockSpatial({ state: () => json({ detail: { message: "spatial geometry not validated for this session",
                                                 status: "UNVALIDATED", reasons: ["NO_CITED_LAP_LENGTH"] } }, 409) });
    const h = mount();
    await flush();
    await wait(120);
    expect(h.result.current).toMatchObject({ status: "unavailable", reason: "UNVALIDATED",
                                             reasons: ["NO_CITED_LAP_LENGTH"] });
  });
});

describe("playing", () => {
  it("uses window requests only, a few per minute of race time", async () => {
    const f = mockSpatial({ state: byTime });
    const h = mount({ playing: true, rate: 16 });
    await flush();
    for (let s = 0; s <= 60; s += 0.5) {
      h.rerender({ ...base, playing: true, rate: 16, t: LAP40 + s * 1000 });
      await flush();
    }
    expect(calls(f, "/spatial")).toHaveLength(0);
    const windows = calls(f, "/spatial/window");
    expect(windows.length).toBeGreaterThanOrEqual(1);
    expect(windows.length).toBeLessThanOrEqual(2);
    for (const w of windows) expect(w.searchParams.get("step")).toBe("2");
    const shown = h.result.current.shown!;
    expect(shown.at).toBeLessThanOrEqual(LAP40 + 60_000);
    expect(LAP40 + 60_000 - shown.at).toBeLessThan(2000);
  });
});

describe("starting playback (browser QA finding: the map stepped back 1.1 s on play)", () => {
  it("keeps the exact state until a window state is newer, never showing an older one", async () => {
    mockSpatial({ state: byTime });
    const h = mount();                                   // paused at the real LAP 40 state
    await flush();
    await wait(120);
    expect(h.result.current.shown?.at).toBe(LAP40);
    h.rerender({ ...base, playing: true, t: LAP40 });
    await flush();                                       // a 2 s window arrives, its latest state is older
    expect(h.result.current.shown?.at).toBe(LAP40);
    h.rerender({ ...base, playing: true, t: LAP40 + 2000 });
    await flush();
    const shown = h.result.current.shown!;
    expect(shown.at).toBeGreaterThan(LAP40);
    expect(shown.at).toBeLessThanOrEqual(LAP40 + 2000);
  });
});

describe("a slow window (mutation sweep)", () => {
  it("is not requested again while it is in flight", async () => {
    const f = mockSpatial({ state: byTime, window: () => new Promise<Response>(() => {}) });
    const h = mount({ playing: true, rate: 16 });
    await flush();
    for (let s = 0; s <= 10; s += 0.5) {
      h.rerender({ ...base, playing: true, rate: 16, t: LAP40 + s * 1000 });
      await flush();
    }
    expect(calls(f, "/spatial/window")).toHaveLength(1);
    expect(h.result.current.status).toBe("loading");
  });
});

describe("selectState (pure selection, real window)", () => {
  const w = fixture().window;
  const at = (i: number) => Date.parse(w.states[i].at);
  it("takes the state with the largest time at or before t, never one after it", () => {
    expect(selectState(w, at(3))!.at).toBe(at(3));
    expect(selectState(w, at(3) + 499)!.at).toBe(at(3));
    expect(selectState(w, at(0) - 1)).toBeNull();
    expect(selectState(w, at(20) + 100)!.at).toBe(at(20));
    expect(selectState(w, at(3))!.drivers).toBe(w.states[3].drivers);
  });
});
