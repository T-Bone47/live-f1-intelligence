import { useSessionState } from "../../state/store";
import { StatusBadge } from "../shared/index";

export function TopBar() {
  const st = useSessionState();
  const snap = st.snapshot as any;
  const mode = st.status;
  const sessionType = snap?.session_type ?? snap?.profile ?? "";
  const circuit = snap?.circuit_short_name ?? "";
  const lap = snap?.current_lap ? `LAP ${snap.current_lap}` : "";
  const phase = snap?.phase ?? "";

  return (
    <header className="topbar" role="banner">
      <div className="topbar-row">
        <StatusBadge status={mode} />
        <div className="title-block">
          <strong className="product-name">F1 INTELLIGENCE</strong>
          <span className="session-info dim">
            {[snap?.country_code, circuit, sessionType, lap].filter(Boolean).join(" \u00B7 ")}
          </span>
        </div>
        {["RED_FLAG", "SAFETY_CAR", "VSC"].includes(phase) && (
          <span className={`rc-banner rc-${phase.toLowerCase()}`} role="alert">
            {phase.replace(/_/g, " ")}
          </span>
        )}
        <div className="topbar-right mono dim text-xs">
          <span>seq {st.seq}</span>
        </div>
      </div>
    </header>
  );
}
