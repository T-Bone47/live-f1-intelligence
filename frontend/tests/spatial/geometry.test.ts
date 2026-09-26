/**
 * Map rendering geometry (Phase 12B): pixels only. The fit keeps the feed
 * frame's shape (one scale for x and y), draws feed y upward, and the
 * rendered lap runs in the circuit's cited direction.
 */

import { describe, expect, it } from "vitest";
import { fitTransform, mapFit, nudgeClear, outwardOffset, placeLabels, signedArea } from "../../src/components/spatial/geometry";
import { track } from "./fixture";

const polyline = () => track().reference!.polyline! as [number, number][];

describe("fitTransform", () => {
  it("preserves the aspect ratio and fits inside the frame with its padding", () => {
    const pts = polyline();
    for (const [w, maxH] of [[640, 460], [343, 300], [1200, 520]]) {
      const fit = fitTransform(pts, w, maxH, 16, true);
      const px = pts.map(([x, y]) => fit.toPx(x, y));
      const xs = px.map((p) => p[0]), ys = px.map((p) => p[1]);
      expect(Math.min(...xs)).toBeGreaterThanOrEqual(16 - 1e-9);
      expect(Math.max(...xs)).toBeLessThanOrEqual(w - 16 + 1e-9);
      expect(Math.min(...ys)).toBeGreaterThanOrEqual(16 - 1e-9);
      expect(Math.max(...ys)).toBeLessThanOrEqual(fit.height - 16 + 1e-9);
      expect(fit.height).toBeLessThanOrEqual(maxH);
      // one scale: a feed-unit step in x and in y cover the same pixels
      const [ax, ay] = fit.toPx(0, 0), [bx] = fit.toPx(1000, 0), [, cy] = fit.toPx(0, 1000);
      expect(Math.abs(bx - ax)).toBeCloseTo(Math.abs(cy - ay), 9);
    }
  });

  it("draws feed y upward when asked (and downward otherwise)", () => {
    const up = fitTransform([[0, 0], [10, 10]], 100, 100, 0, true);
    const down = fitTransform([[0, 0], [10, 10]], 100, 100, 0, false);
    expect(up.toPx(0, 10)[1]).toBeLessThan(up.toPx(0, 0)[1]);
    expect(down.toPx(0, 10)[1]).toBeGreaterThan(down.toPx(0, 0)[1]);
  });
});

describe("rendered direction (ledger ruling: Wikipedia 'List of Formula One circuits' - Zandvoort, Clockwise)", () => {
  it("the reference lap runs clockwise on screen", () => {
    const fit = mapFit(track(), 640);
    const screen = polyline().map(([x, y]) => fit.toPx(x, y));
    expect(signedArea(screen)).toBeGreaterThan(0);
  });

  it("signedArea is positive for a clockwise square in screen coordinates", () => {
    expect(signedArea([[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]])).toBeGreaterThan(0);
    expect(signedArea([[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]])).toBeLessThan(0);
  });
});

describe("placeLabels", () => {
  it("never overlaps two labels when a free offset exists", () => {
    const anchors = [0, 1, 2, 3].map((i) => ({ id: i, x: 100, y: 100, w: 30 }));
    const out = placeLabels(anchors, 400, 300);
    const boxes = [...out.values()].map((p) => ({ x0: p.anchor === "start" ? p.x : p.x - 30, y0: p.y - 10 }));
    for (let i = 0; i < boxes.length; i += 1) {
      for (let j = i + 1; j < boxes.length; j += 1) {
        const a = boxes[i], b = boxes[j];
        const overlap = a.x0 < b.x0 + 30 && b.x0 < a.x0 + 30 && a.y0 < b.y0 + 12 && b.y0 < a.y0 + 12;
        expect(overlap).toBe(false);
      }
    }
  });

  it("avoids reserved boxes such as the timing-line tags (browser QA finding)", () => {
    const reserved = [{ x0: 108, y0: 80, x1: 160, y1: 96 }];      // a tag right of the marker, above it
    const p = placeLabels([{ id: 1, x: 100, y: 100, w: 30 }], 400, 300, reserved).get(1)!;
    const x0 = p.anchor === "start" ? p.x : p.x - 30;
    const hit = x0 < 160 && 108 < x0 + 30 && p.y - 10 < 96 && 80 < p.y + 2;
    expect(hit).toBe(false);
  });

  it("a sector label steps out from under a timing-line tag (browser QA finding)", () => {
    const tag = { x0: 90, y0: 90, x1: 120, y1: 104 };
    const [x, y] = nudgeClear([100, 98], 16, [tag]);
    const inside = x + 8 > tag.x0 && x - 8 < tag.x1 && y + 6 > tag.y0 && y - 6 < tag.y1;
    expect(inside).toBe(false);
    expect(nudgeClear([10, 10], 16, [tag])).toEqual([10, 10]);        // already clear: unchanged
  });

  it("sector names sit outside a clockwise loop, off the cars' path (browser QA finding)", () => {
    const [ox, oy] = outwardOffset([0, 0], [10, 0], 14);             // travelling right on screen
    expect(ox).toBeCloseTo(0, 9);
    expect(oy).toBeCloseTo(-14, 9);                                   // outside = up
    const [dx, dy] = outwardOffset([0, 0], [0, 10], 14);             // travelling down
    expect(dx).toBeCloseTo(14, 9);
    expect(dy).toBeCloseTo(0, 9);
  });

  it("keeps labels inside the frame", () => {
    const out = placeLabels([{ id: 1, x: 395, y: 4, w: 30 }], 400, 300);
    const p = out.get(1)!;
    const x0 = p.anchor === "start" ? p.x : p.x - 30;
    expect(x0).toBeGreaterThanOrEqual(0);
    expect(x0 + 30).toBeLessThanOrEqual(400);
    expect(p.y - 10).toBeGreaterThanOrEqual(0);
  });
});
