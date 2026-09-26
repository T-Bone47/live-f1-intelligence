/**
 * Track map rendering geometry (Phase 12B) - pixels only. Nothing here
 * produces a position, distance, sector or lap: feed coordinates from the
 * contracts are scaled onto the panel (one scale for x and y, so the circuit
 * keeps its shape) and labels are placed so they do not collide.
 *
 * Orientation (ledger ruling): feed y is drawn upward. Wikipedia's "List of
 * Formula One circuits" gives Circuit Zandvoort as clockwise, and the 2026
 * reference lap runs clockwise in y-up feed coordinates (shoelace area
 * -2.2e7), so y-up renders it clockwise on screen (tested).
 */

import type { TrackReference } from "../../spatial/types";

export interface Fit { toPx: (x: number, y: number) => [number, number]; width: number; height: number }

export const MAP_PAD = 18;
export const MAP_MIN_H = 220;
export const MAP_MAX_H = 540;

export function fitTransform(points: number[][], width: number, maxHeight: number, pad: number, yUp: boolean): Fit {
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const [x, y] of points) {
    if (x < x0) x0 = x;
    if (x > x1) x1 = x;
    if (y < y0) y0 = y;
    if (y > y1) y1 = y;
  }
  const bw = Math.max(x1 - x0, 1e-9), bh = Math.max(y1 - y0, 1e-9);
  const scale = Math.max(0, Math.min((width - 2 * pad) / bw, (maxHeight - 2 * pad) / bh));
  const height = bh * scale + 2 * pad;
  const ox = (width - bw * scale) / 2;
  return {
    width,
    height,
    toPx: (x, y) => [ox + (x - x0) * scale, yUp ? pad + (y1 - y) * scale : pad + (y - y0) * scale],
  };
}

/** The map's own fit for a validated track at a panel width (height follows the width). */
export function mapFit(track: TrackReference, width: number): Fit {
  const maxH = Math.max(MAP_MIN_H, Math.min(MAP_MAX_H, width * 0.8));
  return fitTransform(track.reference?.polyline ?? [[0, 0]], width, maxH, MAP_PAD, true);
}

/** Shoelace sum in screen coordinates (y down): > 0 means the path runs clockwise on screen. */
export function signedArea(points: number[][]): number {
  let a = 0;
  for (let i = 0; i + 1 < points.length; i += 1) {
    a += points[i][0] * points[i + 1][1] - points[i + 1][0] * points[i][1];
  }
  return a / 2;
}

/** SVG path data for a polyline already in pixels. */
export function pathData(px: [number, number][], close = false): string {
  if (px.length === 0) return "";
  const d = px.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join("");
  return close ? `${d}Z` : d;
}

const LABEL_H = 12;

export interface Box { x0: number; y0: number; x1: number; y1: number }

/** Where a timing-line tag is drawn (text baseline 10 px above, 12 px right of the line point) and
 * the box drawn around it - the same box label placement keeps clear. */
export const LINE_TAG_DX = 12, LINE_TAG_DY = -10;
export function lineTagBox(at: [number, number], text: string): Box {
  const x0 = at[0] + LINE_TAG_DX - 4, base = at[1] + LINE_TAG_DY;
  return { x0, y0: base - 10, x1: x0 + text.length * 6.4 + 8, y1: base + 4 };
}
const OFFSETS: { dx: number; dy: number; anchor: "start" | "end" }[] = [
  { dx: 9, dy: -7, anchor: "start" }, { dx: -9, dy: -7, anchor: "end" },
  { dx: 9, dy: 15, anchor: "start" }, { dx: -9, dy: 15, anchor: "end" },
];

/**
 * Greedy label placement: each label takes the first of four offsets around
 * its marker that stays inside the frame and overlaps no label placed before
 * it or any reserved box, such as a timing-line tag (callers pass the most
 * important labels first). `y` is the baseline.
 */
export function placeLabels(anchors: { id: number; x: number; y: number; w: number }[], w: number, h: number,
                            reserved: Box[] = []): Map<number, { x: number; y: number; anchor: "start" | "end" }> {
  const placed: Box[] = [...reserved];
  const out = new Map<number, { x: number; y: number; anchor: "start" | "end" }>();
  for (const a of anchors) {
    const boxes = OFFSETS.map((o) => {
      const x = a.x + o.dx, y = a.y + o.dy;
      const x0 = o.anchor === "start" ? x : x - a.w;
      return { x, y, anchor: o.anchor, box: { x0, y0: y - LABEL_H + 2, x1: x0 + a.w, y1: y + 2 } };
    });
    const inside = boxes.filter((b) => b.box.x0 >= 0 && b.box.x1 <= w && b.box.y0 >= 0 && b.box.y1 <= h);
    const free = inside.find((b) => placed.every((p) => b.box.x1 <= p.x0 || p.x1 <= b.box.x0
                                                         || b.box.y1 <= p.y0 || p.y1 <= b.box.y0));
    const pick = free ?? inside[0] ?? boxes[0];
    placed.push(pick.box);
    out.set(a.id, { x: pick.x, y: pick.y, anchor: pick.anchor });
  }
  return out;
}

/** A short centred label (sector name) moved off any reserved box: the first of
 * its own spot, then `step` px below, above, right, left, then twice as far. */
export function nudgeClear(at: [number, number], step: number, reserved: Box[]): [number, number] {
  const tries = [[0, 0], [0, step], [0, -step], [step, 0], [-step, 0], [0, 2 * step], [0, -2 * step]];
  for (const [dx, dy] of tries) {
    const x = at[0] + dx, y = at[1] + dy;
    if (reserved.every((b) => x + 8 <= b.x0 || x - 8 >= b.x1 || y + 6 <= b.y0 || y - 6 >= b.y1)) return [x, y];
  }
  return at;
}

/** Pixel offset `d` px to the left of travel from a to b: outside the loop for a
 * lap drawn clockwise on screen (the orientation ruling), so a sector name
 * sits beside the cars' path rather than on it. */
export function outwardOffset(a: [number, number], b: [number, number], d: number): [number, number] {
  const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
  return [Math.sin(ang) * d, -Math.cos(ang) * d];
}

/** Screen angle (degrees) of the path leaving a point - orients a timing-line tick. */
export function headingDeg(from: [number, number], to: [number, number]): number {
  return (Math.atan2(to[1] - from[1], to[0] - from[0]) * 180) / Math.PI;
}
