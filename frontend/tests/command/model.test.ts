/**
 * Command-center model on the REAL golden timeline: the one session moment,
 * URL tokens, pair intervals, formatting, fail-closed contract checks and the
 * replay reducer. No value is derived here - these tests prove selection only.
 */

import { describe, expect, it } from "vitest";
import { ApiError, checkTimeline } from "../../src/command/api";
import { compoundInfo, fmtGap, fmtInterval, fmtLapTime, fmtSigned, fmtTemp, fmtWindKmh } from "../../src/command/format";
import {
  buildMoment, indexForLapToken, lapTokenForIndex, pairIntervalHistory, positionHistory,
} from "../../src/command/moment";
import { initialUi, uiReducer } from "../../src/command/state";
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
  ])("refuses %s", (_name, mutate) => {
    const t = golden();
    mutate(t);
    expect(() => checkTimeline(t, SID)).toThrow(ApiError);
  });
});

describe("replay reducer", () => {
  const base = initialUi({ last: 73, index: 0 });
  it("ticks forward and stops at the end", () => {
    let s = uiReducer({ ...base, index: 72, playing: true }, { type: "tick" });
    expect(s.index).toBe(73);
    expect(s.playing).toBe(false);
    s = uiReducer(s, { type: "tick" });
    expect(s.index).toBe(73);
  });
  it("play from the end restarts at the beginning; seek clamps and pauses", () => {
    expect(uiReducer({ ...base, index: 73 }, { type: "play" })).toMatchObject({ index: 0, playing: true });
    expect(uiReducer({ ...base, playing: true }, { type: "seek", index: 500 })).toMatchObject({ index: 73, playing: false });
    expect(uiReducer(base, { type: "step", by: -1 }).index).toBe(0);
  });
  it("selecting an event moves the cursor to its frame", () => {
    expect(uiReducer(base, { type: "event", key: "k", index: 12 })).toMatchObject({ index: 12, rcKey: "k" });
  });
});
