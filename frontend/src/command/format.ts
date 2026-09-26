/**
 * Formatting and vocabulary for the Command Center. Presentation only: no
 * value is derived here. Missing values render as "—" (or a word such as
 * "Unavailable"), never null / undefined / NaN / Infinity, and never 0.
 */

import type { BattleState, DriverIdentity, RaceControlMessage, TimingRow } from "./types";

export const DASH = "—";

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** m:ss.sss (lap times). */
export function fmtLapTime(s: number | null | undefined): string {
  if (!finite(s) || s < 0) return DASH;
  const m = Math.floor(s / 60);
  const rest = s - m * 60;
  const sec = rest.toFixed(3).padStart(6, "0");
  return m > 0 ? `${m}:${sec}` : rest.toFixed(3);
}

/** Seconds with 3 decimals, sign always shown (gaps, intervals, deltas). */
export function fmtSigned(s: number | null | undefined, digits = 3): string {
  if (!finite(s)) return DASH;
  const v = s.toFixed(digits);
  return s >= 0 && !v.startsWith("-") ? `+${v}` : v;
}

export function fmtSeconds(s: number | null | undefined, digits = 3): string {
  return finite(s) ? `${s.toFixed(digits)} s` : DASH;
}

/** Gap column: the leader reads LEADER; symbolic gaps ('+1 LAP') verbatim. */
export function fmtGap(row: Pick<TimingRow, "position" | "gap_to_leader_s" | "gap_to_leader_raw">): string {
  if (row.position === 1) return "LEADER";
  if (row.gap_to_leader_raw) return row.gap_to_leader_raw;
  return fmtSigned(row.gap_to_leader_s);
}

export function fmtInterval(row: Pick<TimingRow, "position" | "interval_s">): string {
  if (row.position === 1) return DASH;
  return fmtSigned(row.interval_s);
}

export function fmtTemp(c: number | null | undefined): string {
  return finite(c) ? `${c.toFixed(1)}°C` : DASH;
}

export function fmtPct(v: number | null | undefined): string {
  return finite(v) ? `${v.toFixed(0)}%` : DASH;
}

/** Wind is measured in m/s (FIA weather reports); shown in km/h, 1 decimal. */
export function fmtWindKmh(mps: number | null | undefined): string {
  return finite(mps) ? `${(mps * 3.6).toFixed(1)} km/h` : DASH;
}

export function fmtInt(v: number | null | undefined): string {
  return finite(v) ? String(Math.round(v)) : DASH;
}

/** "13:05:28 UTC" from an ISO timestamp. */
export function fmtClockUtc(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return DASH;
  return `${d.toISOString().slice(11, 19)} UTC`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return DASH;
  return d.toISOString().slice(0, 10);
}

// ------------------------------------------------------------ identity --

export function driverCode(d: DriverIdentity | undefined, num: number): string {
  return d?.acronym ?? `#${num}`;
}

/** Provider team colour as CSS, only if it is a 6-digit hex; else null. */
export function teamColour(d: DriverIdentity | undefined): string | null {
  const hex = d?.team_colour;
  return hex && /^[0-9a-fA-F]{6}$/.test(hex) ? `#${hex}` : null;
}

// ---------------------------------------------------------------- tyres --

const COMPOUND: Record<string, { label: string; short: string; token: string }> = {
  SOFT: { label: "SOFT", short: "S", token: "soft" },
  MEDIUM: { label: "MEDIUM", short: "M", token: "medium" },
  HARD: { label: "HARD", short: "H", token: "hard" },
  INTERMEDIATE: { label: "INTER", short: "I", token: "inter" },
  WET: { label: "WET", short: "W", token: "wet" },
};

export function compoundInfo(c: string | null | undefined): { label: string; short: string; token: string } {
  return (c && COMPOUND[c]) || { label: "UNKNOWN", short: "?", token: "unknown" };
}

// ----------------------------------------------------------- race state --

