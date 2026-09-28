/**
 * Command-center model on the REAL golden timeline: the one session moment,
 * URL tokens, pair intervals, formatting, fail-closed contract checks and the
 * replay reducer. No value is derived here - these tests prove selection only.
 */

import { describe, expect, it } from "vitest";
import { ApiError, checkTimeline } from "../../src/command/api";
import { compoundInfo, fmtGap, fmtInterval, fmtLapTime, fmtSigned, fmtTemp, fmtWindKmh } from "../../src/command/format";
import {
  buildMoment, frameIndexAt, frameTimes, indexForLapToken, knownTime, lapTokenForIndex,
  pairIntervalHistory, positionHistory,
} from "../../src/command/moment";
import { fmtAsOf, fmtClockTenths } from "../../src/command/format";
import { initialUi, parseUrlTime, readUrl, TICK_CAP_MS, uiReducer, writeUrl } from "../../src/command/state";
import { frameIndex, golden, SID } from "./fixture";

describe("one session moment", () => {
  const t = golden();

  it("orders rows by the backend position and exposes the frame as-is", () => {
    const i = frameIndex(t, 30);
    const m = buildMoment(t, i);
    expect(m.frame).toBe(t.frames[i]);
    expect(m.lap).toBe(30);
    expect(m.rows.map((r) => r.position)).toEqual([...m.rows.map((r) => r.position)].sort((a, b) => (a ?? 99) - (b ?? 99)));
    expect(m.rows.length).toBe(t.frames[i].rows.length);
  });

  it("lists only facts the backend says were known at the frame", () => {
    for (const lap of [10, 20, 30]) {
      const i = frameIndex(t, lap);
      const m = buildMoment(t, i);
      expect(m.pits.every((p) => p.frame_index <= i)).toBe(true);
      expect(m.raceControl.length).toBe(t.race_control.filter((r) => r.frame_index <= i).length);
      expect(m.weather.length).toBe(t.weather.filter((w) => w.frame_index <= i).length);
      expect(m.events.every((e) => e.frame_index <= i)).toBe(true);
    }
  });

  it("shows each driver's stints only up to the row's current stint, open at the cursor", () => {
    const i = frameIndex(t, 30);
    const m = buildMoment(t, i);
    for (const r of m.rows) {
      const visible = m.stints.get(r.driver_number) ?? [];
      expect(visible.every((s) => s.stint_number <= (r.stint_number ?? 0))).toBe(true);
      const current = visible.find((s) => s.current);
      if (current) expect(current.drawEnd).toBe(r.lap_number);
    }
  });

  it("round-trips URL lap tokens", () => {
    expect(indexForLapToken(t, "start")).toBe(0);
    expect(indexForLapToken(t, "final")).toBe(t.frames.length - 1);
    const i = frameIndex(t, 42);
    expect(indexForLapToken(t, "42")).toBe(i);
    expect(lapTokenForIndex(t, i)).toBe("42");
    expect(indexForLapToken(t, "999")).toBeNull();
  });

  it("position history is the frames' own positions, null when not reported", () => {
    const h = positionHistory(t, 5);
    for (const [num, series] of h) {
      series.forEach((p, i) => {
        const row = t.frames[i].rows.find((r) => r.driver_number === num);
        expect(p).toBe(row?.position ?? null);
      });
    }
  });

  it("pair interval is the behind car's own interval, only while they are neighbours", () => {
    const f = t.frames[frameIndex(t, 40)];
    const b = f.active_battles[0];
    const hist = pairIntervalHistory(t, b.ahead, b.behind, frameIndex(t, 40));
    for (const p of hist) {
      const fr = t.frames[p.index];
      const a = fr.rows.find((r) => r.driver_number === b.ahead)!;
      const z = fr.rows.find((r) => r.driver_number === b.behind)!;
      const adj = a.position != null && z.position === a.position + 1;
      expect(p.adjacent).toBe(adj);
      expect(p.interval).toBe(adj ? z.interval_s : null);
    }
  });
});

describe("formatting never invents a value", () => {
  it("renders missing values as a dash, never null/NaN/0", () => {
    for (const f of [fmtLapTime, fmtSigned, fmtTemp, fmtWindKmh]) {
      expect(f(null)).toBe("—");
      expect(f(undefined)).toBe("—");
      expect(f(Number.NaN)).toBe("—");
      expect(f(Number.POSITIVE_INFINITY)).toBe("—");
    }
  });
  it("keeps symbolic gaps verbatim and names the leader", () => {
    expect(fmtGap({ position: 8, gap_to_leader_s: null, gap_to_leader_raw: "+1 LAP" })).toBe("+1 LAP");
    expect(fmtGap({ position: 1, gap_to_leader_s: 0, gap_to_leader_raw: null })).toBe("LEADER");
    expect(fmtGap({ position: 2, gap_to_leader_s: 11.536, gap_to_leader_raw: null })).toBe("+11.536");
    expect(fmtInterval({ position: 1, interval_s: 0 })).toBe("—");
  });
  it("formats lap times and labels unknown compounds", () => {
    expect(fmtLapTime(74.23)).toBe("1:14.230");
    expect(compoundInfo(null).label).toBe("UNKNOWN");
    expect(compoundInfo("HARD").label).toBe("HARD");
  });
});

