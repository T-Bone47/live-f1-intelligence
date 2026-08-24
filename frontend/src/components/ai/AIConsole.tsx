/** AI Race Engineer console. Evidence-grounded; never a chatbot. */

import { useState } from "react";
import { askAI, useSessionState } from "../../state/store";
import { Panel } from "../shared";

const SUGGESTIONS = [
  "What is happening?",
  "How are tyres behaving?",
  "Is a battle developing?",
  "What changed?",
] as const;

interface AIAnswer {
  answer: string;
  confidence: string;
  evidence: { id: string; statement: string }[];
  stale: boolean;
  model: string;
  insufficient_data?: boolean;
}

export function AIConsole() {
  const st = useSessionState();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AIAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const sessionId: string | undefined = st.snapshot?.session_id;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim() || !sessionId || busy) return;
    setBusy(true);
    setAnswer(null);
    try {
      setAnswer(await askAI(sessionId, question.trim()));
      setQuestion("");
    } catch {
      setAnswer({
        answer: "AI temporarily unavailable. Deterministic intelligence remains active.",
        confidence: "NONE", evidence: [], stale: false,
        model: "none", insufficient_data: false,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="AI RACE ENGINEER" className="ai-console"
           actions={
             <span className={`ai-ready ${busy ? "analyzing" : ""}`}
                   role="status">
               {busy ? "\u25CB ANALYZING" : "\u25CF READY"}
             </span>
           }>
      <div className="ai-answer-block" aria-live="polite">
        {!answer && !busy && (
          <p className="dim">Ask about pace, tyres, battles or strategy. Answers are grounded in deterministic analysis.</p>
        )}
        {answer && (
          <>
            {answer.insufficient_data && (
              <div className="insufficient-tag" role="note">INSUFFICIENT DATA</div>
            )}
            <p className="ai-text">{answer.answer}</p>
            {answer.evidence.length > 0 && (
              <div className="evidence-row">
                <span className="dim ev-label">EVIDENCE</span>
                {answer.evidence.map((e, i) => (
                  <button key={i} type="button" className="evidence-chip"
                          title={e.statement || ""}
                          onClick={() => navigator.clipboard?.writeText(`[${e.id}] ${e.statement}`)}>
                    [{e.id}]
                  </button>
                ))}
              </div>
            )}
            <div className="ai-meta-row">
              <span className={`conf-badge conf-${(answer.confidence ?? "").toLowerCase()}`}>
                {answer.confidence}
              </span>
              {answer.stale && <span className="stale-badge">STALE</span>}
              <span className="mono dim text-xs">{answer.model}</span>
            </div>
          </>
        )}
      </div>

      <div className="suggestions" role="group" aria-label="Suggested questions">
        {SUGGESTIONS.map(sg => (
          <button key={sg} type="button" className="suggestion-btn"
                  onClick={() => setQuestion(sg)}>{sg}</button>
        ))}
      </div>

      <form onSubmit={submit} className="ai-form">
        <input value={question} onChange={e => setQuestion(e.target.value)}
               placeholder="Ask the race engineer\u2026" maxLength={300}
               aria-label="Ask the race engineer" />
        <button type="submit" disabled={busy || !sessionId}>{"\u2192"}</button>
      </form>
    </Panel>
  );
}

export function AIInsightFeed() {
  const st = useSessionState();
  const insights = [...(st.aiInsights ?? [])].reverse().slice(0, 12);
  if (!insights.length) return null;
  return (
    <section className="panel" aria-label="AI insight feed">
      {insights.map((ins: any, i: number) => (
        <div key={i} className={`ai-insight sev-${(ins.severity ?? "INFO").toLowerCase()}`}>
          <span className="mono dim">{String(ins.generated_at ?? "").slice(11, 19)}</span>
          <span>{ins.answer}</span>
          {(ins.evidence ?? []).length > 0 && (
            <span className="dim ev-ids">
              {(ins.evidence as any[]).map(e => `[${e.id}]`).join(" ")}
            </span>
          )}
        </div>
      ))}
    </section>
  );
}
