/**
 * evidence_spatial_v1 client (Phase 12C): the loaded evidence_v1 segments
 * placed on the validated 12A track by each driver's own sample times.
 *   GET /api/v1/sessions/{sid}/evidence/lap-comparison/spatial?<same query>
 *
 * Fail closed: the document must name the loaded evidence (header and body),
 * its session, drivers and track, list the evidence's segments in order, and
 * carry a path exactly for PLACED extents. The browser never places anything.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, getJson } from "../command/api";
import { fetchTrack } from "../spatial/api";
import type { TrackReference } from "../spatial/types";
import { evidenceUrl, type EvidenceRequest } from "./request";
import type { LapComparisonEvidenceV1 } from "./types";

export const EVIDENCE_SPATIAL_CONTRACT = "evidence_spatial_v1";

export type PlacementReason = "NO_TELEMETRY" | "NO_COVERAGE" | "STALE" | "PIT_LANE" | "OFF_REFERENCE" | "NO_FRACTION";

export interface Extent {
  status: "PLACED" | "NOT_PLACED";
  reason: PlacementReason | null;
  from_ts: string | null;
  to_ts: string | null;
  from_fraction: number | null;
  to_fraction: number | null;
  from_xy: number[] | null;
  to_xy: number[] | null;
  polyline: number[][] | null;
}

export interface PlacedSegment { segment_id: string; label: string; a: Extent; b: Extent }

export interface EvidenceSpatial {
  contract_version: typeof EVIDENCE_SPATIAL_CONTRACT;
  builder_version: string;
  evidence_id: string;
  session_id: string;
  track_id: string;
  driver_a: number;
  driver_b: number;
  lap_length_m: number | null;
  line_placement_p95_m: Record<string, number> | null;
  segments: PlacedSegment[];
  limitations: { code: string; message: string }[];
}

export const REASON_WORDS: Record<PlacementReason, string> = {
  NO_TELEMETRY: "no telemetry",
  NO_COVERAGE: "no location coverage",
  STALE: "location samples more than 2 s apart",
  PIT_LANE: "pit lane",
  OFF_REFERENCE: "off the reference line",
  NO_FRACTION: "no lap position",
};

const refuse = (message: string): never => { throw new ApiError("unsupported", message, 200); };

function checkExtent(e: Extent | undefined, where: string): void {
  if (!e || (e.status !== "PLACED" && e.status !== "NOT_PLACED")) refuse(`${where} has no placement.`);
  if (e!.status === "PLACED") {
    if (!Array.isArray(e!.polyline) || e!.polyline.length < 2 || e!.reason != null) refuse(`${where} is placed without a path.`);
  } else if (e!.polyline != null || e!.from_xy != null || e!.to_xy != null || !e!.reason) {
    refuse(`${where} is not placed but carries a position.`);
  }
}

export function checkEvidenceSpatial(body: unknown, evidence: LapComparisonEvidenceV1, trackId: string): EvidenceSpatial {
  const d = body as Partial<EvidenceSpatial> | null;
  if (!d || d.contract_version !== EVIDENCE_SPATIAL_CONTRACT) refuse(`Response is not ${EVIDENCE_SPATIAL_CONTRACT}.`);
  if (d!.evidence_id !== evidence.evidence_id) refuse(`Placement is for ${d!.evidence_id}, not the loaded ${evidence.evidence_id}.`);
  if (d!.session_id !== evidence.source.session_id) refuse(`Placement belongs to ${d!.session_id}, not ${evidence.source.session_id}.`);
  if (d!.track_id !== trackId) refuse(`Placement is on track ${d!.track_id}, not the loaded ${trackId}.`);
  if (d!.driver_a !== evidence.comparison.driver_a.driver_number || d!.driver_b !== evidence.comparison.driver_b.driver_number) {
    refuse("Placement is for other drivers.");
  }
  const want = evidence.attribution.segments.map((s) => `${s.segment_id}|${s.label}`).join(",");
  if (!Array.isArray(d!.segments) || d!.segments.map((s) => `${s.segment_id}|${s.label}`).join(",") !== want) {
    refuse("Placement segments differ from the evidence.");
  }
  for (const s of d!.segments!) {
    checkExtent(s.a, `${s.label} A`);
    checkExtent(s.b, `${s.label} B`);
  }
  return d as EvidenceSpatial;
}

export async function fetchEvidenceSpatial(request: EvidenceRequest, evidence: LapComparisonEvidenceV1, trackId: string,
                                           signal?: AbortSignal, f: typeof fetch = fetch): Promise<EvidenceSpatial> {
  const url = evidenceUrl(request).replace("/evidence/lap-comparison?", "/evidence/lap-comparison/spatial?");
  const { body, response } = await getJson(url, signal, f);
  if (response.headers.get("X-Spatial-Contract") !== EVIDENCE_SPATIAL_CONTRACT) refuse("Server declared no evidence_spatial_v1.");
  if (response.headers.get("X-Evidence-Id") !== evidence.evidence_id) refuse("Placement header names another evidence.");
  return checkEvidenceSpatial(body, evidence, trackId);
}

export interface TrackContextView {
  status: "idle" | "loading" | "ready" | "unavailable" | "error";
  track: TrackReference | null;
  placed: EvidenceSpatial | null;
  reasons: string[];
  message: string | null;
  retry: () => void;
}

type Slot<T> = { key: string; value: T | null; error: ApiError | null };

/** The evidence is the answer to this request (same session, drivers, laps and cited length). */
function answers(r: EvidenceRequest, e: LapComparisonEvidenceV1): boolean {
  const c = e.comparison;
  return e.source.session_id === r.sessionId
    && c.driver_a.driver_number === r.driverA && c.driver_a.lap_number === r.lapA
    && c.driver_b.driver_number === r.driverB && c.driver_b.lap_number === r.lapB
    && c.lap_length.m === r.lapLengthM && c.lap_length.source === r.lapLengthSource;
}

