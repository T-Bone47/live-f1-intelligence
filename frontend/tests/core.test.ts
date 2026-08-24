import { describe, expect, it } from "vitest";
import { fmtGap, fmtSec, sectorStyle } from "../src/logic/format";
import { applyDelta, applyRemovals } from "../src/ws/socket";

/** Data-layer + formatting contracts. Component visuals are verified via the
 *  dev server (`npm run dev`) against the realtime backend; TypeScript strict
 *  mode (`npm run build`) guards component integrity. */

describe("format helpers", () => {
  it("renders symbolic gaps verbatim", () => {
    expect(fmtGap({ gap_to_leader_raw: "+1 LAP" })).toBe("+1 LAP");
  });

  it("never fabricates zero for missing data", () => {
    expect(fmtGap({})).toBe("—");
    expect(fmtSec(null)).toBe("—");
    expect(fmtSec(undefined)).toBe("—");
  });

  it("formats numeric gaps", () => {
    expect(fmtGap({ gap_to_leader_s: 1.5 })).toBe("+1.500");
    expect(fmtSec(74.25)).toBe("74.250");
  });

  it("sector style pairs color with text label (a11y)", () => {
    expect(sectorStyle("PURPLE").label).toBe("SESSION BEST");
    expect(sectorStyle("GREEN").label).toBe("PERSONAL BEST");
    expect(sectorStyle("YELLOW").label).toBe("SLOWER");
    expect(sectorStyle(undefined).label).toBe("—");
  });
});

describe("delta application", () => {
  const st: any = { snapshot: {} };

  it("sets nested dotted paths", () => {
    applyDelta(st, { "leaderboard.0.a": 2 });
    expect(st.snapshot.leaderboard[0].a).toBe(2);
  });

  it("creates intermediate objects for unknown paths", () => {
    applyDelta(st, { "weather.track_temp_c": 31.4 });
    expect(st.snapshot.weather.track_temp_c).toBe(31.4);
  });

  it("removes paths", () => {
    applyRemovals(st, ["weather.track_temp_c"]);
    expect(st.snapshot.weather.track_temp_c).toBeUndefined();
  });
});
