/**
 * Comparison request: form state <-> URL query <-> API query.
 *
 * The checks here mirror backend/app/evidence/lap_comparison.py::validate_request
 * and api::validate_session_id so a malformed request is caught before a
 * round trip. They are input hygiene, not analysis; the backend stays
 * authoritative and its 422 message is always shown when it disagrees.
 */

export const MAX_SOURCE_CHARS = 300;

export interface EvidenceRequest {
  sessionId: string;
  driverA: number;
  lapA: number;
  driverB: number;
  lapB: number;
  lapLengthM: number;
  lapLengthSource: string;
}

/** Raw text of each form field — what the user typed, before parsing. */
export interface RequestDraft {
  sessionId: string;
  driverA: string;
  lapA: string;
  driverB: string;
  lapB: string;
  lapLengthM: string;
  lapLengthSource: string;
}

export type DraftField = keyof RequestDraft;
export type DraftErrors = Partial<Record<DraftField, string>>;

export const EMPTY_DRAFT: RequestDraft = {
  sessionId: "", driverA: "", lapA: "", driverB: "", lapB: "",
  lapLengthM: "", lapLengthSource: "",
};

/**
 * The one real, validated comparison in this repository (Phase 10.2/10.4/10.5):
 * scripts/fixtures/real-openf1-pair/meta.json. Offered as a preset only — it is
 * a request, not data; the evidence still comes from the API.
 */
export const REAL_PAIR_PRESET: { label: string; draft: RequestDraft } = {
  label: "Singapore 2023 Q — #55 L19 vs #63 L16",
  draft: {
    sessionId: "openf1:9161", driverA: "55", lapA: "19", driverB: "63", lapB: "16",
    lapLengthM: "4940",
    lapLengthSource:
      "Wikipedia, 2023 Singapore Grand Prix: course length 4.940 km (Marina Bay 2023-2024 layout)",
  },
};

const PARAM: Record<DraftField, string> = {
  sessionId: "session", driverA: "driver_a", lapA: "lap_a", driverB: "driver_b",
  lapB: "lap_b", lapLengthM: "lap_length_m", lapLengthSource: "lap_length_source",
};

function parseInteger(text: string): number | null {
  const t = text.trim();
  return /^\d+$/.test(t) ? Number(t) : null;
}

function parseDecimal(text: string): number | null {
  const t = text.trim();
  if (!/^\d+(\.\d+)?$/.test(t)) return null;
  const v = Number(t);
  return Number.isFinite(v) ? v : null;
}

export function validateDraft(d: RequestDraft):
  { ok: true; request: EvidenceRequest } | { ok: false; errors: DraftErrors } {
  const errors: DraftErrors = {};
  const sid = d.sessionId.trim();
  if (!sid) errors.sessionId = "Session id is required (e.g. openf1:9161).";
  else if (sid.length > 64 || /[/\\\s]/.test(sid)) errors.sessionId = "Session id may not contain slashes or spaces, max 64 characters.";

  const driverA = parseInteger(d.driverA);
  const driverB = parseInteger(d.driverB);
  const lapA = parseInteger(d.lapA);
  const lapB = parseInteger(d.lapB);
  if (driverA == null || driverA < 1 || driverA > 99) errors.driverA = "Car number 1–99.";
  if (driverB == null || driverB < 1 || driverB > 99) errors.driverB = "Car number 1–99.";
  if (lapA == null || lapA < 1) errors.lapA = "Lap number ≥ 1.";
  if (lapB == null || lapB < 1) errors.lapB = "Lap number ≥ 1.";
  if (!errors.driverA && !errors.driverB && !errors.lapA && !errors.lapB
      && driverA === driverB && lapA === lapB) {
    errors.lapB = "A and B are the same lap — pick two different laps.";
  }

  const lapLengthM = parseDecimal(d.lapLengthM);
  if (lapLengthM == null || lapLengthM <= 0) {
    errors.lapLengthM = "Lap length in metres (> 0). It is never guessed — cite its source below.";
  }
  const src = d.lapLengthSource.trim();
  // eslint-disable-next-line no-control-regex
  if (!src || src.length > MAX_SOURCE_CHARS || /[\u0000-\u001f]/.test(src)) {
    errors.lapLengthSource = `A printable citation for the lap length, 1–${MAX_SOURCE_CHARS} characters.`;
  }

  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return {
    ok: true,
    request: {
      sessionId: sid, driverA: driverA!, lapA: lapA!, driverB: driverB!, lapB: lapB!,
      lapLengthM: lapLengthM!, lapLengthSource: src,
    },
  };
}

export function draftFromRequest(r: EvidenceRequest): RequestDraft {
  return {
    sessionId: r.sessionId, driverA: String(r.driverA), lapA: String(r.lapA),
    driverB: String(r.driverB), lapB: String(r.lapB), lapLengthM: String(r.lapLengthM),
    lapLengthSource: r.lapLengthSource,
  };
}

/** Swap A and B. The backend negates every change; nothing is negated here. */
export function swapDraft(d: RequestDraft): RequestDraft {
  return { ...d, driverA: d.driverB, lapA: d.lapB, driverB: d.driverA, lapB: d.lapA };
}

export function draftFromSearch(search: string): RequestDraft {
  const q = new URLSearchParams(search);
  const draft = { ...EMPTY_DRAFT };
  (Object.keys(PARAM) as DraftField[]).forEach((k) => { draft[k] = q.get(PARAM[k]) ?? ""; });
  return draft;
}

export function selectedLabelFromSearch(search: string): string | null {
  return new URLSearchParams(search).get("seg");
}

export function searchFromState(r: EvidenceRequest | null, selectedLabel: string | null): string {
  const q = new URLSearchParams();
  if (r) {
    const d = draftFromRequest(r);
    (Object.keys(PARAM) as DraftField[]).forEach((k) => q.set(PARAM[k], d[k]));
  }
  if (selectedLabel) q.set("seg", selectedLabel);
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function evidenceUrl(r: EvidenceRequest): string {
  const q = new URLSearchParams({
    driver_a: String(r.driverA), lap_a: String(r.lapA),
    driver_b: String(r.driverB), lap_b: String(r.lapB),
    lap_length_m: String(r.lapLengthM), lap_length_source: r.lapLengthSource,
  });
  return `/api/v1/sessions/${encodeURIComponent(r.sessionId)}/evidence/lap-comparison?${q}`;
}

export function sameRequest(a: EvidenceRequest | null, b: EvidenceRequest | null): boolean {
  if (!a || !b) return a === b;
  return a.sessionId === b.sessionId && a.driverA === b.driverA && a.lapA === b.lapA
    && a.driverB === b.driverB && a.lapB === b.lapB && a.lapLengthM === b.lapLengthM
    && a.lapLengthSource === b.lapLengthSource;
}
