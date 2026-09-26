/**
 * Application shell (Phase 11): one persistent header for every surface, the
 * session context line, and the keyboard-shortcut help. Four destinations
 * only: Command center, Sessions, Evidence, Pit wall (legacy live view).
 */

import { useEffect, useRef, type ReactNode } from "react";
import { flagLabel, fmtDate, phaseLabel, phaseTone } from "../../command/format";
import type { Moment } from "../../command/moment";
import { Badge, Icon } from "./ui";

export type Destination = "command" | "sessions" | "evidence" | "pitwall";

const NAV: { id: Destination; label: string; href: string; title: string }[] = [
  { id: "command", label: "Command center", href: "/", title: "Race intelligence command center" },
  { id: "sessions", label: "Sessions", href: "/sessions", title: "Stored and live sessions" },
  { id: "evidence", label: "Evidence", href: "/evidence", title: "Lap comparison evidence workbench" },
  { id: "pitwall", label: "Pit wall", href: "/pitwall", title: "Legacy live pit wall (realtime socket)" },
];

export type Mode = { kind: "historical"; replaying: boolean } | { kind: "live"; connected: boolean } | { kind: "none" };

function ModeBadge({ mode }: { mode: Mode }) {
  if (mode.kind === "live") {
    return mode.connected
      ? <Badge tone="live" title="Connected to a running session"><span className="cc-live-dot" aria-hidden="true" />LIVE</Badge>
      : <Badge tone="warning" title="The live connection is not established">RECONNECTING</Badge>;
  }
  if (mode.kind === "historical") {
    return (
      <span className="cc-mode">
        <Badge tone="historical" title="Recorded session - not live"><Icon name="history" size={12} />HISTORICAL</Badge>
        {mode.replaying && <Badge tone="replay" title="Viewing an earlier moment of the recording">REPLAY</Badge>}
      </span>
    );
  }
  return null;
}

export function AppHeader({ active, mode, commandHref, onHelp }: {
  active: Destination; mode: Mode; commandHref?: string; onHelp?: () => void;
}) {
  return (
    <header className="cc-appbar">
      <a className="cc-skip" href="#cc-main">Skip to content</a>
      <a className="cc-brand" href="/" aria-label="Live F1 Intelligence, command center">
        <span className="cc-brand-mark" aria-hidden="true" />
        <span className="cc-brand-name">LIVE F1 <span>INTELLIGENCE</span></span>
      </a>
      <nav className="cc-nav" aria-label="Primary">
        {NAV.map((n) => (
          <a key={n.id} href={n.id === "command" && commandHref ? commandHref : n.href} title={n.title}
             className={`cc-nav-link${active === n.id ? " is-active" : ""}`}
             aria-current={active === n.id ? "page" : undefined}>
            {n.label}
          </a>
        ))}
      </nav>
      <div className="cc-appbar-right">
        <ModeBadge mode={mode} />
        {onHelp && (
          <button type="button" className="cc-btn cc-btn-icon cc-btn-ghost" onClick={onHelp} aria-label="Keyboard shortcuts">
            <Icon name="keyboard" size={15} />
          </button>
        )}
      </div>
    </header>
  );
}

export function SessionHeader({ moment }: { moment: Moment }) {
  const s = moment.timeline.session;
  const place = [s?.country_name, s?.circuit_short_name].filter(Boolean).join(" · ") || "Session";
  const tone = phaseTone(moment.frame.phase);
  const lapText = moment.isStart ? "START" : moment.isFinal ? "FINAL" : `LAP ${moment.lap}`;
  return (
    <div className="cc-session">
      <div className="cc-session-id">
        <p className="cc-eyebrow">{[s?.year, s?.session_name ?? s?.session_type].filter(Boolean).join(" · ")} · {fmtDate(s?.date_start)}</p>
        <h1 className="cc-session-title">{place}</h1>
        {s?.meeting_name == null && <p className="cc-sr">Event name not recorded by the provider.</p>}
      </div>
      <div className="cc-session-lap" aria-label={`${lapText}${moment.totalLaps && !moment.isFinal ? ` of ${moment.totalLaps}` : ""}`}>
        <span className="cc-lap-big">{lapText}</span>
        {moment.totalLaps != null && !moment.isFinal && <span className="cc-lap-total">/ {moment.totalLaps}</span>}
      </div>
      <div className="cc-session-state">
        <Badge tone={tone === "neutral" ? "neutral" : tone} title="Session phase from race control">
          <Icon name="flag" size={12} />{phaseLabel(moment.frame.phase)}
        </Badge>
        <span className="cc-small cc-muted">Track flag · {flagLabel(moment.frame.track_flag)}</span>
      </div>
    </div>
  );
}

const SHORTCUTS: [string, string][] = [
  ["Space / K", "Play or pause the replay"],
  ["← / →", "Previous / next lap"],
  ["Home / End", "Start / end of the recording"],
  ["↑ / ↓", "Move between drivers in the timing tower"],
  ["Enter", "Focus the highlighted driver"],
  ["Esc", "Clear the selection, close this dialog"],
  ["?", "Show these shortcuts"],
];

export function ShortcutHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const back = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (open) {
      back.current = document.activeElement as HTMLElement | null;
      ref.current?.focus();
    } else {
      back.current?.focus?.();
    }
  }, [open]);
  if (!open) return null;
  return (
    <div className="cc-dialog-scrim" onClick={onClose}>
      <div ref={ref} className="cc-dialog" role="dialog" aria-modal="true" aria-labelledby="cc-help-title" tabIndex={-1}
           onClick={(e) => e.stopPropagation()}
           onKeyDown={(e) => {
             if (e.key === "Escape") { e.preventDefault(); onClose(); }
             // one focusable control inside: Tab keeps focus in the dialog
             else if (e.key === "Tab") { e.preventDefault(); ref.current?.querySelector<HTMLElement>("button")?.focus(); }
           }}>
        <div className="cc-dialog-head">
          <h2 id="cc-help-title" className="cc-panel-title">Keyboard shortcuts</h2>
          <button type="button" className="cc-btn cc-btn-icon cc-btn-ghost" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
        </div>
        <dl className="cc-shortcuts">
          {SHORTCUTS.map(([k, v]) => <div key={k}><dt><kbd>{k}</kbd></dt><dd>{v}</dd></div>)}
        </dl>
      </div>
    </div>
  );
}

export function Page({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`cc ${className}`}>{children}</div>;
}
