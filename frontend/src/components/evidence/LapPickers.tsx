/**
 * Lap pickers (Phase 12C): choose the comparison from the backend's lists
 * instead of typing ids. Sessions come from /sessions (stored and recorded,
 * so they work with the database down), drivers and laps from /laps. Only
 * laps with a time and stored car telemetry can be chosen. When the session
 * has a validated track, the lap length and its citation are prefilled from
 * the track's cited circuit length - never guessed, and only into empty
 * fields. Nothing is requested until the pickers are opened.
 */

import { useEffect, useMemo, useState } from "react";
import { ApiError, fetchLapCatalog, fetchSessionCatalog } from "../../command/api";
import { fmtLapTime } from "../../command/format";
import type { LapCatalog, SessionCatalog } from "../../command/types";
import type { RequestDraft } from "../../evidence/request";
import { fetchTrack } from "../../spatial/api";
import type { TrackReference } from "../../spatial/types";

interface Option { id: string; label: string }

function sessionOptions(c: SessionCatalog): Option[] {
  const seen = new Map<string, Option>();
  const add = (id: string, circuit: string | null, year: number | null, name: string | null, tag: string) => {
    if (!seen.has(id)) seen.set(id, { id, label: `${circuit ?? "Unknown circuit"} ${year ?? ""} · ${name ?? "session"} · ${id}${tag}` });
  };
  for (const r of c.recorded ?? []) add(r.session_id, r.circuit_short_name, r.year, r.session_name ?? r.session_type, " · recording");
  for (const s of c.stored) add(s.session_id, s.circuit_short_name, s.year, s.session_name ?? s.session_type, "");
  return [...seen.values()];
}

export function LapPickers({ draft, onChange }: { draft: RequestDraft; onChange: (d: RequestDraft) => void }) {
  const [open, setOpen] = useState(false);
  const [sessions, setSessions] = useState<{ value: SessionCatalog | null; error: ApiError | null } | null>(null);
  const [laps, setLaps] = useState<{ sid: string; value: LapCatalog | null; error: ApiError | null } | null>(null);
  const [track, setTrack] = useState<{ sid: string; value: TrackReference | null } | null>(null);
  const sid = draft.sessionId.trim();

  useEffect(() => {
    if (!open || sessions) return undefined;
    const ctrl = new AbortController();
    fetchSessionCatalog(ctrl.signal).then((value) => setSessions({ value, error: null }), (e: unknown) => {
      if ((e as Error)?.name !== "AbortError") setSessions({ value: null, error: e as ApiError });
    });
    return () => ctrl.abort();
  }, [open, sessions]);

  useEffect(() => {
    if (!open || !sid || laps?.sid === sid) return undefined;
    const ctrl = new AbortController();
    fetchLapCatalog(sid, ctrl.signal).then((value) => setLaps({ sid, value, error: null }), (e: unknown) => {
      if ((e as Error)?.name !== "AbortError") setLaps({ sid, value: null, error: e as ApiError });
    });
    fetchTrack(sid, ctrl.signal).then((value) => setTrack({ sid, value }), (e: unknown) => {
      if ((e as Error)?.name !== "AbortError") setTrack({ sid, value: null });
    });
    return () => ctrl.abort();
  }, [open, sid, laps?.sid]);

  // prefill the cited circuit length of a validated track into empty fields only
  const cited = track?.sid === sid && track.value?.status === "VALIDATED_MAP_SECTOR" ? track.value.circuit : null;
  useEffect(() => {
    if (!open || !cited?.lap_length_m || !cited.lap_length_source) return;
    if (draft.lapLengthM.trim() || draft.lapLengthSource.trim()) return;
    onChange({ ...draft, lapLengthM: String(cited.lap_length_m), lapLengthSource: cited.lap_length_source });
  }, [open, cited, draft, onChange]);

  const options = useMemo(() => (sessions?.value ? sessionOptions(sessions.value) : []), [sessions]);
  const catalog = laps?.sid === sid ? laps.value : null;
  const eligible = (driver: string) => catalog?.drivers.find((d) => String(d.driver_number) === driver)?.laps
    .filter((l) => l.duration_s != null && l.has_car_telemetry) ?? [];

  if (!open) {
    return (
      <button type="button" className="ewb-btn ewb-btn-ghost ewb-pick-open" onClick={() => setOpen(true)}>
        Pick laps from a session
      </button>
    );
  }

  const side = (k: "A" | "B") => {
    const car = k === "A" ? draft.driverA : draft.driverB;
    const lap = k === "A" ? draft.lapA : draft.lapB;
    const setCar = (v: string) => onChange(k === "A" ? { ...draft, driverA: v, lapA: "" } : { ...draft, driverB: v, lapB: "" });
    const setLap = (v: string) => onChange(k === "A" ? { ...draft, lapA: v } : { ...draft, lapB: v });
    return (
      <fieldset className={`ewb-pair ewb-pair-${k.toLowerCase()}`}>
        <legend className="ewb-label"><span className="ewb-driver-mono" aria-hidden="true">{k}</span> Driver {k}</legend>
        <select aria-label={`Driver ${k} car`} className="ewb-input" value={car} onChange={(e) => setCar(e.target.value)}
                disabled={!catalog}>
          <option value="">Car…</option>
          {(catalog?.drivers ?? []).map((d) => (
            <option key={d.driver_number} value={d.driver_number}>#{d.driver_number} {d.acronym ?? ""}</option>
          ))}
        </select>
        <select aria-label={`Driver ${k} lap`} className="ewb-input ewb-mono" value={lap} onChange={(e) => setLap(e.target.value)}
                disabled={!eligible(car).length}>
          <option value="">Lap…</option>
          {eligible(car).map((l) => (
            <option key={l.lap_number} value={l.lap_number}>
              L{l.lap_number} · {fmtLapTime(l.duration_s)}{l.is_pit_out_lap ? " · pit out" : ""}{l.deleted === true ? " · deleted" : ""}
            </option>
          ))}
        </select>
      </fieldset>
    );
  };

  return (
    <div className="ewb-pickers">
      <label className="ewb-field is-wide">
        <span className="ewb-label">Session</span>
        <select aria-label="Session" className="ewb-input" value={sid}
                onChange={(e) => onChange({ ...draft, sessionId: e.target.value, driverA: "", lapA: "", driverB: "", lapB: "",
                                            lapLengthM: "", lapLengthSource: "" })}>
          <option value="">{sessions ? "Choose a session…" : "Loading sessions…"}</option>
          {sid && !options.some((o) => o.id === sid) && <option value={sid}>{sid}</option>}
          {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
      </label>
      {sessions?.error && <p className="ewb-field-error">Sessions could not be listed: {sessions.error.message}</p>}
      {laps?.sid === sid && laps.error && <p className="ewb-field-error">Laps could not be listed: {laps.error.message}</p>}
      {side("A")}
      {side("B")}
      <p className="ewb-field-hint">
        Only laps with a time and stored car telemetry are offered.
        {cited ? ` Lap length prefilled from the validated track: ${cited.lap_length_m} m (${cited.lap_length_source}).`
               : " Without a validated track, enter the lap length with its citation."}
      </p>
    </div>
  );
}
