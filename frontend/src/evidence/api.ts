/**
 * Evidence API client. Two calls only:
 *   1. GET /evidence/lap-comparison      -> evidence_v1 (authoritative)
 *   2. GET a segment's telemetry_reference -> raw samples, ONLY on explicit drill-down
 *
 * Errors are classified from the HTTP contract (docs/RACEWISE_EVIDENCE_CONTRACT.md
 * §11) and the backend's own message is kept verbatim. A body that is not
 * evidence_v1 is refused here (fail closed), never rendered as valid.
 */

import { CONTRACT_VERSION, type LapComparisonEvidenceV1, type TelemetryReference } from "./types";
import { evidenceUrl, type EvidenceRequest } from "./request";

export type EvidenceErrorKind =
  | "invalid"       // 422: bad parameter, lap without duration, no telemetry, identity guard
  | "not_found"     // 404: unknown session / lap / driver
  | "withheld"      // 500: evidence failed evidence_v1 validation — withheld by the backend
  | "rate_limited"  // 429
  | "unavailable"   // network failure, 502/503/504
  | "unsupported"   // a 200 body that is not evidence_v1
  | "unexpected";

export class EvidenceError extends Error {
  constructor(readonly kind: EvidenceErrorKind, message: string, readonly status: number | null) {
    super(message);
    this.name = "EvidenceError";
  }
}

export interface EvidenceResponse {
  evidence: LapComparisonEvidenceV1;
  /** Server-Timing header, verbatim (db / pipeline / serialize). */
  serverTiming: string | null;
}

function kindForStatus(status: number): EvidenceErrorKind {
  if (status === 422) return "invalid";
  if (status === 404) return "not_found";
  if (status === 429) return "rate_limited";
  if (status === 500) return "withheld";
  if (status === 502 || status === 503 || status === 504) return "unavailable";
  return "unexpected";
}

async function detailOf(r: Response): Promise<string> {
  try {
    const body = await r.json();
    const d = body?.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d.map((e) => `${(e?.loc ?? []).slice(1).join(".") || "request"}: ${e?.msg ?? "invalid"}`).join("; ");
    }
  } catch { /* non-JSON body */ }
  return `HTTP ${r.status}`;
}

export async function fetchLapComparisonEvidence(
  request: EvidenceRequest, signal?: AbortSignal, fetchImpl: typeof fetch = fetch,
): Promise<EvidenceResponse> {
  let r: Response;
  try {
    r = await fetchImpl(evidenceUrl(request), { signal, headers: { Accept: "application/json" } });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") throw e;
    throw new EvidenceError("unavailable", "The evidence API could not be reached.", null);
  }
  if (!r.ok) throw new EvidenceError(kindForStatus(r.status), await detailOf(r), r.status);

  let body: unknown;
  try { body = await r.json(); } catch {
    throw new EvidenceError("unsupported", "The response was not JSON.", r.status);
  }
  const ev = body as Partial<LapComparisonEvidenceV1> | null;
  if (!ev || ev.contract_version !== CONTRACT_VERSION || ev.evidence_type !== "lap_comparison"
      || typeof ev.evidence_id !== "string" || !ev.attribution || !ev.comparison) {
    throw new EvidenceError("unsupported",
      `Response is not ${CONTRACT_VERSION} lap_comparison evidence; nothing is rendered.`, r.status);
  }
  const headerId = r.headers.get("X-Evidence-Id");
  if (headerId && headerId !== ev.evidence_id) {
    throw new EvidenceError("unsupported",
      "X-Evidence-Id header disagrees with the body's evidence_id; nothing is rendered.", r.status);
  }
  return { evidence: ev as LapComparisonEvidenceV1, serverTiming: r.headers.get("Server-Timing") };
}

/* ── Drill-down ─────────────────────────────────────────────────────────── */

export const DRILLDOWN_CHANNELS = ["speed", "throttle", "brake", "gear", "drs"] as const;
export type DrilldownChannel = typeof DRILLDOWN_CHANNELS[number];

export interface TelemetryPoint { ts: string; value: number }

export interface TelemetryWindow {
  driverNumber: number;
  lapNumber: number;
  window: { start: string; end: string };
  provenanceClass: string | null;
  series: Record<DrilldownChannel, TelemetryPoint[]>;
}

/** Only same-origin telemetry routes of the existing shape are followed. */
const TELEMETRY_ROUTE = /^\/api\/v1\/sessions\/[^/?#]+\/telemetry\/\d{1,2}$/;

export function isSupportedReference(ref: TelemetryReference): boolean {
  return TELEMETRY_ROUTE.test(ref.route) && !!ref.start && !!ref.end;
}

export function telemetryUrl(ref: TelemetryReference): string {
  // RAW: the samples as stored — no downsampling between the evidence and the view.
  const q = new URLSearchParams({
    start: ref.start, end: ref.end, frequency: "RAW", fields: DRILLDOWN_CHANNELS.join(","),
  });
  return `${ref.route}?${q}`;
}

export async function fetchTelemetryReference(
  ref: TelemetryReference, signal?: AbortSignal, fetchImpl: typeof fetch = fetch,
): Promise<TelemetryWindow> {
  if (!isSupportedReference(ref)) {
    throw new EvidenceError("unsupported", "This telemetry reference is not a supported drill-down route.", null);
  }
  let r: Response;
  try { r = await fetchImpl(telemetryUrl(ref), { signal }); } catch (e) {
    if ((e as Error)?.name === "AbortError") throw e;
    throw new EvidenceError("unavailable", "The telemetry route could not be reached.", null);
  }
  if (!r.ok) throw new EvidenceError(kindForStatus(r.status), await detailOf(r), r.status);
  const body = await r.json();
  if (body?.driver_number !== ref.driver_number) {
    throw new EvidenceError("unsupported",
      `Telemetry identity mismatch: asked for #${ref.driver_number}, got #${body?.driver_number}.`, r.status);
  }
  const series = {} as Record<DrilldownChannel, TelemetryPoint[]>;
  for (const ch of DRILLDOWN_CHANNELS) {
    const pts = Array.isArray(body?.series?.[ch]) ? body.series[ch] : [];
    series[ch] = pts.filter((p: TelemetryPoint) =>
      typeof p?.ts === "string" && typeof p?.value === "number" && Number.isFinite(p.value));
  }
  return {
    driverNumber: ref.driver_number, lapNumber: ref.lap_number,
    window: { start: body?.window?.start ?? ref.start, end: body?.window?.end ?? ref.end },
    provenanceClass: body?.provenance?.class ?? null,
    series,
  };
}
