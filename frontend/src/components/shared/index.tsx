/* Shared reusable components for the pit wall. */

import type { ReactNode } from "react";

/* ---- Panel ---- */
export function Panel({ title, children, className, actions }: {
  title: string; children: ReactNode; className?: string; actions?: ReactNode;
}) {
  return (
    <section className={`panel ${className ?? ""}`} aria-label={title}>
      <div className="panel-header">
        <h2>{title}</h2>
        {actions && <div className="panel-actions">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

/* ---- StatusBadge: color + text (a11y) ---- */
const STATUS_MAP: Record<string, { icon: string; color: string }> = {
  LIVE:        { icon: "\u25CF", color: "var(--live)" },
  REPLAY:      { icon: "\u25B6", color: "var(--info)" },
  CONNECTING:  { icon: "\u25CB", color: "var(--warning)" },
  DEGRADED:    { icon: "\u25B3", color: "var(--warning)" },
  DISCONNECTED:{ icon: "\u2715", color: "var(--text-muted)" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS_MAP[status] ?? STATUS_MAP.DISCONNECTED;
  return (
    <span className="status-badge" style={{ color: s.color, borderColor: s.color }}
          role="status" aria-label={`Session mode: ${status}`}>
      <span aria-hidden="true">{s.icon}</span> {status}
    </span>
  );
}

/* ---- ConfidenceBadge ---- */
export function ConfidenceBadge({ level }: { level: string }) {
  return <span className={`conf-badge conf-${level.toLowerCase()}`} title={`Confidence: ${level}`}>{level}</span>;
}

/* ---- TyreChip ---- */
const COMPOUND_COLOR: Record<string, string> = {
  S: "var(--tyre-soft)", M: "var(--tyre-medium)",
  H: "var(--tyre-hard)", I: "var(--tyre-inter)", W: "var(--tyre-wet)",
};

export function TyreChip({ compound, age }: { compound?: string | null; age?: number | null }) {
  if (!compound || compound === "UNKNOWN") {
    return <span className="tyre-chip dim">{`\u2014`}</span>;
  }
  const letter = compound[0];
  const color = COMPOUND_COLOR[letter] ?? "var(--text-secondary)";
  return (
    <span className="tyre-chip">
      <span className="tyre-dot" style={{ borderColor: color }} aria-hidden="true">{letter}</span>
      {age != null ? <span className="tyre-age">{age}</span> : null}
    </span>
  );
}

/* ---- TimingValue: monospaced, never jumps ---- */
export function TimingValue({ value, digits = 3, prefix = "" }: {
  value: number | null | undefined; digits?: number; prefix?: string;
}) {
  if (value == null) return <span className="timing-value unavailable">\u2014</span>;
  return <span className="timing-value">{prefix}{value.toFixed(digits)}</span>;
}

/* ---- EvidenceChip ---- */
export function EvidenceChip({ id, statement }: { id: string; statement: string }) {
  return (
    <button type="button" className="evidence-chip" title={statement}
            onClick={() => navigator.clipboard?.writeText(`[${id}] ${statement}`)}>
      [{id}]
    </button>
  );
}

/* ---- Metric (label + value pair) ---- */
export function Metric({ label, value, mono = true }: {
  label: string; value: ReactNode; mono?: boolean;
}) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <span className={`metric-value ${mono ? "mono" : ""}`}>{value ?? `\u2014`}</span>
    </div>
  );
}

/* ---- Delta indicator with direction ---- */
export function Delta({ value, unit = "s", digits = 3, invert = false }: {
  value: number | null | undefined; unit?: string; digits?: number; invert?: boolean;
}) {
  if (value == null) return <span className="dim">{`\u2014`}</span>;
  const positive = value > 0;
  const good = invert ? !positive : positive;
  return (
    <span className={`delta ${good ? "delta-good" : "delta-bad"}`}>
      {positive ? "+" : ""}{value.toFixed(digits)}{unit}
    </span>
  );
}
