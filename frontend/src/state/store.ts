import { useSyncExternalStore, useMemo, useCallback, useState, useEffect } from "react";
import { SessionSocket, SessionState } from "../ws/socket";

let socket: SessionSocket | null = null;
const hasBrowser = typeof location !== "undefined" && typeof WebSocket !== "undefined";
const defaultSessionId =
  (hasBrowser
    ? new URLSearchParams(location.search).get("session")
    : null) ?? "openf1:11353";

export function getSessionSocket(): SessionSocket {
  if (!socket) {
    const wsUrl = hasBrowser
      ? `${location.protocol === "https:" ? "wss://" : "ws://"}${location.host}/ws/session/${encodeURIComponent(defaultSessionId)}`
      : `ws://localhost/ws/session/${defaultSessionId}`;
    socket = new SessionSocket(wsUrl, defaultSessionId);
    if (hasBrowser) socket.connect();
  }
  return socket;
}

export function useSessionState(): SessionState {
  const sock = getSessionSocket();
  return useSyncExternalStore(
    (cb) => sock.subscribe(cb),
    () => sock.getState(),
  );
}

/* ── Driver selection state (app-level) ── */
let _driverState = { selected: null as number | null, comparison: null as number | null };
let _driverListeners: Set<() => void> = new Set();

function notifyDriverListeners() {
  _driverListeners.forEach((fn) => fn());
}

export function selectDriver(num: number | null) {
  if (_driverState.selected === num) return;
  _driverState = { ..._driverState, selected: num };
  notifyDriverListeners();
}

export function selectComparisonDriver(num: number | null) {
  if (_driverState.comparison === num) return;
  _driverState = { ..._driverState, comparison: num };
  notifyDriverListeners();
}

export function useDriverSelection(): {
  selectedDriver: number | null;
  comparisonDriver: number | null;
  selectDriver: (num: number | null) => void;
  selectComparisonDriver: (num: number | null) => void;
} {
  const snap = useSyncExternalStore(
    (cb) => { _driverListeners.add(cb); return () => { _driverListeners.delete(cb); }; },
    () => _driverState,
  );
  return {
    selectedDriver: snap.selected,
    comparisonDriver: snap.comparison,
    selectDriver,
    selectComparisonDriver,
  };
}

/* ── Intelligence REST fetching ── */
export function useIntelligence(sessionId: string | undefined) {
  const [intel, setIntel] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!sessionId) { setIntel(null); return; }
    let alive = true;
    let timer: ReturnType<typeof setInterval>;

    const fetch_ = () => {
      setLoading(true);
      apiGet(`/sessions/${encodeURIComponent(sessionId)}/intelligence`)
        .then((d) => { if (alive) setIntel(d); })
        .catch(() => {})
        .finally(() => { if (alive) setLoading(false); });
    };

    fetch_();
    // Refresh every 5 seconds
    timer = setInterval(fetch_, 5000);

    return () => { alive = false; clearInterval(timer); };
  }, [sessionId]);

  return { intel, loading };
}

/* ── Sector data fetching ── */
export function useSectors(sessionId: string | undefined, driver: number | null) {
  const [sectors, setSectors] = useState<any>(null);

  useEffect(() => {
    if (!sessionId || !driver) { setSectors(null); return; }
    let alive = true;
    apiGet(`/sessions/${encodeURIComponent(sessionId)}/sectors/${driver}`)
      .then((d) => { if (alive) setSectors(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, [sessionId, driver]);

  return sectors;
}

/* ── Pace data fetching ── */
export function usePace(sessionId: string | undefined, driver: number | null) {
  const [pace, setPace] = useState<any>(null);

  useEffect(() => {
    if (!sessionId || !driver) { setPace(null); return; }
    let alive = true;
    apiGet(`/sessions/${encodeURIComponent(sessionId)}/pace/${driver}`)
      .then((d) => { if (alive) setPace(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, [sessionId, driver]);

  return pace;
}

/** REST helpers (same origin, proxied by vite in dev). */
export async function apiGet(path: string): Promise<any> {
  const r = await fetch(`/api/v1${path}`);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export async function apiPost(path: string, body: any): Promise<any> {
  const r = await fetch(`/api/v1${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

/** Ask the AI race engineer; polls the job until terminal status. */
export async function askAI(sessionId: string, question: string): Promise<any> {
  const { job_id } = await apiPost(
    `/sessions/${encodeURIComponent(sessionId)}/ai/ask`, { question });
  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 250));
    const job = await apiGet(`/ai/jobs/${job_id}`);
    if (["DONE", "FALLBACK", "REJECTED", "FAILED", "STALE"].includes(job.status)) {
      return job;
    }
  }
  throw new Error("AI job timeout");
}

export function useEvents(sessionId: string | undefined) {
  const [events, setEvents] = useState<any[]>([]);
  useEffect(() => {
    if (!sessionId) return;
    apiGet(`/sessions/${encodeURIComponent(sessionId)}/events`)
      .then((data) => setEvents(data?.events ?? []))
      .catch(() => {});
  }, [sessionId]);
  return events;
}