describe("the timeline contract fails closed", () => {
  it("accepts the real golden for its own session", () => {
    expect(checkTimeline(golden(), SID).frames.length).toBe(golden().frames.length);
  });
  it.each([
    ["another contract", (t: ReturnType<typeof golden>) => { (t as { contract_version: string }).contract_version = "x"; }],
    ["another session", (t: ReturnType<typeof golden>) => { t.session!.session_id = "openf1:1"; }],
    ["a frame out of order", (t: ReturnType<typeof golden>) => { t.frames[3].index = 7; }],
    ["no race-control list", (t: ReturnType<typeof golden>) => { (t as unknown as Record<string, unknown>).race_control = null; }],
    ["a frame time that goes backwards", (t: ReturnType<typeof golden>) => { t.frames[5].at = t.frames[2].at; }],
  ])("refuses %s", (_name, mutate) => {
    const t = golden();
    mutate(t);
    expect(() => checkTimeline(t, SID)).toThrow(ApiError);
  });
});

describe("race-time cursor (Phase 12B)", () => {
  const t = golden();
  const frames = frameTimes(t);
  const last = frames.length - 1;
  const base = initialUi({ frames, t: frames[0], rate: 16 });

  it("frame times are the frames' own at, in order", () => {
    expect(frames).toHaveLength(t.frames.length);
    frames.forEach((ms, i) => expect(ms).toBe(Date.parse(t.frames[i].at!)));
  });

  it("frameIndexAt picks the last frame at or before t", () => {
    expect(frameIndexAt(frames, frames[5])).toBe(5);
    expect(frameIndexAt(frames, frames[5] + 1)).toBe(5);
    expect(frameIndexAt(frames, frames[6] - 1)).toBe(5);
    expect(frameIndexAt(frames, frames[0] - 1000)).toBe(0);
    expect(frameIndexAt(frames, frames[last] + 5000)).toBe(last);
  });

  it("tick advances race time at the rate and stops at the end", () => {
    let s = uiReducer({ ...base, t: frames[10], playing: true }, { type: "tick", wallMs: 100 });
    expect(s.t).toBe(frames[10] + 1600);
    s = uiReducer({ ...base, t: frames[last] - 100, rate: 4, playing: true }, { type: "tick", wallMs: 100 });
    expect(s).toMatchObject({ t: frames[last], playing: false });
    expect(uiReducer(s, { type: "tick", wallMs: 100 }).t).toBe(frames[last]);
  });

  it("a hidden-tab tick is capped", () => {
    const s = uiReducer({ ...base, t: frames[10], playing: true }, { type: "tick", wallMs: 5000 });
    expect(TICK_CAP_MS).toBe(250);
    expect(s.t).toBe(frames[10] + 4000);
  });

  it("a tick while paused changes nothing", () => {
    const s = { ...base, t: frames[10] };
    expect(uiReducer(s, { type: "tick", wallMs: 100 })).toBe(s);
  });

  it("step back from mid-lap goes to the lap's own frame first", () => {
    const mid = frames[20] + 30_000;
    expect(mid).toBeLessThan(frames[21]);
    let s = uiReducer({ ...base, t: mid, playing: true }, { type: "step", by: -1 });
    expect(s).toMatchObject({ t: frames[20], playing: false });
    s = uiReducer(s, { type: "step", by: -1 });
    expect(s.t).toBe(frames[19]);
    expect(uiReducer({ ...base, t: mid }, { type: "step", by: 1 }).t).toBe(frames[21]);
    expect(uiReducer({ ...base, t: frames[0] }, { type: "step", by: -1 }).t).toBe(frames[0]);
  });

  it("play from the end restarts; seeks clamp and pause", () => {
    expect(uiReducer({ ...base, t: frames[last] }, { type: "play" })).toMatchObject({ t: frames[0], playing: true });
    expect(uiReducer({ ...base, playing: true }, { type: "seekTime", t: 1e15 })).toMatchObject({ t: frames[last], playing: false });
    expect(uiReducer(base, { type: "seekTime", t: 0 }).t).toBe(frames[0]);
    expect(uiReducer(base, { type: "seekFrame", index: 12 }).t).toBe(frames[12]);
    expect(uiReducer(base, { type: "seekFrame", index: 999 }).t).toBe(frames[last]);
  });

  it("nudge moves race time by milliseconds within the bounds", () => {
    expect(uiReducer({ ...base, t: frames[20] }, { type: "nudge", ms: 10_000 }).t).toBe(frames[20] + 10_000);
    expect(uiReducer({ ...base, t: frames[0] }, { type: "nudge", ms: -10_000 }).t).toBe(frames[0]);
  });

  it("selecting an event with a time moves the cursor there", () => {
    expect(uiReducer(base, { type: "event", key: "k", t: frames[12] + 5 })).toMatchObject({ t: frames[12] + 5, rcKey: "k" });
    expect(uiReducer(base, { type: "event", key: "k" }).t).toBe(base.t);
  });

  it("lists include items timestamped at or before t between frames", () => {
    const m = t.race_control.find((x) => x.frame_index > 1 && Date.parse(x.ts!) > frames[x.frame_index - 1])!;
    const at = Date.parse(m.ts!);
    const i = frameIndexAt(frames, at);
    expect(i).toBe(m.frame_index - 1);
    expect(buildMoment(t, i, at).raceControl).toContain(m);
    expect(buildMoment(t, i).raceControl).not.toContain(m);
    expect(buildMoment(t, i, at).raceControl.length)
      .toBe(t.race_control.filter((x) => Date.parse(x.ts!) <= at).length);
  });

  it("events stay on the engine's frame_index (their own timestamp can precede it)", () => {
    const e = t.events.find((x) => x.frame_index > 0 && Date.parse(x.timestamp) <= frames[x.frame_index - 1])!;
    expect(e).toBeDefined();
    const i = e.frame_index - 1;
    expect(buildMoment(t, i, frames[i + 1] - 1).events).not.toContain(e);
  });

  it("knownTime changes only when the known content does", () => {
    const i = 30;
    const a = knownTime(t, i, frames[i] + 1);
    expect(knownTime(t, i, frames[i] + 2)).toBe(a);
    const stamps = [...t.race_control, ...t.pit_stops, ...t.weather].map((x) => Date.parse(x.ts!));
    const next = Math.min(...stamps.filter((ms) => ms > frames[i]));
    expect(knownTime(t, i, next)).toBe(next);
    expect(buildMoment(t, i, knownTime(t, i, next + 1)).raceControl)
      .toEqual(buildMoment(t, i, next + 1).raceControl);
  });

  it("formats the cursor clock to tenths and the frame a panel shows", () => {
    expect(fmtClockTenths(Date.parse("2026-08-23T13:41:02.567Z"))).toBe("13:41:02.5 UTC");
    expect(fmtClockTenths(Number.NaN)).toBe("—");
    expect(fmtAsOf(t.frames[frameIndexAtLap(t, 40)])).toMatch(/^as of LAP 40 · \d\d:\d\d:\d\d$/);
  });

  it("the URL carries t only between frames; a bad or out-of-range t is ignored", () => {
    const iso = new Date(frames[20] + 1500).toISOString();
    expect(writeUrl({ session: SID, lap: "20", t: iso, driver: null })).toContain("t=");
    expect(readUrl(`?session=x&t=${encodeURIComponent(iso)}`).t).toBe(iso);
    expect(parseUrlTime(iso, frames)).toBe(frames[20] + 1500);
    expect(parseUrlTime("garbage", frames)).toBeNull();
    expect(parseUrlTime("2020-01-01T00:00:00Z", frames)).toBeNull();
    expect(parseUrlTime("2026-08-23T13:41:02", frames)).toBeNull();     // no offset
    expect(parseUrlTime(null, frames)).toBeNull();
  });
});

