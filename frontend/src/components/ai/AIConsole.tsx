/**
 * AI Race Engineer Console — Enhanced with structured queries,
 * trust indicators, insight feed, and terminal-style appearance
 */

import { FormEvent, useState, useRef } from "react";
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

export function AIConsole({ id }: { id?: string } = {}) {
  const st = useSessionState();
  const snap = st.snapshot as any;
  const sessionId = snap?.session_id;

  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleAsk = async (q: string) => {
    if (!sessionId || !q.trim()) return;
    setLoading(true);
    setQuestion("");
    try {
      const result = await askAI(sessionId, q);
      setAnswer(result);
    } catch {
      setAnswer({ status: "FAILED", response: { answer: "AI request failed. Deterministic intelligence remains active." } });
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
    <Panel id={id} title="AI ENGINEER" className="ai-console"
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
            <p className="ai-text">{answer.response?.answer ?? "No response."}</p>

            {/* Evidence */}
            {answer.response?.evidence?.length > 0 && (
              <div className="evidence-row">
                <span className="ev-label dim">EVIDENCE</span>
                {answer.response.evidence.map((e: any) => (
                  <EvidenceChip key={e.id} id={e.id} statement={e.statement} />
                ))}
              </div>
            )}

            {/* Meta row */}
            <div className="ai-meta-row">
              {answer.response?.confidence && <ConfidenceBadge level={answer.response.confidence} />}
              <ProvenanceBadge type="AI" />
              {answer.response?.generated_at && (
                <span className="dim text-xs mono">{fmtTime(answer.response.generated_at)}</span>
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

    </Panel>
  );
}
