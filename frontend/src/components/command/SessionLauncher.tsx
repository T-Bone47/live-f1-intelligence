/**
 * Sessions (Phase 11 discovery): running hubs and stored sessions, straight
 * from GET /api/v1/sessions. Metadata is shown as stored (no event name is
 * invented). A session opens in the command center when a timeline exists
 * (a running hub or a recording); otherwise the reason is stated.
 */

import { useState } from "react";
import { fetchSessionCatalog } from "../../command/api";
import { fmtDate } from "../../command/format";
import type { StoredSession } from "../../command/types";
import { dataOf, useResource } from "../../command/useResource";
import { AppHeader, Page } from "./Shell";
import { Badge, EmptyState, ErrorState, Icon, SkeletonRows } from "./ui";

function place(s: StoredSession): string {
  return [s.country_name, s.circuit_short_name].filter(Boolean).join(" · ") || s.location || s.session_id;
}

function SessionRow({ s }: { s: StoredSession }) {
  const href = `/?session=${encodeURIComponent(s.session_id)}`;
  return (
    <tr>
      <td className="cc-num">{fmtDate(s.date_start)}</td>
      <td>
        <span className="cc-strong">{place(s)}</span>
        <span className="cc-small cc-muted cc-block">{s.meeting_name ?? "event name not recorded"} · {s.session_id}</span>
      </td>
      <td>{[s.year, s.session_name ?? s.session_type].filter(Boolean).join(" · ") || "—"}</td>
      <td className="cc-num">{s.max_lap ?? "—"}</td>
      <td className="cc-num">{s.drivers}</td>
      <td>{s.has_car_telemetry ? <Badge tone="official">Recorded</Badge> : <span className="cc-muted cc-small">Not stored</span>}</td>
      <td>
        {s.timeline_available ? (
          <a className="cc-btn cc-btn-primary" href={href}>Open <Icon name="chevronRight" size={13} /></a>
        ) : (
          <span className="cc-small cc-muted" title="The command center needs a recording of this session or a running hub">No recording</span>
        )}
      </td>
    </tr>
  );
}

export function SessionLauncher() {
  const [reload, setReload] = useState(0);
  const res = useResource("catalog", (_k, signal) => fetchSessionCatalog(signal), reload);
  const data = dataOf(res);
  return (
    <Page>
      <AppHeader active="sessions" mode={{ kind: "none" }} />
      <main id="cc-main" className="cc-sessions" tabIndex={-1}>
        <header className="cc-sessions-head">
          <p className="cc-eyebrow">Discovery</p>
          <h1 className="cc-session-title">Sessions</h1>
          <p className="cc-muted">Stored sessions come from the database; a session opens in the command center when a recording or a running hub provides its lap timeline.</p>
        </header>
        {res.status === "error" && (
          <ErrorState title="Sessions could not be loaded" message={res.error.message} onRetry={() => setReload((r) => r + 1)} />
        )}
        {!data && res.status !== "error" && <SkeletonRows rows={6} label="Loading sessions" />}
        {data && (
          <>
            {data.active.length > 0 && (
              <section className="cc-panel" aria-labelledby="cc-active-title">
                <header className="cc-panel-head"><h2 id="cc-active-title" className="cc-panel-title">Running now</h2></header>
                <ul className="cc-active-list">
                  {data.active.map((a) => (
                    <li key={a.session_id}>
                      <a className="cc-btn" href={`/?session=${encodeURIComponent(a.session_id)}`}>
                        {a.session_id.startsWith("replay:") ? <Badge tone="replay">REPLAY STREAM</Badge> : <Badge tone="live">HUB</Badge>}
                        {a.session_id} · {a.phase} · {a.clients} viewers
                      </a>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <section className="cc-panel" aria-labelledby="cc-stored-title">
              <header className="cc-panel-head">
                <h2 id="cc-stored-title" className="cc-panel-title">Stored sessions</h2>
                <div className="cc-panel-meta">{data.stored.length} in the database</div>
              </header>
              {data.stored_error && (
                <ErrorState title="Stored sessions unavailable" message={`The database is unavailable (${data.stored_error}).`}
                            onRetry={() => setReload((r) => r + 1)} />
              )}
              {!data.stored_error && data.stored.length === 0 && (
                <EmptyState title="No stored sessions" why="Nothing has been recorded into this database yet. Record one with scripts/record_session.py." />
              )}
              {data.stored.length > 0 && (
                <div className="cc-scroll-x">
                  <table className="cc-table cc-sessions-table">
                    <thead><tr>
                      <th scope="col">Date</th><th scope="col">Event</th><th scope="col">Session</th>
                      <th scope="col" className="cc-num">Laps</th><th scope="col" className="cc-num">Cars</th>
                      <th scope="col">Telemetry</th><th scope="col"><span className="cc-sr">Open</span></th>
                    </tr></thead>
                    <tbody>{data.stored.map((s) => <SessionRow key={s.session_id} s={s} />)}</tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </Page>
  );
}