function frameIndexAtLap(t: ReturnType<typeof golden>, lap: number) {
  return t.frames.findIndex((f) => f.kind === "LAP" && f.lap === lap);
}

describe("final review fixes (Phase 12B)", () => {
  const t = golden();
  const frames = frameTimes(t);

  it("race time stays in whole milliseconds, even after fractional playback ticks (review #1)", () => {
    let s = initialUi({ frames, t: frames[10], rate: 16, playing: true });
    for (let i = 0; i < 30; i += 1) s = uiReducer(s, { type: "tick", wallMs: 16.7 });
    expect(Number.isInteger(s.t)).toBe(true);
    expect(Number.isInteger(uiReducer(s, { type: "seekTime", t: frames[20] + 0.3 }).t)).toBe(true);
    expect(Number.isInteger(uiReducer(s, { type: "nudge", ms: 0.6 }).t)).toBe(true);
  });

  it("a frame without a time opens and is never shown at a guessed time (review #8)", () => {
    const u = golden();
    u.frames[5].at = null;
    u.frames[u.frames.length - 1].at = null;
    expect(() => checkTimeline(u, SID)).not.toThrow();
    const ms = frameTimes(u);
    const last = ms.length - 1;
    expect(ms.every((x) => Number.isFinite(x))).toBe(true);
    expect(ms[5]).toBe(ms[6]);                       // hidden behind the next timed frame
    expect(frameIndexAt(ms, ms[5])).toBe(6);
    expect(ms[last]).toBe(ms[last - 1]);             // the newest frame stays reachable at the end
    expect(frameIndexAt(ms, ms[last])).toBe(last);
  });

  it("a frame time that is not a time is still refused", () => {
    const u = golden();
    u.frames[5].at = "lap five";
    expect(() => checkTimeline(u, SID)).toThrow(ApiError);
  });
});
