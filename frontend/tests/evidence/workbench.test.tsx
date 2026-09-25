/**
 * Evidence Workbench against the REAL golden evidence_v1 (Singapore 2023 Q,
 * #55 L19 vs #63 L16). fetch is the only mock.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EvidenceWorkbench } from "../../src/components/evidence/EvidenceWorkbench";
import { fmtBand, fmtDelta } from "../../src/evidence/format";
import { golden, jsonResponse, mockFetch, REAL_SEARCH } from "./fixture";

afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

async function renderLoaded(search = REAL_SEARCH) {
  const utils = render(<EvidenceWorkbench search={search} />);
  await screen.findByText(golden().evidence_id);
  return utils;
}
const rows = (c: HTMLElement) => Array.from(c.querySelectorAll<HTMLButtonElement>("ol.ewb-rows button.ewb-row"));
const row = (c: HTMLElement, label: string) => rows(c).find((r) => r.textContent?.startsWith(label))!;

describe("renders the actual evidence_v1 fixture", () => {
  it("shows the official lap delta, who is ahead, every segment and the evidence id", async () => {
    mockFetch();
    const { container } = await renderLoaded();
    const ev = golden();
    expect(screen.getAllByText(fmtDelta(ev.comparison.lap_delta_s)).length).toBeGreaterThan(0);
    expect(container.querySelector(".ewb-keyfig-sub")).toHaveTextContent("#55 ahead");
    expect(rows(container)).toHaveLength(ev.attribution.segments.length);
    expect(rows(container).map((r) => r.querySelector(".ewb-row-label")?.textContent))
      .toEqual(ev.attribution.segments.map((s) => s.label));
  });

  it("preserves significance and uncertainty exactly as the contract states", async () => {
    mockFetch();
    const { container } = await renderLoaded();
    for (const s of golden().attribution.segments) {
      const r = row(container, s.label);
      if (s.direction === "NO_DATA") { expect(r).toHaveTextContent("No data"); continue; }
      expect(r).toHaveTextContent(fmtDelta(s.accumulated_change_s));
      expect(r).toHaveTextContent(fmtBand(s.uncertainty_s));
      expect(r).toHaveTextContent(s.significant ? "Significant" : "Not significant");
    }
  });

  it("uses normalized metre labels, keeps S3 not covered, and lists every limitation", async () => {
    mockFetch();
    const { container } = await renderLoaded();
    expect(row(container, "R09")).toHaveTextContent("2,875–3,399 m norm.");
    expect(screen.getByText("Not covered")).toBeInTheDocument();
    expect(container.querySelectorAll(".ewb-limits .ewb-limit")).toHaveLength(golden().limitations.length);
    for (const l of golden().limitations) expect(screen.getByText(l.code)).toBeInTheDocument();
    expect(within(container.querySelector<HTMLElement>(".ewb-caveats")!).getByText(/normalized, not track position/)).toBeInTheDocument();
  });

  it("shows provenance: versions, input digest and the lineage chain", async () => {
    mockFetch();
    await renderLoaded();
    const ev = golden();
    expect(screen.getByText(ev.provenance.input_digest)).toBeInTheDocument();
    expect(screen.getByText(ev.calculation.attribution_version)).toBeInTheDocument();
    for (const c of ev.provenance.chain) expect(screen.getByText(c)).toBeInTheDocument();
  });

  it("never renders null, undefined, NaN or Infinity", async () => {
    mockFetch();
    const { container } = await renderLoaded();
    fireEvent.click(row(container, "R13"));
    expect(container.textContent).not.toMatch(/\b(null|undefined|NaN|Infinity)\b/);
    fireEvent.click(row(container, "R09"));
    expect(container.textContent).not.toMatch(/\b(null|undefined|NaN|Infinity)\b/);
  });
});

describe("does not recalculate analysis", () => {
  it("shows the contract's `significant` flag even where |change| < band would say otherwise", async () => {
    const ev = golden();
    ev.attribution.segments.find((s) => s.label === "R09")!.significant = true; // |−0.066| < 0.108
    mockFetch({ evidence: () => jsonResponse(ev) });
    const { container } = await renderLoaded();
    expect(row(container, "R09")).toHaveTextContent("Significant");
    expect(row(container, "R09")).not.toHaveTextContent("Not significant");
  });

  it("shows delta_end_s as delivered, not inherited_gap_s + accumulated_change_s", async () => {
    const ev = golden();
    ev.attribution.segments.find((s) => s.label === "R09")!.delta_end_s = 0.5; // only a recomputing UI would "fix" this
    mockFetch({ evidence: () => jsonResponse(ev) });
    const { container } = await renderLoaded();
    fireEvent.click(row(container, "R09"));
    expect(container.querySelector(".ewb-inspector")).toHaveTextContent("+0.500 s");
  });
});

describe("segment selection and keyboard navigation", () => {
  it("click selects, the inspector shows time accounting, and the URL records the segment", async () => {
    mockFetch();
    const { container } = await renderLoaded();
    fireEvent.click(row(container, "R09"));
    const insp = container.querySelector<HTMLElement>(".ewb-inspector")!;
    expect(within(insp).getByRole("heading", { name: "R09" })).toBeInTheDocument();
    expect(insp).toHaveTextContent("+0.084 s");      // gap entering
    expect(insp).toHaveTextContent("#63 ahead");     // positive delta = B ahead
    expect(insp).toHaveTextContent("Not significant under the current uncertainty bound");
    expect(insp).toHaveTextContent("#55 brake onset 31.8 m later (norm.)");
    expect(window.location.search).toContain("seg=R09");
  });

  it("keeps the requested segment in the URL while the evidence is still loading", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    render(<EvidenceWorkbench search={`${REAL_SEARCH}&seg=R09`} />);
    expect(window.location.search).toContain("seg=R09");
  });

  it("arrow keys move the selection, Escape clears it, [ and ] step globally", async () => {
    mockFetch();
    const user = userEvent.setup();
    const { container } = await renderLoaded();
    fireEvent.click(row(container, "R02"));
    row(container, "R02").focus();
    await user.keyboard("{ArrowDown}");
    expect(row(container, "R03")).toHaveAttribute("aria-pressed", "true");
    await user.keyboard("{Escape}");
    expect(rows(container).every((r) => r.getAttribute("aria-pressed") === "false")).toBe(true);
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard("]");
    expect(row(container, "R01")).toHaveAttribute("aria-pressed", "true");
    await user.keyboard("]");
    expect(row(container, "R02")).toHaveAttribute("aria-pressed", "true");
  });
});

describe("telemetry is fetched only on explicit drill-down", () => {
  it("makes no telemetry request until the user asks, then requests the referenced windows", async () => {
    const fetchFn = mockFetch({
      telemetry: (url) => jsonResponse({
        driver_number: Number(url.match(/telemetry\/(\d+)/)![1]), window: {}, provenance: { class: "B" },
        series: { speed: [{ ts: "2023-09-16T14:27:34.368000+00:00", value: 210 }], throttle: [], brake: [], gear: [], drs: [] },
      }),
    });
    const telemetryCalls = () => fetchFn.mock.calls.map((c) => String(c[0])).filter((u) => u.includes("/telemetry/"));
    const { container } = await renderLoaded();
    fireEvent.click(row(container, "R09"));
    expect(telemetryCalls()).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: /Inspect telemetry/ }));
    await screen.findByText(/hover for nearest samples/, undefined, { timeout: 2000 }).catch(() => undefined);
    await waitFor(() => expect(telemetryCalls()).toHaveLength(2));
    expect(telemetryCalls().every((u) => u.includes("frequency=RAW") && u.includes("start=") && u.includes("end="))).toBe(true);
    expect(telemetryCalls().some((u) => u.includes("gps"))).toBe(false);
    expect(screen.getByText("Not distance-aligned")).toBeInTheDocument();
  });
});

describe("error and empty states", () => {
  it("idle: explains what to do", () => {
    mockFetch();
    render(<EvidenceWorkbench search="" />);
    expect(screen.getByText("No comparison loaded")).toBeInTheDocument();
  });
  it.each([
    [422, "Comparison refused (422)"], [404, "Not found (404)"], [500, "Evidence withheld (500)"],
  ] as const)("HTTP %i shows '%s' with the backend message", async (status, title) => {
    mockFetch({ evidence: () => jsonResponse({ detail: "driver 55 lap 19 has no duration" }, status) });
    render(<EvidenceWorkbench search={REAL_SEARCH} />);
    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(screen.getByText("driver 55 lap 19 has no duration")).toBeInTheDocument();
  });
  it("unavailable fields render as unavailable, never null", async () => {
    const ev = golden();
    ev.comparison.lap_delta_s = null;
    ev.comparison.driver_a.lap_duration_s = null;
    ev.source.event = null;
    ev.source.circuit = null;
    mockFetch({ evidence: () => jsonResponse(ev) });
    const { container } = await renderLoaded();
    expect(screen.getByText("Official lap delta unavailable")).toBeInTheDocument();
    expect(screen.getByText("Circuit not recorded")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\b(null|undefined|NaN)\b/);
  });
});

describe("comparison selector", () => {
  it("swapping A/B and loading requests the swapped comparison (the backend negates; the UI does not)", async () => {
    const fetchFn = mockFetch();
    await renderLoaded();
    fireEvent.click(screen.getByRole("button", { name: "Swap driver A and driver B" }));
    expect(screen.getByText(/Selector differs from the loaded evidence/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Load evidence/ }));
    await waitFor(() => expect(fetchFn.mock.calls.length).toBe(2));
    expect(String(fetchFn.mock.calls[1][0])).toContain("driver_a=63&lap_a=16&driver_b=55&lap_b=19");
  });
  it("refuses to request without a cited lap length", () => {
    const fetchFn = mockFetch();
    render(<EvidenceWorkbench search="" />);
    fireEvent.click(screen.getByRole("button", { name: /Load evidence/ }));
    expect(screen.getByText(/It is never guessed/)).toBeInTheDocument();
    expect(fetchFn).not.toHaveBeenCalled();
  });
  it("the RaceWise hand-off is present but disabled until its contract is finalized", async () => {
    mockFetch();
    await renderLoaded();
    expect(screen.getByRole("button", { name: /Investigate with RaceWise/ })).toBeDisabled();
    expect(screen.getByText(/integration contract is not finalized/)).toBeInTheDocument();
  });
});
