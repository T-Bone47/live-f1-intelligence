/**
 * Evidence Workbench primitives: icons, driver tags, class and status badges.
 * One component per concept, used everywhere on the page (MASTER.md §6).
 *
 * Icons are inline SVG paths from Lucide (ISC licence, lucide.dev) — no
 * emoji, no icon-font dependency.
 */

import type { ReactNode } from "react";
import type { AttributionStatus, Confidence } from "../../evidence/types";
import { CLASS_TEXT, CONFIDENCE_TEXT, STATUS_TEXT } from "../../evidence/vocabulary";

const ICONS = {
  chevronLeft: <path d="m15 18-6-6 6-6" />,
  chevronRight: <path d="m9 18 6-6-6-6" />,
  chevronDown: <path d="m6 9 6 6 6-6" />,
  x: <><path d="M18 6 6 18" /><path d="m6 6 12 12" /></>,
  swap: <><path d="M8 3 4 7l4 4" /><path d="M4 7h16" /><path d="m16 21 4-4-4-4" /><path d="M20 17H4" /></>,
  refresh: <><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" /><path d="M8 16H3v5" /></>,
  alert: <><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" /><path d="M12 9v4" /><path d="M12 17h.01" /></>,
  info: <><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></>,
  copy: <><rect width="14" height="14" x="8" y="8" rx="2" ry="2" /><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" /></>,
  check: <path d="M20 6 9 17l-5-5" />,
  activity: <path d="M22 12h-4l-3 9L9 3l-3 9H2" />,
  zoomIn: <><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /><path d="M11 8v6" /><path d="M8 11h6" /></>,
  zoomOut: <><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /><path d="M8 11h6" /></>,
  arrowLeft: <><path d="m12 19-7-7 7-7" /><path d="M19 12H5" /></>,
  send: <><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></>,
  circleDot: <><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="2" /></>,
  circleMinus: <><circle cx="12" cy="12" r="10" /><path d="M8 12h8" /></>,
  ban: <><circle cx="12" cy="12" r="10" /><path d="m4.9 4.9 14.2 14.2" /></>,
  database: <><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5V19A9 3 0 0 0 21 19V5" /><path d="M3 12A9 3 0 0 0 21 12" /></>,
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 14, label }: { name: IconName; size?: number; label?: string }) {
  return (
    <svg className="ewb-icon" width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
         aria-hidden={label ? undefined : true} role={label ? "img" : undefined} aria-label={label}
         focusable="false">
      {ICONS[name]}
    </svg>
  );
}

/** "#55" with an A/B monogram; A = solid round marker, B = dashed square (never colour alone). */
export function DriverTag({ side, number, compact = false }: { side: "A" | "B"; number: number; compact?: boolean }) {
  return (
    <span className={`ewb-driver ewb-driver-${side.toLowerCase()}`}>
      <span className="ewb-driver-mono" aria-hidden="true">{side}</span>
      <span className="ewb-num">#{number}</span>
      {!compact && <span className="ewb-sr">(driver {side})</span>}
    </span>
  );
}

/** Evidence class letter + word: B OFFICIAL / C DERIVED / F UNAVAILABLE. */
export function ClassBadge({ cls }: { cls: "B" | "C" | "F" }) {
  return (
    <span className={`ewb-class ewb-class-${cls.toLowerCase()}`} title={CLASS_TEXT[cls].long}>
      <span className="ewb-class-letter" aria-hidden="true">{cls}</span>
      {CLASS_TEXT[cls].short}
      <span className="ewb-sr">, {CLASS_TEXT[cls].long}</span>
    </span>
  );
}

/** Significance from the contract's `significant` flag — never recomputed. */
export function SignificanceBadge({ significant, noData = false }: { significant: boolean; noData?: boolean }) {
  if (noData) {
    return <span className="ewb-sig ewb-sig-nodata"><Icon name="ban" size={12} />No data</span>;
  }
  return significant
    ? <span className="ewb-sig ewb-sig-yes"><Icon name="circleDot" size={12} />Significant</span>
    : <span className="ewb-sig ewb-sig-no"><Icon name="circleMinus" size={12} />Not significant</span>;
}

export function StatusBadge({ status }: { status: AttributionStatus }) {
  return (
    <span className={`ewb-status ewb-status-${status.toLowerCase()}`} title={STATUS_TEXT[status].detail}>
      {STATUS_TEXT[status].label}
    </span>
  );
}

export function ConfidenceTag({ level, prefix = "Telemetry" }: { level: Confidence; prefix?: string }) {
  return (
    <span className={`ewb-conf ewb-conf-${level.toLowerCase()}`}>
      {prefix} <strong>{CONFIDENCE_TEXT[level]}</strong>
    </span>
  );
}

/** Resolvable = the two drivers' sample brackets are further apart than the misalignment bound. */
export function ResolvableTag({ resolvable }: { resolvable: boolean }) {
  return resolvable
    ? <span className="ewb-res ewb-res-yes">Resolvable</span>
    : <span className="ewb-res ewb-res-no">Within alignment error</span>;
}

export function AssociationTag() {
  return <span className="ewb-assoc" title="Associations are temporal only; causality is not established.">Temporal association</span>;
}

export function Section({ id, title, eyebrow, actions, children, className = "", busy }: {
  id?: string; title: string; eyebrow?: string; actions?: ReactNode; children: ReactNode;
  className?: string; busy?: boolean;
}) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section id={id} className={`ewb-section ${className}`} aria-labelledby={headingId} aria-busy={busy || undefined}>
      <header className="ewb-section-head">
        <div>
          {eyebrow && <p className="ewb-eyebrow">{eyebrow}</p>}
          <h2 id={headingId} className="ewb-section-title" tabIndex={-1}>{title}</h2>
        </div>
        {actions && <div className="ewb-section-actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

/** Label/value pair for dense definition grids. */
export function Readout({ label, value, sub, tone }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: "a" | "b" | "muted";
}) {
  return (
    <div className="ewb-readout">
      <dt className="ewb-label">{label}</dt>
      <dd className={`ewb-value ${tone ? `ewb-tone-${tone}` : ""}`}>{value}</dd>
      {sub != null && <dd className="ewb-readout-sub">{sub}</dd>}
    </div>
  );
}
