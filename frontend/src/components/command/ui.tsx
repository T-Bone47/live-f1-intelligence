/**
 * Command Center primitives (Phase 11): icons, panel, badges, driver identity,
 * loading / empty / error states. One concept, one component (MASTER.md §6).
 * Icons are inline SVG paths from Lucide (ISC licence, lucide.dev); no emoji.
 */

import type { ReactNode } from "react";
import { compoundInfo, driverCode, teamColour } from "../../command/format";
import type { DriverIdentity } from "../../command/types";

const ICONS = {
  play: <polygon points="6 3 20 12 6 21 6 3" />,
  pause: <><rect x="14" y="4" width="4" height="16" rx="1" /><rect x="6" y="4" width="4" height="16" rx="1" /></>,
  skipBack: <><polygon points="19 20 9 12 19 4 19 20" /><line x1="5" x2="5" y1="19" y2="5" /></>,
  skipForward: <><polygon points="5 4 15 12 5 20 5 4" /><line x1="19" x2="19" y1="5" y2="19" /></>,
  chevronLeft: <path d="m15 18-6-6 6-6" />,
  chevronRight: <path d="m9 18 6-6-6-6" />,
  arrowUp: <><path d="m5 12 7-7 7 7" /><path d="M12 19V5" /></>,
  arrowDown: <><path d="M12 5v14" /><path d="m19 12-7 7-7-7" /></>,
  flag: <><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" /><line x1="4" x2="4" y1="22" y2="15" /></>,
  alert: <><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" /><path d="M12 9v4" /><path d="M12 17h.01" /></>,
  info: <><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></>,
  x: <><path d="M18 6 6 18" /><path d="m6 6 12 12" /></>,
  thermometer: <path d="M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z" />,
  droplet: <path d="M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z" />,
  wind: <><path d="M17.7 7.7a2.5 2.5 0 1 1 1.8 4.3H2" /><path d="M9.6 4.6A2 2 0 1 1 11 8H2" /><path d="M12.6 19.4A2 2 0 1 0 14 16H2" /></>,
  rain: <><path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242" /><path d="M16 14v6" /><path d="M8 14v6" /><path d="M12 16v6" /></>,
  timer: <><line x1="10" x2="14" y1="2" y2="2" /><line x1="12" x2="15" y1="14" y2="11" /><circle cx="12" cy="14" r="8" /></>,
  wrench: <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />,
  radio: <><circle cx="12" cy="12" r="2" /><path d="M4.93 19.07a10 10 0 0 1 0-14.14" /><path d="M7.76 16.24a6 6 0 0 1 0-8.49" /><path d="M16.24 7.76a6 6 0 0 1 0 8.49" /><path d="M19.07 4.93a10 10 0 0 1 0 14.14" /></>,
  history: <><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" /><path d="M3 3v5h5" /><path d="M12 7v5l4 2" /></>,
  keyboard: <><rect width="20" height="16" x="2" y="4" rx="2" /><path d="M6 8h.01" /><path d="M10 8h.01" /><path d="M14 8h.01" /><path d="M18 8h.01" /><path d="M8 12h.01" /><path d="M12 12h.01" /><path d="M16 12h.01" /><path d="M7 16h10" /></>,
  gauge: <><path d="m12 14 4-4" /><path d="M3.34 19a10 10 0 1 1 17.32 0" /></>,
  compare: <><path d="M8 3 4 7l4 4" /><path d="M4 7h16" /><path d="m16 21 4-4-4-4" /><path d="M20 17H4" /></>,
  list: <><line x1="8" x2="21" y1="6" y2="6" /><line x1="8" x2="21" y1="12" y2="12" /><line x1="8" x2="21" y1="18" y2="18" /><line x1="3" x2="3.01" y1="6" y2="6" /><line x1="3" x2="3.01" y1="12" y2="12" /><line x1="3" x2="3.01" y1="18" y2="18" /></>,
  database: <><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5V19A9 3 0 0 0 21 19V5" /><path d="M3 12A9 3 0 0 0 21 12" /></>,
  refresh: <><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" /><path d="M8 16H3v5" /></>,
  layers: <><path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z" /><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65" /><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65" /></>,
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 14, label }: { name: IconName; size?: number; label?: string }) {
  return (
    <svg className="cc-icon" width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
         aria-hidden={label ? undefined : true} role={label ? "img" : undefined} aria-label={label}
         focusable="false">
      {ICONS[name]}
    </svg>
  );
}

