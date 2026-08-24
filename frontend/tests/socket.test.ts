import { describe, expect, it } from "vitest";
import { SessionSocket, applyDelta, applyRemovals } from "../src/ws/socket";

function makeState() {
  const s = new SessionSocket("ws://test", "openf1:test");
  (s as any).state.snapshot = {
    leaderboard: [{ position: 1, driver_number: 16, last_lap_s: 74.5 }],
    weather: { air_temp_c: 19.0 },
    recent_events: [],
  };
  (s as any).state.seq = 10;
  return s;
}

describe("delta application", () => {
  it("sets nested dotted paths", () => {
    const st: any = { snapshot: { leaderboard: [{ a: 1 }] } };
    applyDelta(st, { "leaderboard.0.a": 2 });
    expect(st.snapshot.leaderboard[0].a).toBe(2);
  });

  it("creates intermediate objects for unknown paths", () => {
    const st: any = { snapshot: {} };
    applyDelta(st, { "weather.track_temp_c": 31.4 });
    expect(st.snapshot.weather.track_temp_c).toBe(31.4);
  });

  it("removes paths", () => {
    const st: any = { snapshot: { battles: { "1v2": {} } } };
    applyRemovals(st, ["battles.1v2"]);
    expect(st.snapshot.battles["1v2"]).toBeUndefined();
  });
});

describe("sequence handling", () => {
  it("accepts exactly-next sequence", () => {
    const s = makeState();
    s.handleMessage({
      kind: "delta", seq: 11,
      changes: { "weather.air_temp_c": 20 },
      removed: [], ts: "2026-08-23T15:00:00+00:00",
    });
    expect(s.getState().seq).toBe(11);
    expect(s.getState().snapshot.weather.air_temp_c).toBe(20);
  });

  it("ignores duplicate/stale sequences", () => {
    const s = makeState();
    s.handleMessage({ kind: "delta", seq: 9, changes: { "a.b": 1 }, removed: [] });
    s.handleMessage({ kind: "delta", seq: 10, changes: { "a.b": 1 }, removed: [] });
    expect(s.getState().seq).toBe(10);
    expect((s.getState().snapshot as any).a).toBeUndefined();
  });

  it("requests resume on gap without applying stale deltas", () => {
    const s = makeState();
    let sent: any = null;
    (s as any).send = (m: any) => { sent = m; };
    s.handleMessage({ kind: "delta", seq: 15, changes: { "x.y": 1 }, removed: [] });
    expect(sent.action).toBe("resume");
    expect(sent.last_seq).toBe(10);
    expect(s.getState().seq).toBe(10); // nothing applied until resync
  });
});

describe("mode detection", () => {
  it("marks replay sessions from id prefix", () => {
    const s = new SessionSocket("ws://t", "replay:x");
    s.handleMessage({
      kind: "snapshot", seq: 1, session_id: "replay:x",
      data: { session_id: "replay:x" }, ts: "2026-08-23T15:00:00+00:00",
    });
    expect(s.getState().status).toBe("REPLAY");
  });

  it("marks live sessions otherwise", () => {
    const s = new SessionSocket("ws://t", "openf1:x");
    s.handleMessage({
      kind: "snapshot", seq: 1, session_id: "openf1:x",
      data: {}, ts: "2026-08-23T15:00:00+00:00",
    });
    expect(s.getState().status).toBe("LIVE");
  });
});

describe("telemetry + events frames", () => {
  it("stores latest telemetry per driver", () => {
    const s = makeState();
    s.handleMessage({ kind: "telemetry", driver: 16, samples: [{ speed_kph: 280 }] });
    s.handleMessage({ kind: "telemetry", driver: 16, samples: [{ speed_kph: 300 }] });
    expect(s.getState().telemetry[16].speed_kph).toBe(300);
  });

  it("appends only unseen significant events", () => {
    const s = makeState();
    const ev = { event_key: "s|OVERTAKE|12v4|L22", event_type: "OVERTAKE" };
    s.handleMessage({ kind: "events", critical: true, events: [ev] });
    s.handleMessage({ kind: "events", critical: true, events: [ev] });
    expect(s.getState().recentEvents.filter((e) => e.event_type === "OVERTAKE")).toHaveLength(1);
  });
});
