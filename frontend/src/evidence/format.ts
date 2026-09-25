/**
 * Presentation formatting for evidence values.
 *
 * Formatting only: rounding for display, units, signs and phrasing that the
 * contract already defines. No value is derived here. Anything that is not a
 * finite number renders as UNAVAILABLE — never "null", "NaN" or "Infinity".
 */

export const UNAVAILABLE = "—";
const MINUS = "−"; // typographic minus: same width as "+" in the mono face

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function signed(v: number, digits: number): string {
  const s = Math.abs(v).toFixed(digits);
  // -0.0004 rounds to "0.000": show it unsigned rather than as "−0.000".
  if (Number(s) === 0) return s;
  return (v < 0 ? MINUS : "+") + s;
}

/** Signed seconds, e.g. "−0.072 s". */
export function fmtDelta(v: number | null | undefined, digits = 3): string {
  return isNum(v) ? `${signed(v, digits)} s` : UNAVAILABLE;
}

/** Signed number without unit (tables with a unit in the header). */
export function fmtSignedNum(v: number | null | undefined, digits = 3): string {
  return isNum(v) ? signed(v, digits) : UNAVAILABLE;
}

/** Uncertainty band, e.g. "±0.108 s". */
export function fmtBand(v: number | null | undefined, digits = 3): string {
  return isNum(v) ? `±${Math.abs(v).toFixed(digits)} s` : UNAVAILABLE;
}

/** Lap or sector time: "1:30.984" or "26.717". */
export function fmtLapTime(v: number | null | undefined): string {
  if (!isNum(v)) return UNAVAILABLE;
  const m = Math.floor(v / 60);
  const s = v - m * 60;
  return m > 0 ? `${m}:${s.toFixed(3).padStart(6, "0")}` : s.toFixed(3);
}

export function fmtSeconds(v: number | null | undefined, digits = 3): string {
  return isNum(v) ? `${v.toFixed(digits)} s` : UNAVAILABLE;
}

/**
 * Metres. When the evidence carries ALIGNMENT_NORMALIZED_DISTANCE every metre
 * label says so (Phase 10.5 handoff): "2,875 m norm."
 */
export function fmtMetres(v: number | null | undefined, normalized: boolean, digits = 0): string {
  if (!isNum(v)) return UNAVAILABLE;
  const n = v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return normalized ? `${n} m norm.` : `${n} m`;
}

export function fmtMetreRange(a: number, b: number, normalized: boolean): string {
  const f = (v: number) => Math.round(v).toLocaleString("en-US");
  return `${f(a)}–${f(b)} ${normalized ? "m norm." : "m"}`;
}

/** Normalized lap fraction, e.g. "x 0.582". */
export function fmtX(v: number | null | undefined, digits = 3): string {
  return isNum(v) ? `x ${v.toFixed(digits)}` : UNAVAILABLE;
}

export function fmtKph(v: number | null | undefined, digits = 0): string {
  return isNum(v) ? `${v.toFixed(digits)} km/h` : UNAVAILABLE;
}

export function fmtSignedKph(v: number | null | undefined, digits = 1): string {
  return isNum(v) ? `${signed(v, digits)} km/h` : UNAVAILABLE;
}

export function fmtPct(v: number | null | undefined, digits = 0): string {
  return isNum(v) ? `${v.toFixed(digits)} %` : UNAVAILABLE;
}

export function fmtFraction(v: number | null | undefined): string {
  return isNum(v) ? `${(v * 100).toFixed(1)} %` : UNAVAILABLE;
}

export function fmtInt(v: number | null | undefined): string {
  return isNum(v) ? String(Math.round(v)) : UNAVAILABLE;
}

/** ISO timestamp -> "14:27:34.368 UTC" (the evidence stores UTC). */
export function fmtClock(ts: string | null | undefined): string {
  if (!ts) return UNAVAILABLE;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return UNAVAILABLE;
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}.${p(d.getUTCMilliseconds(), 3)} UTC`;
}

export function fmtDate(ts: string | null | undefined): string {
  if (!ts) return UNAVAILABLE;
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? UNAVAILABLE : d.toISOString().slice(0, 10);
}

export function driverTag(n: number): string {
  return `#${n}`;
}

/**
 * Who is ahead at a delta value, from the contract's sign convention
 * (negative = A ahead). Returns null when unavailable.
 */
export function aheadOf(delta: number | null | undefined, a: number, b: number): string | null {
  if (!isNum(delta)) return null;
  if (Number(Math.abs(delta).toFixed(3)) === 0) return "level";
  return delta < 0 ? `${driverTag(a)} ahead` : `${driverTag(b)} ahead`;
}

/**
 * Which driver a segment's change favours (contract §4: negative = A gained
 * time in the segment). A measured direction, not a cause.
 */
export function changeFavours(change: number | null | undefined, a: number, b: number): string | null {
  if (!isNum(change)) return null;
  if (Number(Math.abs(change).toFixed(3)) === 0) return "no net change";
  return change < 0 ? `favours ${driverTag(a)}` : `favours ${driverTag(b)}`;
}

/**
 * Offset phrasing from the contract's rule "sign A − B along the lap":
 * positive = A's event later along the lap. "#55 brake onset 31.8 m later (norm.)"
 */
export function offsetPhrase(
  offsetM: number | null | undefined, a: number, what: string, normalized: boolean,
): string {
  if (!isNum(offsetM)) return `${what}: not comparable`;
  const mag = Math.abs(offsetM);
  if (Number(mag.toFixed(1)) === 0) return `${driverTag(a)} ${what} at the same point`;
  const where = offsetM > 0 ? "later" : "earlier";
  return `${driverTag(a)} ${what} ${mag.toFixed(1)} m ${where}${normalized ? " (norm.)" : ""}`;
}
