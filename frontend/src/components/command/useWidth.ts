import { useCallback, useLayoutEffect, useState } from "react";

/**
 * Element width via ResizeObserver, coalesced to one update per frame.
 * Returns a callback ref, so an element that mounts later (a chart shown only
 * when data exists) is observed too.
 */
export function useWidth<T extends HTMLElement>(fallback = 640) {
  const [el, setEl] = useState<T | null>(null);
  const [width, setWidth] = useState(fallback);
  const ref = useCallback((node: T | null) => setEl(node), []);
  useLayoutEffect(() => {
    if (!el) return;
    if (el.clientWidth) setWidth(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    let raf = 0;
    const ro = new ResizeObserver((entries) => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const w = Math.round(entries[0]?.contentRect.width ?? 0);
        if (w > 0) setWidth(w);
      });
    });
    ro.observe(el);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, [el]);
  return [ref, width] as const;
}