const PHASE: Record<string, string> = {
  LIVE: "RUNNING", RED_FLAG: "RED FLAG", SAFETY_CAR: "SAFETY CAR", VSC: "VSC",
  SUSPENDED: "SUSPENDED", CHEQUERED: "CHEQUERED FLAG", FINISHED: "FINISHED",
  FORMATION: "FORMATION", SCHEDULED: "SCHEDULED", UNKNOWN: "STATUS UNKNOWN",
};
export const phaseLabel = (p: string | null | undefined): string => (p && PHASE[p]) || p || "STATUS UNKNOWN";
/** CSS token suffix for the phase; unknown phases stay neutral. */
export function phaseTone(p: string | null | undefined): "green" | "red" | "sc" | "vsc" | "chequered" | "neutral" {
  if (p === "LIVE") return "green";
  if (p === "RED_FLAG" || p === "SUSPENDED") return "red";
  if (p === "SAFETY_CAR") return "sc";
  if (p === "VSC") return "vsc";
  if (p === "CHEQUERED" || p === "FINISHED") return "chequered";
  return "neutral";
}

const FLAG: Record<string, string> = {
  GREEN: "GREEN", CLEAR: "CLEAR", YELLOW: "YELLOW", DOUBLE_YELLOW: "DOUBLE YELLOW",
  RED: "RED", CHEQUERED: "CHEQUERED", UNKNOWN: "NO FLAG REPORTED",
};
export const flagLabel = (f: string | null | undefined): string => (f && FLAG[f]) || f || "NO FLAG REPORTED";

const BATTLE: Record<string, { label: string; detail: string }> = {
  ACTIVE_BATTLE: { label: "ACTIVE", detail: "Battle detector: gap ≤ 0.6 s confirmed over two samples." },
  DRS_RANGE: { label: "WITHIN 1 S",
    detail: "Battle detector state DRS_RANGE: interval ≤ 1.0 s. DRS availability is not in this data." },
  DEFENDING: { label: "DEFENDING", detail: "Battle detector: the gap re-grew above 0.6 s but is still ≤ 1.0 s (or settling)." },
  SEPARATING: { label: "SEPARATING", detail: "Battle detector: the gap is opening beyond 2.5 s (or the pair is settling)." },
  OVERTAKE: { label: "OVERTAKE", detail: "Battle detector: a position swap within the pair." },
};
export function battleState(s: BattleState): { label: string; detail: string } {
  return BATTLE[s] ?? { label: s, detail: "Battle detector state." };
}

// --------------------------------------------------------- race control --

export type RcKind = "red" | "yellow" | "clear" | "green" | "blue" | "sc" | "chequered"
  | "incident" | "limits" | "session" | "info";

/** Icon/filter family of a race-control message, from its own fields and text. */
export function rcKind(m: RaceControlMessage): RcKind {
  const msg = (m.message ?? "").toUpperCase();
  const flag = (m.flag ?? "").toUpperCase();
  if (flag === "RED" || /\bRED FLAG\b/.test(msg)) return "red";
  if (flag === "CHEQUERED") return "chequered";
  if (/SAFETY CAR|\bVSC\b/.test(msg)) return "sc";
  if (flag === "YELLOW" || flag === "DOUBLE YELLOW") return "yellow";
  if (flag === "CLEAR") return "clear";
  if (flag === "GREEN") return "green";
  if (flag === "BLUE") return "blue";
  if (/DELETED|TRACK LIMITS/.test(msg)) return "limits";
  if (/PENALTY|INVESTIGATION|STEWARDS|NOTED|REPRIMAND/.test(msg)) return "incident";
  if (/^SESSION |RESUME|RESUMPTION|STANDING START|FORMATION/.test(msg)) return "session";
  return "info";
}

export const RC_FILTERS: { id: string; label: string; kinds: RcKind[] | null }[] = [
  { id: "key", label: "Key", kinds: ["red", "sc", "chequered", "session", "incident", "green"] },
  { id: "flags", label: "Flags", kinds: ["red", "yellow", "clear", "green", "blue", "sc", "chequered"] },
  { id: "incidents", label: "Incidents", kinds: ["incident", "limits"] },
  { id: "all", label: "All", kinds: null },
];
