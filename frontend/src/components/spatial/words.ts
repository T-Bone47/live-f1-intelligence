/**
 * Track map vocabulary (Phase 12B): formatting and words only. Every state is
 * said in words, so nothing depends on colour or shape alone. Metres are the
 * contract's own `distance_m`, rounded for display.
 */

import type { DriverState, Grade } from "../../spatial/types";
import type { SpatialReason } from "../../spatial/useSpatial";

const DASH = "—";

export function fmtMetres(m: number | null | undefined): string {
  if (m == null || !Number.isFinite(m)) return DASH;
  return `${m.toLocaleString("en-US", { maximumFractionDigits: 0 })} m`;
}

export function fmtAge(s: number | null | undefined): string {
  return s == null || !Number.isFinite(s) ? DASH : `${s.toFixed(1)} s`;
}

export const gradeWord = (g: Grade | null): string => (g ? g.toLowerCase() : "not graded");

const FLAG_WORDS: Record<string, string> = {
  ON_REFERENCE: "on reference", OFF_REFERENCE: "off reference", PIT_LANE: "pit lane",
};

/** "on reference", "pit lane", "stale · off reference", "no coverage". */
export function stateWords(d: DriverState): string {
  if (d.status === "NO_COVERAGE") return "no coverage";
  const flag = FLAG_WORDS[d.flag ?? ""] ?? "position";
  return d.status === "STALE" ? `stale · ${flag}` : flag;
}

/** The short tag printed beside a marker whose state is not a plain on-reference position. */
export function tagFor(d: DriverState): "STALE" | "PIT" | "OFF" | null {
  if (d.status === "STALE") return "STALE";
  if (d.flag === "PIT_LANE") return "PIT";
  if (d.flag === "OFF_REFERENCE") return "OFF";
  return null;
}

export const uncertain = (d: DriverState) => d.confidence === "LOW" || d.confidence === "NONE";

/** The marker's accessible name: every field in words. */
export function markerName(code: string, d: DriverState): string {
  const parts = [`#${d.driver_number} ${code}`, stateWords(d)];
  parts.push(d.lap_number != null ? `lap ${d.lap_number}` : "lap not known");
  if (d.sector != null) parts.push(`sector ${d.sector}`);
  if (d.distance_m != null) parts.push(`${fmtMetres(d.distance_m).replace(" m", "")} metres from the finish line`);
  if (d.status === "STALE") parts.push(`last sample ${fmtAge(d.age_s)} before the cursor`);
  parts.push(`confidence ${gradeWord(d.confidence)}`);
  return parts.join(", ");
}

export const REASON_TEXT: Record<SpatialReason, string> = {
  RECORDING_ONLY: "Spatial positions are built from session recordings; a running live session is not spatialized.",
  NO_RECORDING: "No recording for this session, so there is no spatial data.",
  UNVALIDATED: "The track geometry did not pass its validation gate, so no circuit or position is drawn.",
};
