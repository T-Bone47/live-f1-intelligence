/**
 * Server state for one read: idle -> loading (keeps the previous value) ->
 * success | error. Values are never mutated after they arrive.
 */

import { useEffect, useState } from "react";
import { ApiError } from "./api";

export type Resource<T> =
  | { status: "idle" }
  | { status: "loading"; previous: T | null }
  | { status: "success"; data: T }
  | { status: "error"; error: ApiError };

export function useResource<T>(
  key: string | null,
  load: (key: string, signal: AbortSignal) => Promise<T>,
  reloadKey = 0,
): Resource<T> {
  const [state, setState] = useState<Resource<T>>({ status: "idle" });

  useEffect(() => {
    if (key == null) { setState({ status: "idle" }); return; }
    const ctrl = new AbortController();
    setState((prev) => ({
      status: "loading",
      previous: prev.status === "success" ? prev.data : prev.status === "loading" ? prev.previous : null,
    }));
    load(key, ctrl.signal)
      .then((data) => { if (!ctrl.signal.aborted) setState({ status: "success", data }); })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setState({ status: "error", error: e instanceof ApiError ? e
          : new ApiError("unexpected", (e as Error)?.message || "Unexpected error.", null) });
      });
    return () => ctrl.abort();
    // `load` is a module-level function at every call site
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, reloadKey]);

  return state;
}

export function dataOf<T>(r: Resource<T>): T | null {
  return r.status === "success" ? r.data : r.status === "loading" ? r.previous : null;
}