export function Panel({ id, title, meta, actions, children, className = "", busy }: {
  id: string; title: string; meta?: ReactNode; actions?: ReactNode; children: ReactNode;
  className?: string; busy?: boolean;
}) {
  return (
    <section id={id} className={`cc-panel ${className}`} aria-labelledby={`${id}-title`} aria-busy={busy || undefined}>
      <header className="cc-panel-head">
        <h2 id={`${id}-title`} className="cc-panel-title">{title}</h2>
        {meta != null && <div className="cc-panel-meta">{meta}</div>}
        {actions && <div className="cc-panel-actions">{actions}</div>}
      </header>
      <div className="cc-panel-body">{children}</div>
    </section>
  );
}

/** Driver identity: team colour bar (from provider data) + code + number. Never colour alone. */
export function DriverChip({ driver, num, showNumber = true, size = "md" }: {
  driver: DriverIdentity | undefined; num: number; showNumber?: boolean; size?: "sm" | "md" | "lg";
}) {
  const colour = teamColour(driver);
  return (
    <span className={`cc-driver cc-driver-${size}`} title={driver?.full_name ?? `Car ${num}`}>
      <span className="cc-team-bar" style={colour ? { background: colour } : undefined} aria-hidden="true" />
      <span className="cc-driver-code">{driverCode(driver, num)}</span>
      {showNumber && <span className="cc-driver-num">{num}</span>}
    </span>
  );
}

/** Compound: coloured ring + letter + word. Colour is never the only cue. */
export function TyreChip({ compound, laps, compact = false }: {
  compound: string | null; laps?: number | null; compact?: boolean;
}) {
  const c = compoundInfo(compound);
  return (
    <span className={`cc-tyre cc-tyre-${c.token}`} title={`${c.label}${laps != null ? ` · ${laps} laps on set` : ""}`}>
      <span className="cc-tyre-ring" aria-hidden="true">{c.short}</span>
      {!compact && <span className="cc-tyre-label">{c.label}</span>}
      {compact && <span className="cc-sr">{c.label}</span>}
      {laps != null && <span className="cc-tyre-laps">{laps}</span>}
    </span>
  );
}

export function Badge({ tone = "neutral", children, title }: {
  tone?: "neutral" | "live" | "replay" | "historical" | "warning" | "red" | "sc" | "vsc" | "green"
    | "chequered" | "derived" | "official";
  children: ReactNode; title?: string;
}) {
  return <span className={`cc-badge cc-badge-${tone}`} title={title}>{children}</span>;
}

/** Value with a short highlight when it changes (keyed remount; motion only on change). */
export function Tick({ value, children }: { value: string; children?: ReactNode }) {
  return <span key={value} className="cc-tick">{children ?? value}</span>;
}

export function Readout({ label, value, sub, wide }: { label: string; value: ReactNode; sub?: ReactNode; wide?: boolean }) {
  return (
    <div className={`cc-readout${wide ? " cc-readout-wide" : ""}`}>
      <dt className="cc-label">{label}</dt>
      <dd className="cc-readout-value">{value}</dd>
      {sub != null && <dd className="cc-readout-sub">{sub}</dd>}
    </div>
  );
}

export function EmptyState({ title, why, action }: { title: string; why: string; action?: ReactNode }) {
  return (
    <div className="cc-empty" role="status">
      <p className="cc-empty-title">{title}</p>
      <p className="cc-empty-why">{why}</p>
      {action}
    </div>
  );
}

export function ErrorState({ title, message, onRetry }: { title: string; message: string; onRetry?: () => void }) {
  return (
    <div className="cc-error" role="alert">
      <Icon name="alert" size={16} />
      <div>
        <p className="cc-error-title">{title}</p>
        <p className="cc-error-msg">{message}</p>
        {onRetry && (
          <button type="button" className="cc-btn" onClick={onRetry}>
            <Icon name="refresh" size={13} /> Retry
          </button>
        )}
      </div>
    </div>
  );
}

/** Content-shaped skeleton rows (no shimmer under reduced motion). */
export function SkeletonRows({ rows = 8, label }: { rows?: number; label: string }) {
  return (
    <div className="cc-skeleton" aria-busy="true" aria-label={label}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="cc-skel-row" style={{ opacity: 1 - i * (0.6 / rows) }} />
      ))}
    </div>
  );
}
