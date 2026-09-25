/**
 * Comparison selector. There is no stored-laps listing route, so the fields
 * are typed; the one validated real pair is offered as a preset. Swapping A
 * and B only swaps the request — the backend negates every change.
 */

import type { FormEvent } from "react";
import {
  MAX_SOURCE_CHARS, REAL_PAIR_PRESET, swapDraft,
  type DraftErrors, type DraftField, type RequestDraft,
} from "../../evidence/request";
import { Icon } from "./primitives";

interface Props {
  draft: RequestDraft;
  errors: DraftErrors;
  stale: boolean;
  busy: boolean;
  onChange: (d: RequestDraft) => void;
  onSubmit: () => void;
}

function Field({ id, label, value, error, onChange, hint, mono = true, inputMode, wide }: {
  id: DraftField; label: string; value: string; error?: string; onChange: (v: string) => void;
  hint?: string; mono?: boolean; inputMode?: "numeric" | "decimal" | "text"; wide?: boolean;
}) {
  const errId = `ewb-f-${id}-err`;
  return (
    <div className={`ewb-field ${wide ? "is-wide" : ""} ${error ? "has-error" : ""}`}>
      <label htmlFor={`ewb-f-${id}`} className="ewb-label">{label}</label>
      <input id={`ewb-f-${id}`} className={`ewb-input ${mono ? "ewb-mono" : ""}`} value={value}
             inputMode={inputMode} autoComplete="off" spellCheck={false}
             maxLength={id === "lapLengthSource" ? MAX_SOURCE_CHARS : 64}
             aria-invalid={!!error} aria-describedby={error ? errId : undefined}
             onChange={(e) => onChange(e.target.value)} />
      {error ? <p id={errId} className="ewb-field-error">{error}</p> : hint ? <p className="ewb-field-hint">{hint}</p> : null}
    </div>
  );
}

export function ComparisonForm({ draft, errors, stale, busy, onChange, onSubmit }: Props) {
  const set = (k: DraftField) => (v: string) => onChange({ ...draft, [k]: v });
  const submit = (e: FormEvent) => { e.preventDefault(); onSubmit(); };
  return (
    <form className="ewb-form" onSubmit={submit} aria-label="Comparison selector" noValidate>
      <div className="ewb-form-grid">
        <Field id="sessionId" label="Session" value={draft.sessionId} error={errors.sessionId} onChange={set("sessionId")} hint="provider:key, e.g. openf1:9161" />
        <fieldset className="ewb-pair ewb-pair-a">
          <legend className="ewb-label"><span className="ewb-driver-mono" aria-hidden="true">A</span> Driver A</legend>
          <Field id="driverA" label="Car" value={draft.driverA} error={errors.driverA} onChange={set("driverA")} inputMode="numeric" />
          <Field id="lapA" label="Lap" value={draft.lapA} error={errors.lapA} onChange={set("lapA")} inputMode="numeric" />
        </fieldset>
        <button type="button" className="ewb-btn ewb-btn-icon ewb-swap" aria-label="Swap driver A and driver B"
                onClick={() => onChange(swapDraft(draft))}><Icon name="swap" /></button>
        <fieldset className="ewb-pair ewb-pair-b">
          <legend className="ewb-label"><span className="ewb-driver-mono" aria-hidden="true">B</span> Driver B</legend>
          <Field id="driverB" label="Car" value={draft.driverB} error={errors.driverB} onChange={set("driverB")} inputMode="numeric" />
          <Field id="lapB" label="Lap" value={draft.lapB} error={errors.lapB} onChange={set("lapB")} inputMode="numeric" />
        </fieldset>
        <Field id="lapLengthM" label="Lap length (m)" value={draft.lapLengthM} error={errors.lapLengthM} onChange={set("lapLengthM")} inputMode="decimal" />
        <Field id="lapLengthSource" label="Lap length citation" value={draft.lapLengthSource} error={errors.lapLengthSource}
               onChange={set("lapLengthSource")} mono={false} wide hint="Required: a length is never guessed." />
      </div>
      <div className="ewb-form-actions">
        <button type="submit" className="ewb-btn ewb-btn-primary" disabled={busy}>
          <Icon name="refresh" />{busy ? "Loading…" : "Load evidence"}
        </button>
        <button type="button" className="ewb-btn ewb-btn-ghost" onClick={() => onChange({ ...REAL_PAIR_PRESET.draft })}>
          Preset: {REAL_PAIR_PRESET.label}
        </button>
        {stale && <p className="ewb-stale" role="status"><Icon name="alert" size={12} />Selector differs from the loaded evidence — load to update.</p>}
      </div>
    </form>
  );
}