const asApiError = (e: unknown): ApiError =>
  (e instanceof ApiError ? e : new ApiError("unexpected", (e as Error)?.message || "Unexpected error.", null));

/** Track (per session) and placement (per evidence) for the workbench. */
export function useTrackContext(request: EvidenceRequest | null, evidence: LapComparisonEvidenceV1 | null): TrackContextView {
  const [reload, setReload] = useState(0);
  const [trackSlot, setTrackSlot] = useState<Slot<TrackReference> | null>(null);
  const [placedSlot, setPlacedSlot] = useState<Slot<EvidenceSpatial> | null>(null);
  const sid = request?.sessionId ?? null;
  const trackKey = sid == null ? null : `${sid}|${reload}`;

  useEffect(() => {
    if (trackKey == null || sid == null || trackSlot?.key === trackKey) return undefined;
    const ctrl = new AbortController();
    fetchTrack(sid, ctrl.signal).then(
      (t) => setTrackSlot({ key: trackKey, value: t, error: null }),
      (e: unknown) => { if ((e as Error)?.name !== "AbortError") setTrackSlot({ key: trackKey, value: null, error: asApiError(e) }); });
    return () => ctrl.abort();
  }, [sid, trackKey, trackSlot?.key]);

  const track = trackSlot?.key === trackKey ? trackSlot.value : null;
  const validated = track?.status === "VALIDATED_MAP_SECTOR" ? track : null;
  // place only the evidence this request produced: while a new request loads, the
  // previous evidence is still shown and must not be paired with the new query
  const placedKey = validated && evidence && request && answers(request, evidence)
    ? `${evidence.evidence_id}|${validated.track_id}|${reload}` : null;

  useEffect(() => {
    if (placedKey == null || placedSlot?.key === placedKey || !request || !evidence || !validated) return undefined;
    const ctrl = new AbortController();
    fetchEvidenceSpatial(request, evidence, validated.track_id, ctrl.signal).then(
      (p) => setPlacedSlot({ key: placedKey, value: p, error: null }),
      (e: unknown) => { if ((e as Error)?.name !== "AbortError") setPlacedSlot({ key: placedKey, value: null, error: asApiError(e) }); });
    return () => ctrl.abort();
  }, [placedKey, placedSlot?.key, request, evidence, validated]);

  const retry = useCallback(() => { setTrackSlot(null); setPlacedSlot(null); setReload((r) => r + 1); }, []);
  const base = { track: validated, placed: null, reasons: [] as string[], message: null as string | null, retry };

  if (trackKey == null) return { ...base, status: "idle" };
  const tErr = trackSlot?.key === trackKey ? trackSlot.error : null;
  if (tErr) {
    return tErr.kind === "not_found" || tErr.kind === "unvalidated"
      ? { ...base, status: "unavailable", message: tErr.message, reasons: tErr.reasons }
      : { ...base, status: "error", message: tErr.message };
  }
  if (!trackSlot || trackSlot.key !== trackKey) return { ...base, status: "loading" };
  if (!validated) {
    return { ...base, status: "unavailable", message: "The session's track geometry did not pass its validation gate.",
             reasons: track?.validation.reasons ?? [] };
  }
  if (placedKey == null) return { ...base, status: "loading" };
  const pErr = placedSlot?.key === placedKey ? placedSlot.error : null;
  if (pErr) {
    return pErr.kind === "not_found" || pErr.kind === "unvalidated"
      ? { ...base, status: "unavailable", message: pErr.message, reasons: pErr.reasons }
      : { ...base, status: "error", message: pErr.message };
  }
  if (!placedSlot || placedSlot.key !== placedKey) return { ...base, status: "loading" };
  return { ...base, status: "ready", placed: placedSlot.value };
}
