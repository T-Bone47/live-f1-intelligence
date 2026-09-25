import { describe, expect, it } from "vitest";
import {
  UNAVAILABLE, aheadOf, changeFavours, fmtBand, fmtDelta, fmtKph, fmtLapTime, fmtMetres,
  fmtPct, fmtX, offsetPhrase,
} from "../../src/evidence/format";
import { STATUS_TEXT, LIMITATION_TITLE, LIMITATION_CONSEQUENCE, DIRECTION_DETAIL } from "../../src/evidence/vocabulary";

const BAD = [null, undefined, NaN, Infinity, -Infinity];

describe("formatters never render null, NaN, Infinity or undefined", () => {
  it.each([fmtDelta, fmtBand, fmtLapTime, fmtX, fmtKph, fmtPct])("%o", (f) => {
    for (const v of BAD) expect(f(v as number)).toBe(UNAVAILABLE);
  });
  it("metres too", () => {
    for (const v of BAD) expect(fmtMetres(v as number, true)).toBe(UNAVAILABLE);
  });
});

describe("sign convention: delta_t = elapsed_A - elapsed_B, negative means A ahead", () => {
  it("formats signs explicitly with a typographic minus", () => {
    expect(fmtDelta(-0.07200000000000273)).toBe("−0.072 s");
    expect(fmtDelta(0.08407756334359817)).toBe("+0.084 s");
    expect(fmtDelta(-0.0004)).toBe("0.000 s");
  });
  it("names who is ahead from the sign, never flips it", () => {
    expect(aheadOf(-0.072, 55, 63)).toBe("#55 ahead");
    expect(aheadOf(0.084, 55, 63)).toBe("#63 ahead");
    expect(aheadOf(0, 55, 63)).toBe("level");
    expect(aheadOf(null, 55, 63)).toBeNull();
  });
  it("a negative change favours A, a positive change favours B", () => {
    expect(changeFavours(-0.066, 55, 63)).toBe("favours #55");
    expect(changeFavours(0.083, 55, 63)).toBe("favours #63");
  });
  it("offsets follow the contract rule A - B along the lap (positive = A later)", () => {
    expect(offsetPhrase(31.81833333333349, 55, "brake onset", true)).toBe("#55 brake onset 31.8 m later (norm.)");
    expect(offsetPhrase(-29.6, 55, "brake onset", true)).toBe("#55 brake onset 29.6 m earlier (norm.)");
    expect(offsetPhrase(null, 55, "brake onset", true)).toBe("brake onset: not comparable");
  });
});

describe("metre labels say 'norm.' when the distance is normalized", () => {
  it("normalized vs physical", () => {
    expect(fmtMetres(2875.08, true)).toBe("2,875 m norm.");
    expect(fmtMetres(4940, false)).toBe("4,940 m");
  });
});

describe("vocabulary never states a cause", () => {
  const CAUSAL = /\b(because|caused|causes|cause of|due to|better|worse|mistake|faster through|too late|too early|should have)\b/i;
  const texts = [
    ...Object.values(STATUS_TEXT).flatMap((t) => [t.label, t.detail]),
    ...Object.values(LIMITATION_TITLE), ...Object.values(LIMITATION_CONSEQUENCE), ...Object.values(DIRECTION_DETAIL),
  ];
  it.each(texts)("%s", (t) => { expect(t).not.toMatch(CAUSAL); });
});
