/** Formatting helpers. Missing data stays explicitly unavailable - never 0. */

export const UNAVAILABLE = "—";

export function fmtSec(v: number | null | undefined, digits = 3): string {
  return typeof v === "number" ? v.toFixed(digits) : UNAVAILABLE;
}

export function fmtGap(row: any): string {
  if (typeof row.gap_to_leader_s === "number") return `+${row.gap_to_leader_s.toFixed(3)}`;
  if (row.gap_to_leader_raw) return row.gap_to_leader_raw; // '+1 LAP' verbatim
  return UNAVAILABLE;
}

export function compoundLabel(c: string | null | undefined): string {
  if (!c || c === "UNKNOWN" || c === "TEST_UNKNOWN") return UNAVAILABLE;
  return c.slice(0, 3);
}

/** Sector state: color + text label (never color-only, a11y rule). */
export function sectorStyle(cls: string | undefined): { color: string; label: string } {
  switch (cls) {
    case "PURPLE": return { color: "var(--purple)", label: "SESSION BEST" };
    case "GREEN":  return { color: "var(--green)",  label: "PERSONAL BEST" };
    case "YELLOW": return { color: "var(--yellow)", label: "SLOWER" };
    default:       return { color: "var(--dim)",    label: "—" };
  }
}

export function degradationText(deg: any): string {
  if (!deg || deg.rate_s_per_lap == null) return UNAVAILABLE;
  const sign = deg.rate_s_per_lap >= 0 ? "+" : "";
  return `${sign}${deg.rate_s_per_lap.toFixed(2)} s/lap`;
}
