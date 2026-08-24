import { createRoot } from "react-dom/client";
import { App } from "./components/App";
import React from "react";
import "./styles.css";

class ErrorBoundary extends React.Component<{children: any}, {error: any}> {
  constructor(props: any) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error: any) { return { error }; }
  render() {
    if (this.state.error) {
      return <div style={{ color: "red", padding: "20px", background: "#222", fontFamily: "monospace" }}>
        <h1>Frontend Crash</h1>
        <pre>{this.state.error.message}</pre>
        <pre>{this.state.error.stack}</pre>
      </div>;
    }
    return this.props.children;
  }
}

createRoot(document.getElementById("root")!).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
);
