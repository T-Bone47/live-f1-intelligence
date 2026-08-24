/**
 * SessionSocket: owns the WebSocket connection, applies the snapshot protocol
 * (f1intel-snapshot-1): snapshot -> deltas, sequence validation, resume.
 * Components never touch the socket directly (data-layer rule).
 */

export type ConnStatus =
  | "CONNECTING"
  | "LIVE"
  | "REPLAY"
  | "DEGRADED"
  | "DISCONNECTED";

export interface SessionState {
  sessionId: string;
  status: ConnStatus;
  seq: number;
  snapshot: any | null;          // full projection dict from backend
  recentEvents: any[];           // significant events (append-only tail)
  telemetry: Record<number, any>; // latest coalesced sample per driver
  lastUpdate: string | null;
  aiInsights: any[];             // kind=ai frames (chronological tail)
}

type Listener = () => void;

const CRITICAL_TYPES = new Set([
  "SAFETY_CAR", "VSC", "RED_FLAG", "SESSION_STATE_CHANGE",
  "OVERTAKE", "FASTEST_LAP_CHANGE",
]);

export function applyDelta(state: SessionState, changes: Record<string, unknown>): void {
  for (const [path, value] of Object.entries(changes)) {
    setPath(state.snapshot as any, path, value);
  }
}

export function applyRemovals(state: SessionState, removed: string[]): void {
  for (const path of removed) deletePath(state.snapshot as any, path);
}

function setPath(obj: any, path: string, value: unknown): void {
  const parts = path.split(".");
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    const key = parts[i];
    if (cur[key] === undefined || cur[key] === null) cur[key] = {};
    cur = cur[key];
  }
  cur[parts[parts.length - 1]] = value;
}

function deletePath(obj: any, path: string): void {
  const parts = path.split(".");
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    cur = cur?.[parts[i]];
    if (cur === undefined) return;
  }
  delete cur[parts[parts.length - 1]];
}

export class SessionSocket {
  private ws: WebSocket | null = null;
  private state: SessionState;
  private listeners = new Set<Listener>();
  private url: string;
  private closedByUser = false;

  constructor(url: string, initialSessionId: string) {
    this.url = url;
    this.state = {
      sessionId: initialSessionId,
      status: "CONNECTING",
      seq: 0,
      snapshot: null,
      recentEvents: [],
      aiInsights: [],
      telemetry: {},
      lastUpdate: null,
    };
  }

  getState(): SessionState {
    return this.state;
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(): void {
    this.state = { ...this.state };
    this.listeners.forEach((fn) => fn());
  }

  connect(): void {
    this.closedByUser = false;
    this.setStatus("CONNECTING");
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      /* snapshot arrives immediately after open */
    };

    ws.onmessage = (ev) => {
      try {
        this.handleMessage(JSON.parse(ev.data));
      } catch {
        /* malformed frame ignored - backend contract guarantees JSON */
      }
    };

    ws.onclose = () => {
      if (!this.closedByUser) {
        this.setStatus("DISCONNECTED");
        setTimeout(() => this.connect(), 2000); // auto-reconnect + resume
      }
    };

    ws.onerror = () => ws.close();
  }

  send(msg: object): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  close(): void {
    this.closedByUser = true;
    this.ws?.close();
  }

  private setStatus(s: ConnStatus): void {
    this.state.status = s;
    this.emit();
  }

  private handleGap(): void {
    // sequence gap -> ask server to replay history or send fresh snapshot
    this.send({ action: "resume", last_seq: this.state.seq });
  }

  handleMessage(msg: any): void {
    switch (msg.kind) {
      case "snapshot": {
        this.state.snapshot = msg.data;
        this.state.recentEvents = msg.data?.recent_events ?? [];
        this.state.seq = msg.seq;
        this.state.lastUpdate = msg.ts ?? null;
        const sid: string = msg.session_id ?? this.state.sessionId;
        this.state.status = sid.startsWith("replay:") ? "REPLAY" : "LIVE";
        break;
      }
      case "delta": {
        const incoming: number = msg.seq;
        if (incoming > this.state.seq + 1) {
          this.handleGap();
          return; // stale until resync completes
        }
        if (incoming <= this.state.seq) return; // duplicate/stale
        applyDelta(this.state, msg.changes ?? {});
        applyRemovals(this.state, msg.removed ?? []);
        this.state.seq = incoming;
        this.state.lastUpdate = msg.ts ?? null;
        if (msg.events?.length) this.appendEvents(msg.events);
        break;
      }
      case "events": {
        for (const e of msg.events ?? []) {
          if (CRITICAL_TYPES.has(e.event_type) || msg.critical) {
            this.appendEvents([e]);
            // critical events also mutate authoritative snapshot fields via
            // the next delta; nothing to patch here beyond the feed panel
          }
        }
        break;
      }
      case "ai": {
        const insight = { ...msg, _received: new Date().toISOString() };
        this.state.aiInsights = [...this.state.aiInsights.slice(-40), insight];
        break;
      }
      case "telemetry": {
        this.state.telemetry[msg.driver] = msg.samples?.[0] ?? null;
        break;
      }
      case "pong":
        break;
      default:
        break;
    }
    this.emit();
  }

  private appendEvents(events: any[]): void {
    const existing = new Set(this.state.recentEvents.map((e) => e.event_key));
    for (const e of events) {
      if (!existing.has(e.event_key)) {
        this.state.recentEvents.push(e);
        existing.add(e.event_key);
      }
    }
    if (this.state.recentEvents.length > 60) {
      this.state.recentEvents.splice(0, this.state.recentEvents.length - 60);
    }
    this.state.snapshot = {
      ...(this.state.snapshot ?? {}),
      recent_events: [...this.state.recentEvents].reverse(),
    };
  }
}
