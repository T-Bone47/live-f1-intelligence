/**
 * Phase 10.6 — Evidence Workbench (/evidence).
 *
 * Container: owns the URL-backed request, server state (useEvidence) and UI
 * state (selected segment, drill-down, selector open). Every analytical value
 * comes from evidence_v1; components render, format and navigate it.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  draftFromSearch, sameRequest, searchFromState, selectedLabelFromSearch, validateDraft,
  type DraftErrors, type EvidenceRequest, type RequestDraft,
} from "../../evidence/request";
import { useEvidence } from "../../evidence/useEvidence";
import { buildView, stepLabel } from "../../evidence/viewModel";
import { AccountingSummary } from "./AccountingSummary";
import { ComparisonForm } from "./ComparisonForm";
import { ComparisonHeader } from "./ComparisonHeader";
import { DeltaChart } from "./DeltaChart";
import { DrilldownTelemetry } from "./DrilldownTelemetry";
import { EvidenceEmptyState, EvidenceErrorState, EvidenceLoadingState } from "./EvidenceStates";
import { CaveatStrip, LimitationsPanel } from "./LimitationsPanel";
import { Icon, Section } from "./primitives";
import { ProvenancePanel } from "./ProvenancePanel";
import { InvestigateWithRaceWiseButton } from "./RaceWiseButton";
import { SectorEvidence } from "./SectorEvidence";
import { SegmentInspector } from "./SegmentInspector";
import { SegmentTimeline } from "./SegmentTimeline";
import "./evidence.css";

function initialRequest(search: string): EvidenceRequest | null {
  const v = validateDraft(draftFromSearch(search));
  return v.ok ? v.request : null;
}

function isTyping(el: EventTarget | null): boolean {
  const t = el as HTMLElement | null;
  return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
}

export function EvidenceWorkbench({ search = typeof location !== "undefined" ? location.search : "" }: { search?: string }) {
  const [draft, setDraft] = useState<RequestDraft>(() => draftFromSearch(search));
  const [errors, setErrors] = useState<DraftErrors>({});
  const [request, setRequest] = useState<EvidenceRequest | null>(() => initialRequest(search));
  const [selected, setSelected] = useState<string | null>(() => selectedLabelFromSearch(search));
  const [reloadKey, setReloadKey] = useState(0);
  const [drillOpen, setDrillOpen] = useState(false);
  const [formOpen, setFormOpen] = useState(() => initialRequest(search) == null);

  const state = useEvidence(request, reloadKey);
  const data = state.status === "success" ? state.data : state.status === "loading" ? state.previous : null;
  const view = useMemo(() => (data ? buildView(data.evidence) : null), [data]);
  const sel = view && selected && view.byLabel.has(selected) ? selected : null;
  const segment = sel && view ? view.byLabel.get(sel) ?? null : null;
  // Until evidence arrives the requested label cannot be checked; keep it in the URL meanwhile.
  const urlSel = view ? sel : selected;

  const draftCheck = useMemo(() => validateDraft(draft), [draft]);
  const stale = !!request && (!draftCheck.ok || !sameRequest(draftCheck.request, request));

  useEffect(() => {
    if (typeof history === "undefined") return;
    history.replaceState(null, "", `${location.pathname}${searchFromState(request, urlSel)}`);
  }, [request, urlSel]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.title = request
      ? `Evidence · #${request.driverA} L${request.lapA} vs #${request.driverB} L${request.lapB}${urlSel ? ` · ${urlSel}` : ""}`
      : "Evidence Workbench · Live F1 Intelligence";
  }, [request, urlSel]);

  const select = useCallback((label: string | null) => setSelected(label), []);
  const step = useCallback((n: number) => {
    if (view) setSelected((cur) => stepLabel(view.segments, cur && view.byLabel.has(cur) ? cur : null, n));
  }, [view]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!view || isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "]") step(1);
      else if (e.key === "[") step(-1);
      else if (e.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, step]);

  const submit = () => {
    const v = validateDraft(draft);
    if (!v.ok) { setErrors(v.errors); setFormOpen(true); return; }
    setErrors({});
    setFormOpen(false);
    if (sameRequest(v.request, request)) setReloadKey((k) => k + 1);
    else setRequest(v.request);
  };

  const showAllLimitations = () => {
    const heading = document.getElementById("ewb-limitations-title");
    heading?.scrollIntoView?.({ block: "start" });
    heading?.focus({ preventScroll: true });
  };

  const summaryText = request
    ? `#${request.driverA} lap ${request.lapA} vs #${request.driverB} lap ${request.lapB} · ${request.sessionId}`
    : "No comparison selected";

  return (
    <div className="ewb" data-testid="evidence-workbench">
      <a className="ewb-skip" href="#ewb-main">Skip to evidence</a>
      <header className="ewb-bar">
        <a href="/" className="ewb-back"><Icon name="arrowLeft" />Pit wall</a>
        <p className="ewb-product">Live F1 Intelligence <span>/ Evidence Workbench</span></p>
        <p className="ewb-bar-meta">evidence_v1 · lap comparison</p>
      </header>

      <main id="ewb-main" className="ewb-main" tabIndex={-1}>
        <details className="ewb-selector" open={formOpen} onToggle={(e) => setFormOpen((e.currentTarget as HTMLDetailsElement).open)}>
          <summary>
            <Icon name="chevronDown" />
            <span className="ewb-label">Comparison</span>
            <span className="ewb-mono ewb-selector-sum">{summaryText}</span>
            {stale && <span className="ewb-stale-dot">edited</span>}
          </summary>
          <ComparisonForm draft={draft} errors={errors} stale={stale} busy={state.status === "loading"}
                          onChange={setDraft} onSubmit={submit} />
        </details>

        {state.status === "idle" && <EvidenceEmptyState />}
        {state.status === "loading" && !view && <EvidenceLoadingState />}
        {state.status === "error" && <EvidenceErrorState error={state.error} onRetry={() => setReloadKey((k) => k + 1)} />}

        {view && state.status !== "error" && (
          <div className={`ewb-body ${state.status === "loading" ? "is-refreshing" : ""}`} aria-busy={state.status === "loading" || undefined}>
            {state.status === "loading" && <p className="ewb-refreshing" role="status">Loading the new comparison — showing the previous evidence meanwhile.</p>}
            <ComparisonHeader view={view} />
            <CaveatStrip view={view} onShowAll={showAllLimitations} />

            <div className="ewb-grid">
              <Section id="ewb-delta" className="ewb-area-chart" title="Δt over normalized lap distance" eyebrow="Where the gap changed">
                <DeltaChart view={view} selected={sel} onSelect={select} onStep={step} />
              </Section>
              <Section id="ewb-segments" className="ewb-area-timeline" title="Segment timeline"
                       eyebrow={`${view.segments.length} segments · straight to straight`}>
                <SegmentTimeline view={view} selected={sel} onSelect={select} />
              </Section>
              <div className="ewb-area-side">
                <SegmentInspector view={view} segment={segment} onStep={step} onClear={() => select(null)}
                                  drillOpen={drillOpen} onToggleDrill={() => setDrillOpen((o) => !o)} />
                <InvestigateWithRaceWiseButton evidence={view.evidence} focusSegmentIds={segment ? [segment.segment_id] : []} />
              </div>
              {drillOpen && segment && (
                <div className="ewb-area-drill">
                  <DrilldownTelemetry key={segment.segment_id} view={view} segment={segment} onClose={() => setDrillOpen(false)} />
                </div>
              )}
              <div className="ewb-area-sectors ewb-stack">
                <Section id="ewb-sectors" title="Sectors" eyebrow="Official (B) and engine (C), never merged">
                  <SectorEvidence view={view} selected={sel} onSelect={select} />
                </Section>
                <Section id="ewb-accounting" title="Accounting" eyebrow="Covered delta change">
                  <AccountingSummary view={view} />
                </Section>
              </div>
            </div>

            <div className="ewb-two ewb-foot">
              <Section id="ewb-limitations" title="Limitations" eyebrow="What this evidence cannot say">
                <LimitationsPanel view={view} />
              </Section>
              <Section id="ewb-provenance" title="Provenance" eyebrow="Lineage and identity">
                <ProvenancePanel view={view} serverTiming={data?.serverTiming ?? null} />
              </Section>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
