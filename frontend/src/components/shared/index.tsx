/**
 * Shared UI primitives — LIVE F1 INTELLIGENCE
 * Design system building blocks, all values from tokens.css.
 */

import { type ReactNode, type HTMLAttributes, memo } from "react";
import { UNAVAILABLE } from "../../logic/format";

/* ── Panel ── */
interface PanelProps extends HTMLAttributes<HTMLDivElement> {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}

export function Panel({ title, actions, children, className = "", ...rest }: PanelProps) {
  return (
    <div className={`panel ${className}`} {...rest}>
      <div className="panel-header">
        <h2>{title}</h2>
        {actions && <div className="panel-actions">{actions}</div>}
      </div>
      <div className="panel-body">{children}</div>
    </div>
  );
}

/* ── Status Badge ── */
const STATUS_MAP: Record<string, { label: string; cssColor: string; dotColor: string }> = {
  LIVE:         { label: "LIVE",         cssColor: "var(--live)",     dotColor: "var(--live)" },
  REPLAY:       { label: "REPLAY",       cssColor: "var(--info)",     dotColor: "var(--info)" },
  CONNECTING:   { label: "CONNECTING",   cssColor: "var(--text-muted)", dotColor: "var(--warning)" },
  CONNECTED:    { label: "CONNECTED",    cssColor: "var(--success)",  dotColor: "var(--success)" },
  DEGRADED:     { label: "DEGRADED",     cssColor: "var(--warning)",  dotColor: "var(--warning)" },
  DISCONNECTED: { label: "DISCONNECTED", cssColor: "var(--text-muted)", dotColor: "var(--text-muted)" },
  WAITING:      { label: "WAITING",      cssColor: "var(--text-muted)", dotColor: "var(--text-muted)" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS_MAP[status] ?? STATUS_MAP.WAITING;
  return (
    <span className="status-badge" style={{ color: s.cssColor, borderColor: s.cssColor }}>
      <span style={{
        width: 6, height: 6, borderRadius: "50%", background: s.dotColor,
        display: "inline-block",
        animation: status === "LIVE" ? "rc-pulse 1.5s ease-in-out infinite" : undefined,
      }} />
      {s.label}
    </span>
  );
}

/* ── Status Ribbon ── */
export function StatusRibbon({ phase, status }: { phase: string; status: string }) {
  const cls = status === "LIVE"
    ? (phase || "green").toLowerCase().replace(/ /g, "_")
    : status.toLowerCase();
  return <div className={`status-ribbon ${cls}`} role="status" aria-label={`Track status: ${cls}`} />;
}

/* ── Confidence Badge ── */
export function ConfidenceBadge({ level }: { level: string | null | undefined }) {
  const l = (level ?? "NONE").toUpperCase();
  return <span className={`conf-badge conf-${l}`}>{l}</span>;
}

/* ── Provenance Badge ── */
export function ProvenanceBadge({ type }: { type: "LIVE" | "DERIVED" | "ESTIMATED" | "HYPOTHETICAL" | "AI" }) {
  return <span className={`provenance-badge prov-${type.toLowerCase()}`}>{type}</span>;
}

/* ── Tyre Chip ── */
const COMPOUND_COLOR: Record<string, string> = {
  SOFT: "var(--tyre-soft)", MEDIUM: "var(--tyre-medium)",
  HARD: "var(--tyre-hard)", INTERMEDIATE: "var(--tyre-inter)",
  WET: "var(--tyre-wet)",
};

export const TyreChip = memo(function TyreChip(
  { compound, age }: { compound: string | null | undefined; age?: number | null }
) {
  const c = (compound ?? "UNKNOWN").toUpperCase();
  if (c === "UNKNOWN" || c === "TEST_UNKNOWN") return <span className="dim text-xs">—</span>;
  const color = COMPOUND_COLOR[c] ?? "var(--text-muted)";
  return (
    <span className="tyre-chip">
      <span className="tyre-dot" style={{ borderColor: color }} title={c}>
        {c[0]}
      </span>
      {age != null && <span className="tyre-age">{age}</span>}
    </span>
  );
});

/* ── Timing Value ── */
export function TimingValue(
  { value, highlight, className = "" }: { value: string; highlight?: string; className?: string }
) {
  const hClass = highlight === "purple" ? "sector-purple"
    : highlight === "green" ? "sector-green"
    : highlight === "yellow" ? "sector-yellow"
    : "";
  return <span className={`mono ${hClass} ${className}`}>{value}</span>;
}

/* ── Evidence Chip ── */
export function EvidenceChip({ id }: { id: string }) {
  return <span className="evidence-chip" title={id}>{id}</span>;
}

/* ── Metric ── */
export function Metric(
  { label, value, sub, provenance }:
  { label: string; value: ReactNode; sub?: ReactNode; provenance?: string }
) {
  return (
    <div className="metric">
      <span className="metric-label">
        {label}
        {provenance && <ProvenanceBadge type={provenance as any} />}
      </span>
      <span className="metric-value">{value ?? UNAVAILABLE}</span>
      {sub != null && <span className="dim text-xs">{sub}</span>}
    </div>
  );
}

/* ── Delta ── */
export function Delta(
  { value, suffix = "", invert = false }:
  { value: number | null | undefined; suffix?: string; invert?: boolean }
) {
  if (value == null) return <span className="dim">—</span>;
  const good = invert ? value > 0 : value < 0;
  const cls = good ? "delta-good" : value === 0 ? "dim" : "delta-bad";
  const sign = value > 0 ? "+" : "";
  return (
    <span className={`delta ${cls}`}>
      {sign}{value.toFixed(3)}{suffix}
    </span>
  );
}

/* ── Data Freshness ── */
export function DataFreshness({ ageMs }: { ageMs: number | null }) {
  if (ageMs == null) return <span className="freshness disconnected"><span className="freshness-dot" /> —</span>;
  const s = Math.round(ageMs / 1000);
  const cls = s < 3 ? "live" : s < 10 ? "delayed" : "stale";
  return (
    <span className={`freshness ${cls}`}>
      <span className="freshness-dot" />
      {s < 3 ? "LIVE" : `${s}s`}
    </span>
  );
}

/* ── Battle State Badge ── */
export function BattleStateBadge({ state }: { state: string }) {
  const s = state.toLowerCase();
  return <span className={`battle-state-badge ${s}`}>{state.replace(/_/g, " ")}</span>;
}

/* ── Nav Rail ── */
const NAV_ITEMS = [
  { id: "timing",   icon: "⊞", label: "TIM" },
  { id: "circuit",  icon: "◎", label: "MAP" },
  { id: "telemetry",icon: "⌇", label: "TEL" },
  { id: "strategy", icon: "⚙", label: "STR" },
  { id: "tyres",    icon: "●", label: "TYR" },
  { id: "battles",  icon: "⚔", label: "BTL" },
  { id: "ai",       icon: "◆", label: "AI" },
  { id: "events",   icon: "⚡", label: "EVT" },
] as const;

export function NavRail(
  { active, onNav }: { active: string; onNav: (id: string) => void }
) {
  return (
    <nav className="nav-rail" role="navigation" aria-label="Main navigation">
      {NAV_ITEMS.map(n => (
        <button key={n.id}
          className={`nav-item ${active === n.id ? "active" : ""}`}
          onClick={() => onNav(n.id)}
          aria-current={active === n.id ? "page" : undefined}
          title={n.label}
        >
          <span className="nav-icon">{n.icon}</span>
          <span className="nav-label">{n.label}</span>
        </button>
      ))}
    </nav>
  );
}
