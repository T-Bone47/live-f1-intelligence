/** Formatting helpers. Missing data stays explicitly unavailable — never 0. */

export const UNAVAILABLE = "—";

export function fmtSec(v: number | null | undefined, digits = 3): string {
  return typeof v === "number" ? v.toFixed(digits) : UNAVAILABLE;
}

export function fmtLap(v: number | null | undefined, digits = 3): string {
  if (typeof v !== "number") return UNAVAILABLE;
  const m = Math.floor(v / 60);
  const s = v - m * 60;
  return m > 0 ? `${m}:${s.toFixed(digits).padStart(digits + 3, "0")}` : s.toFixed(digits);
}

export function fmtGap(row: any): string {
  if (typeof row.gap_to_leader_s === "number") return `+${row.gap_to_leader_s.toFixed(3)}`;
  if (row.gap_to_leader_raw) return row.gap_to_leader_raw; // '+1 LAP' verbatim
  return UNAVAILABLE;
}

export function fmtInterval(v: number | null | undefined): string {
  if (typeof v !== "number") return UNAVAILABLE;
  return v >= 0 ? `+${v.toFixed(3)}` : v.toFixed(3);
}

export function compoundLabel(c: string | null | undefined): string {
  if (!c || c === "UNKNOWN" || c === "TEST_UNKNOWN") return UNAVAILABLE;
  return c.slice(0, 3);
}

/** Sector state: color + text label (never color-only, a11y rule). */
export function sectorStyle(cls: string | undefined): { color: string; label: string; cssClass: string } {
  switch (cls) {
    case "PURPLE": return { color: "var(--sector-purple)", label: "SESSION BEST", cssClass: "sector-purple" };
    case "GREEN":  return { color: "var(--sector-green)",  label: "PERSONAL BEST", cssClass: "sector-green" };
    case "YELLOW": return { color: "var(--sector-yellow)", label: "SLOWER", cssClass: "sector-yellow" };
    default:       return { color: "var(--text-muted)",    label: "—", cssClass: "" };
  }
}

export function degradationText(deg: any): string {
  if (!deg || deg.rate_s_per_lap == null) return UNAVAILABLE;
  const sign = deg.rate_s_per_lap >= 0 ? "+" : "";
  return `${sign}${deg.rate_s_per_lap.toFixed(2)} s/lap`;
}

/** Team abbreviation from full name. */
export function teamAbbr(name: string | null | undefined): string {
  if (!name) return "";
  // Common F1 team abbreviations
  const map: Record<string, string> = {
    "Red Bull Racing": "RBR", "McLaren": "MCL", "Ferrari": "FER",
    "Mercedes": "MER", "Aston Martin": "AMR", "Alpine": "ALP",
    "Williams": "WIL", "RB": "RBS", "Haas F1 Team": "HAA",
    "Kick Sauber": "SAU", "Sauber": "SAU",
  };
  for (const [full, abbr] of Object.entries(map)) {
    if (name.includes(full)) return abbr;
  }
  return name.slice(0, 3).toUpperCase();
}

/** Battle state display text. */
export function battleStateLabel(state: string): string {
  return state.replace(/_/g, " ");
}

/** Track status display text. */
export function trackStatusLabel(phase: string): string {
  const map: Record<string, string> = {
    GREEN: "GREEN FLAG", YELLOW: "YELLOW FLAG", VSC: "VIRTUAL SAFETY CAR",
    SAFETY_CAR: "SAFETY CAR", RED_FLAG: "RED FLAG", CHEQUERED: "CHEQUERED FLAG",
    FORMATION_LAP: "FORMATION LAP", STARTING: "STARTING",
  };
  return map[phase] ?? phase.replace(/_/g, " ");
}

/** Event icon by type. */
export function eventIcon(type: string): string {
  const map: Record<string, string> = {
    FASTEST_LAP_CHANGE: "⚡", OVERTAKE: "↕", PIT_STOP: "🔧",
    SAFETY_CAR: "🟡", VSC: "🟡", RED_FLAG: "🔴",
    SESSION_STATE_CHANGE: "🏁", TYRE_DEGRADATION: "●",
    PACE_CHANGE: "📈", PACE_DROP: "📉",
    BATTLE_FORMED: "⚔", BATTLE_RESOLVED: "✓",
    STRATEGY_DEVIATION: "⚙", WEATHER_CHANGE: "🌤",
  };
  return map[type] ?? "•";
}

/** Format timestamp to HH:MM:SS. */
export function fmtTime(ts: string | null | undefined): string {
  if (!ts) return UNAVAILABLE;
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return UNAVAILABLE;
  }
}

/** Rolling pace trend arrow. */
export function trendArrow(slope: number | null | undefined): string {
  if (slope == null) return "";
  if (slope < -0.1) return "↗"; // improving
  if (slope > 0.1) return "↘";  // degrading
  return "→"; // stable
}
