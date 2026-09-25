/**
 * Pixel geometry for the workbench's SVG charts: linear scales, "nice" axis
 * ticks, element width tracking and a reduced-motion-aware domain tween.
 * Presentation only — maps evidence values to pixels, derives no evidence.
 */

import { useEffect, useRef, useState } from "react";

export type Scale = (v: number) => number;

export function linear(d0: number, d1: number, r0: number, r1: number): Scale {
  const span = d1 - d0 || 1;
  return (v) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** Round tick step (1, 2, 2.5, 5 × 10^n) giving about `count` ticks. */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!(max > min)) return [min];
  const raw = (max - min) / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const start = Math.ceil(min / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step * 1e-9; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

/** Width of an element, tracked with ResizeObserver and coalesced to one update per frame. */
export function useElementWidth<T extends HTMLElement>(fallback = 720) {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const w = Math.round(el.getBoundingClientRect().width);
      if (w > 0) setWidth((prev) => (prev === w ? prev : w));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    let frame = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    });
    ro.observe(el);
    return () => { cancelAnimationFrame(frame); ro.disconnect(); };
  }, []);
  return { ref, width };
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Tween a [lo, hi] domain toward `target` (220 ms ease-out); instant under reduced motion. */
export function useTweenedDomain(target: [number, number], durationMs = 220): [number, number] {
  const [domain, setDomain] = useState<[number, number]>(target);
  const fromRef = useRef<[number, number]>(target);
  const [t0, t1] = target;
  useEffect(() => {
    const from = fromRef.current;
    if (from[0] === t0 && from[1] === t1) return;
    if (prefersReducedMotion() || typeof requestAnimationFrame === "undefined") {
      fromRef.current = [t0, t1];
      setDomain([t0, t1]);
      return;
    }
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const k = Math.min(1, (now - start) / durationMs);
      const e = 1 - (1 - k) ** 3;
      const next: [number, number] = [from[0] + (t0 - from[0]) * e, from[1] + (t1 - from[1]) * e];
      fromRef.current = next;
      setDomain(next);
      if (k < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [t0, t1, durationMs]);
  return domain;
}
