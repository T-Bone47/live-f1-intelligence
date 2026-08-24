/**
 * AI Race Engineer Console — Enhanced with structured queries,
 * trust indicators, insight feed, and terminal-style appearance
 */

import { FormEvent, useState, useRef, useEffect } from "react";
import { useSessionState, askAI, apiGet } from "../../state/store";
import { Panel, ConfidenceBadge, EvidenceChip, ProvenanceBadge, DataFreshness } from "../shared";
import { fmtTime } from "../../logic/format";

const SUGGESTED_QUERIES = [
  "Why is the leader faster?",
  "What changed in the last 5 laps?",
  "Who should pit next?",
  "Is there a tyre degradation concern?",
  "Compare the top 3 strategies",
  "Any weather risk?",
  "Who has the pace advantage?",
  "Explain the current battle",
];

export function AIConsole() {
  const st = useSessionState();
  const snap = st.snapshot as any;
  const sessionId = snap?.session_id;
  const aiStatus = (snap as any)?.ai_status;

  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [insights, setInsights] = useState<any[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  // Fetch AI insights from WebSocket events
  useEffect(() => {
    const evts = snap?.recent_events ?? [];
    const aiEvts = evts.filter((e: any) =>
      (e.event_type ?? e.type ?? "").includes("AI") ||
      (e.source ?? "").includes("ai")
    );
    if (aiEvts.length > 0) {
      setInsights((prev) => [...prev, ...aiEvts].slice(-10));
    }
  }, [snap?.recent_events]);

  const handleAsk = async (q: string) => {
    if (!sessionId || !q.trim()) return;
    setLoading(true);
    setQuestion("");
    try {
      const result = await askAI(sessionId, q);
      setAnswer(result);
    } catch {
      setAnswer({ status: "FAILED", answer: "AI request failed. Deterministic intelligence remains active." });
    } finally {
      setLoading(false);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    handleAsk(question);
  };

  const isReady = st.status !== "DISCONNECTED";
  const statusLabel = loading ? "ANALYZING…" :
    isReady ? "READY" : "DISCONNECTED";

  return (
    <Panel title="AI ENGINEER" className="ai-console"
      actions={
        <span className={`ai-ready ${loading ? "analyzing" : ""}`}
              style={{ color: loading ? "var(--warning)" : isReady ? "var(--success)" : "var(--text-muted)" }}>
          ● {statusLabel}
        </span>
      }>
      {/* Latest answer */}
      <div className="ai-answer-block">
        {answer ? (
          <>
            <p className="ai-text">{answer.answer ?? answer.response ?? "No response."}</p>

            {/* Evidence */}
            {answer.evidence_ids?.length > 0 && (
              <div className="evidence-row">
                <span className="ev-label dim">EVIDENCE</span>
                {answer.evidence_ids.map((id: string) => (
                  <EvidenceChip key={id} id={id} />
                ))}
              </div>
            )}

            {/* Meta row */}
            <div className="ai-meta-row">
              {answer.confidence && <ConfidenceBadge level={answer.confidence} />}
              <ProvenanceBadge type="AI" />
              {answer.timestamp && (
                <span className="dim text-xs mono">{fmtTime(answer.timestamp)}</span>
              )}
              {answer.status === "FALLBACK" && (
                <span className="insufficient-tag">DETERMINISTIC FALLBACK</span>
              )}
              {answer.status === "STALE" && (
                <span className="insufficient-tag">STALE RESPONSE</span>
              )}
            </div>
          </>
        ) : (
          <p className="dim text-sm" style={{ fontStyle: "italic" }}>
            DETERMINISTIC INTELLIGENCE ACTIVE
            {!isReady && " · AI TEMPORARILY UNAVAILABLE"}
          </p>
        )}
      </div>

      {/* Suggestions */}
      <div className="suggestions">
        {SUGGESTED_QUERIES.slice(0, 4).map((q) => (
          <button key={q} className="suggestion-btn" onClick={() => handleAsk(q)}
                  disabled={loading || !sessionId}>
            {q}
          </button>
        ))}
      </div>

      {/* Input */}
      <form className="ai-form" onSubmit={onSubmit}>
        <input ref={inputRef}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="> QUERY ENGINEER (E.G. 'NORRIS STRATEGY?')"
          disabled={loading || !sessionId}
          autoComplete="off"
        />
        <button type="submit" disabled={loading || !question.trim() || !sessionId}>
          {loading ? "…" : "→"}
        </button>
      </form>

      {/* Insight feed */}
      {insights.length > 0 && (
        <div style={{ borderTop: "1px solid var(--border)", marginTop: "var(--sp-2)", paddingTop: "var(--sp-1)" }}>
          {insights.slice(-3).map((ins, i) => (
            <div key={i} className="ai-insight">
              <span className="dim mono text-xs">{fmtTime(ins.ts ?? ins.timestamp)}</span>
              <span>{ins.description ?? ins.message ?? ""}</span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
