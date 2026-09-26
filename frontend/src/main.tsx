import { createRoot } from "react-dom/client";
import React, { Suspense, lazy } from "react";
import "./styles.css";

// Routes (pathname only; each is its own lazy chunk):
//   /  and /sessions  Phase 11 Race Intelligence Command Center (REST timeline)
//   /evidence         Phase 10.6 Evidence Workbench (REST only)
//   /pitwall          legacy live pit wall (opens the realtime session socket)
const CommandCenter = lazy(() =>
  import("./components/command/CommandCenter").then((m) => ({ default: m.CommandCenter })));
const EvidenceWorkbench = lazy(() =>
  import("./components/evidence/EvidenceWorkbench").then((m) => ({ default: m.EvidenceWorkbench })));
const PitWall = lazy(() => import("./components/App").then((m) => ({ default: m.App })));

const path = location.pathname.replace(/\/+$/, "") || "/";

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { error: Error | null }> {
  constructor(props: { children: React.ReactNode }) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div role="alert" style={{ color: "#e2e6eb", background: "#07090b", padding: 24, fontFamily: "system-ui, sans-serif", minHeight: "100vh" }}>
          <h1 style={{ fontSize: 16, margin: "0 0 8px" }}>This view failed to render</h1>
          <p style={{ margin: "0 0 16px", color: "#9aa3af" }}>{this.state.error.message}</p>
          <a href="/" style={{ color: "#a0caff" }}>Back to the command center</a>
        </div>
      );
    }
    return this.props.children;
  }
}

function Route() {
  if (path === "/evidence") return <EvidenceWorkbench />;
  if (path === "/pitwall") return <PitWall />;
  return <CommandCenter />;
}

createRoot(document.getElementById("root")!).render(
  <ErrorBoundary>
    <Suspense fallback={<div style={{ minHeight: "100vh", background: "#07090b" }} />}>
      <Route />
    </Suspense>
  </ErrorBoundary>
);
