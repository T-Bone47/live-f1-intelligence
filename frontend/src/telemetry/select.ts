/**
 * Selection over stored samples (Phase 12C). Nothing here computes a value:
 * it keeps the samples at or before the cursor and splits them where two
 * real samples are more than MAX_GAP_MS apart, so a line is never drawn
 * across a gap.
 */

import { MAX_GAP_MS, type ChannelView, type Gap, type Sample, type TelemetryPoint } from "./types";

export function toSamples(points: TelemetryPoint[]): Sample[] {
  return points.map((p) => ({ t: Date.parse(p.ts), value: p.value }));
}

/** Number of samples at or before t (samples sorted by time). */
export function countUpTo(samples: Sample[], t: number): number {
  let lo = 0, hi = samples.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (samples[mid].t <= t) lo = mid + 1; else hi = mid;
  }
  return lo;
}

export function splitRuns(samples: Sample[]): { runs: Sample[][]; gaps: Gap[] } {
  const runs: Sample[][] = [];
  const gaps: Gap[] = [];
  let run: Sample[] = [];
  for (const s of samples) {
    const prev = run.at(-1);
    if (prev && s.t - prev.t > MAX_GAP_MS) {
      runs.push(run);
      gaps.push({ from: prev.t, to: s.t });
      run = [];
    }
    run.push(s);
  }
  if (run.length) runs.push(run);
  return { runs, gaps };
}

/** The samples in [from, t], split at gaps; the last one is the latest at t. */
export function channelView(samples: Sample[], from: number, t: number, available: boolean): ChannelView {
  const shown = samples.slice(countUpTo(samples, from - 1), countUpTo(samples, t));
  const { runs, gaps } = splitRuns(shown);
  return { available, runs, gaps, latest: shown.at(-1) ?? null };
}
