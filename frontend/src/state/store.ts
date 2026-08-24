import { useSyncExternalStore } from "react";
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
