/**
 * Server state for one comparison: idle -> loading -> success | error.
 * The evidence object is immutable once received; UI state lives elsewhere.
 */

import { useEffect, useState } from "react";
import { EvidenceError, fetchLapComparisonEvidence, type EvidenceResponse } from "./api";
import type { EvidenceRequest } from "./request";

export type EvidenceState =
  | { status: "idle" }
  | { status: "loading"; request: EvidenceRequest; previous: EvidenceResponse | null }
  | { status: "success"; request: EvidenceRequest; data: EvidenceResponse }
  | { status: "error"; request: EvidenceRequest; error: EvidenceError };

export function useEvidence(request: EvidenceRequest | null, reloadKey = 0): EvidenceState {
  const [state, setState] = useState<EvidenceState>({ status: "idle" });

  useEffect(() => {
    if (!request) { setState({ status: "idle" }); return; }
    const ctrl = new AbortController();
    setState((prev) => ({
      status: "loading", request,
      previous: prev.status === "success" ? prev.data : prev.status === "loading" ? prev.previous : null,
    }));
    fetchLapComparisonEvidence(request, ctrl.signal)
      .then((data) => { if (!ctrl.signal.aborted) setState({ status: "success", request, data }); })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        const error = e instanceof EvidenceError ? e
          : new EvidenceError("unexpected", (e as Error)?.message || "Unexpected error.", null);
        setState({ status: "error", request, error });
      });
    return () => ctrl.abort();
  }, [request, reloadKey]);

  return state;
}
