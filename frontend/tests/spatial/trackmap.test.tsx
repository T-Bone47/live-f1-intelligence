/**
 * <TrackMap> (Phase 12B) on the REAL track golden, REAL spatial states and the
 * REAL Phase 11 timeline moment. The map draws only what the contracts carry:
 * no position, distance, sector or lap is computed in the browser.
 */

import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fmtClockTenths } from "../../src/command/format";
import { buildMoment } from "../../src/command/moment";
import { mapFit } from "../../src/components/spatial/geometry";
import { TrackMap } from "../../src/components/spatial/TrackMap";
import type { DriverState, TrackReference } from "../../src/spatial/types";
import type { SpatialView } from "../../src/spatial/useSpatial";
import { frameIndex, golden } from "../command/fixture";
import { stateAt, track } from "./fixture";

afterEach(() => vi.unstubAllGlobals());

const TL = golden();
const MOMENT40 = buildMoment(TL, frameIndex(TL, 40));
const S40 = stateAt(2);

function view(over: Partial<SpatialView> = {}, drivers: DriverState[] = S40.drivers, t: TrackReference = track()): SpatialView {
  return { status: "ready", track: t, shown: { at: Date.parse(S40.at), drivers }, lagging: false,
           reason: null, reasons: [], error: null, retry: vi.fn(), ...over };
}

function draw(v: SpatialView = view(), props: Partial<Parameters<typeof TrackMap>[0]> = {}) {
  const onSelect = vi.fn(), onPositionSelect = vi.fn();
  const utils = render(<TrackMap view={v} moment={MOMENT40} selected={null} battle={null} playing={false} rate={16}
                                 onSelect={onSelect} onPositionSelect={onPositionSelect} {...props} />);
  return { ...utils, onSelect, onPositionSelect };
}

const markers = (c: HTMLElement) => [...c.querySelectorAll<SVGGElement>("g.sm-marker")];
const marker = (c: HTMLElement, n: number) => c.querySelector<SVGGElement>(`g.sm-marker[data-driver="${n}"]`);
const translate = (el: Element) => {
  const m = /translate\(([-\d.]+)px,\s*([-\d.]+)px\)/.exec((el as SVGGElement).style.transform)!;
  return [Number(m[1]), Number(m[2])];
};
const positioned = S40.drivers.filter((d) => d.status !== "NO_COVERAGE");
const noCoverage = S40.drivers.filter((d) => d.status === "NO_COVERAGE");
const code = (n: number) => MOMENT40.driver.get(n)?.acronym ?? `#${n}`;
const colour = (n: number) => `#${MOMENT40.driver.get(n)!.team_colour}`;

describe("the validated circuit comes from the contract", () => {
  it("draws the circuit, three sector paths and the FINISH/S1/S2 lines", () => {
    const { container } = draw();
    expect(container.querySelectorAll("path.sm-circuit")).toHaveLength(1);
    expect([...container.querySelectorAll("path.sm-sector")].map((p) => p.getAttribute("data-sector"))).toEqual(["1", "2", "3"]);
    expect([...container.querySelectorAll(".sm-sector-label")].map((t) => t.textContent)).toEqual(["S1", "S2", "S3"]);
    expect([...container.querySelectorAll("g.sm-line")].map((g) => g.getAttribute("data-line")))
      .toEqual(track().timing_lines.map((l) => l.line));
    expect([...container.querySelectorAll(".sm-line-tag")].map((t) => t.textContent)).toEqual(["FINISH", "S1", "S2"]);
  });

  it("an unvalidated track draws no circuit and says why", () => {
    const { container } = draw(view({ status: "unavailable", reason: "UNVALIDATED", track: null, shown: null,
                                      reasons: ["P95_ABOVE_THRESHOLD:S1"] }));
    expect(screen.getByText("Spatial map unavailable")).toBeInTheDocument();
    expect(screen.getByText("P95_ABOVE_THRESHOLD:S1")).toBeInTheDocument();
    expect(container.querySelector("path")).toBeNull();
    expect(markers(container)).toHaveLength(0);
  });

  it("a 409 on the state draws no circuit even though the track itself loaded (mutation sweep)", () => {
    const { container } = draw(view({ status: "unavailable", reason: "UNVALIDATED", shown: null,
                                      reasons: ["NO_CITED_LAP_LENGTH"] }));
    expect(screen.getByText("NO_CITED_LAP_LENGTH")).toBeInTheDocument();
    expect(container.querySelector("path")).toBeNull();
    expect(screen.queryByRole("button", { name: /map info/i })).toBeNull();
  });

  it("a track whose status is not validated is never drawn, whatever it carries", () => {
    const t = track();
    t.status = "UNVALIDATED";                              // geometry left in place on purpose
    const { container } = draw(view({ status: "loading", shown: null }, S40.drivers, t));
    expect(container.querySelector("path")).toBeNull();
    expect(markers(container)).toHaveLength(0);
  });

  it.each([["RECORDING_ONLY", /recordings/i], ["NO_RECORDING", /no recording/i]])("%s is unavailable, with no circuit", (reason, text) => {
    const { container } = draw(view({ status: "unavailable", reason: reason as SpatialView["reason"], track: null, shown: null }));
    expect(screen.getByText("Spatial map unavailable")).toBeInTheDocument();
    expect(screen.getByText(text)).toBeInTheDocument();
    expect(container.querySelector("path")).toBeNull();
  });

  it("an error shows the backend message and a retry", () => {
    const v = view({ status: "error", error: { kind: "withheld", message: "spatial output withheld (fail closed)" } as SpatialView["error"] });
    draw(v);
    expect(screen.getByText("spatial output withheld (fail closed)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(v.retry).toHaveBeenCalled();
  });
});

describe("markers are the backend's positions", () => {
  it("one marker per positioned driver at the backend x/y", () => {
    const { container } = draw();
    expect(markers(container)).toHaveLength(positioned.length);
    const fit = mapFit(track(), 640);
    for (const d of positioned) {
      const [px, py] = fit.toPx(d.x!, d.y!);
      const [mx, my] = translate(marker(container, d.driver_number)!);
      expect(mx).toBeCloseTo(px, 1);
      expect(my).toBeCloseTo(py, 1);
    }
  });

  it("NO_COVERAGE drivers get no marker and are listed under Not on map", () => {
    const { container } = draw();
    expect(noCoverage.length).toBeGreaterThan(0);
    const strip = container.querySelector(".sm-offmap") as HTMLElement;
    for (const d of noCoverage) {
      expect(marker(container, d.driver_number)).toBeNull();
      expect(within(strip).getByText(code(d.driver_number))).toBeInTheDocument();
    }
    expect(within(strip).getAllByText(/no coverage/i).length).toBe(noCoverage.length);
  });

  it("STALE is faded and labelled stale with its age; OFF and PIT carry their tags", () => {
    const drivers = structuredClone(S40.drivers);
    const [a, b, c] = drivers.filter((d) => d.status === "POSITIONED" && d.flag === "ON_REFERENCE");
    Object.assign(a, { status: "STALE", age_s: 7.5, confidence: "LOW" });
    Object.assign(b, { flag: "OFF_REFERENCE", reference_fraction: null, distance_m: null, sector: null, lap_number: null });
    Object.assign(c, { flag: "PIT_LANE", reference_fraction: null, distance_m: null, sector: null, lap_number: null });
    const { container } = draw(view({}, drivers));
    expect(marker(container, a.driver_number)).toHaveClass("is-stale");
    expect(container.querySelector(`.sm-label[data-driver="${a.driver_number}"]`)).toHaveTextContent(/STALE/);
    fireEvent.mouseEnter(marker(container, a.driver_number)!);
    expect(screen.getByRole("tooltip")).toHaveTextContent(/7\.5 s/);
    expect(marker(container, b.driver_number)).toHaveClass("is-off");
    expect(container.querySelector(`.sm-label[data-driver="${b.driver_number}"]`)).toHaveTextContent(/OFF/);
    expect(marker(container, c.driver_number)!.querySelector("rect.sm-square")).not.toBeNull();
    expect(container.querySelector(`.sm-label[data-driver="${c.driver_number}"]`)).toHaveTextContent(/PIT/);
  });

  it("marker colour is the driver's team colour whatever the status", () => {
    const drivers = structuredClone(S40.drivers);
    const [a, b] = drivers.filter((d) => d.status === "POSITIONED" && d.flag === "ON_REFERENCE");
    Object.assign(a, { flag: "PIT_LANE", reference_fraction: null, distance_m: null, sector: null, lap_number: null });
    Object.assign(b, { status: "STALE", age_s: 3.1 });
    const { container } = draw(view({}, drivers));
    for (const d of drivers.filter((x) => x.status !== "NO_COVERAGE")) {
      const shape = marker(container, d.driver_number)!.querySelector(".sm-shape")!;
      const paint = shape.getAttribute("fill") === "none" ? shape.getAttribute("stroke") : shape.getAttribute("fill");
      expect(paint?.toLowerCase()).toBe(colour(d.driver_number).toLowerCase());
    }
  });

  it("LOW or NONE confidence draws a dashed ring and says the grade in words", () => {
    const drivers = structuredClone(S40.drivers);
    const a = drivers.find((d) => d.status === "POSITIONED")!;
    a.confidence = "NONE";
    const { container } = draw(view({}, drivers));
    expect(marker(container, a.driver_number)!.querySelector(".sm-uncertain")).not.toBeNull();
    expect(marker(container, a.driver_number)).toHaveAttribute("aria-label", expect.stringMatching(/confidence none/i));
  });
});

describe("labels, selection and interaction", () => {
  const p1 = MOMENT40.rows[0].driver_number;

  it("P1 of the current frame keeps a persistent label", () => {
    const { container } = draw();
    expect(container.querySelector(`.sm-label[data-driver="${p1}"]`)).toHaveTextContent(code(p1));
  });

  it("the selected driver and the battle pair are labelled and highlighted", () => {
    const [x, y, z] = positioned.map((d) => d.driver_number).filter((n) => n !== p1);
    const { container } = draw(view(), { selected: x, battle: [y, z] });
    expect(marker(container, x)).toHaveClass("is-selected");
    expect(marker(container, y)).toHaveClass("is-battle");
    expect(marker(container, z)).toHaveClass("is-battle");
    for (const n of [x, y, z]) expect(container.querySelector(`.sm-label[data-driver="${n}"]`)).toHaveTextContent(code(n));
    expect(container.querySelector(".sm-battle-link")).not.toBeNull();
  });

  it("keyboard: arrows move focus through markers in position order; Enter selects; Esc clears", () => {
    const { container, onSelect, onPositionSelect } = draw();
    const order = MOMENT40.rows.map((r) => r.driver_number).filter((n) => marker(container, n));
    const first = marker(container, order[0])!;
    expect(first).toHaveAttribute("tabindex", "0");
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(document.activeElement).toBe(marker(container, order[1]));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(first, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith(order[0]);
    expect(onPositionSelect).toHaveBeenCalledWith(order[0], new Date(Date.parse(S40.at)).toISOString());
    fireEvent.keyDown(first, { key: "Escape" });
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("clicking a timing line shows its measured p95 and n from the track document", () => {
    const { container } = draw();
    const s1 = track().timing_lines.find((l) => l.line === "S1")!;
    fireEvent.click(container.querySelector('g.sm-line[data-line="S1"]')!);
    const readout = container.querySelector(".sm-line-readout")!;
    expect(readout).toHaveTextContent(`p95 ${s1.dispersion_m!.p95.toFixed(1)} m`);
    expect(readout).toHaveTextContent(`n ${s1.n.toLocaleString("en-US")}`);
  });

  it("hovering a sector highlights its path", () => {
    const { container } = draw();
    const s2 = container.querySelector('path.sm-sector[data-sector="2"]')!;
    fireEvent.mouseEnter(s2);
    expect(s2).toHaveClass("is-hot");
    fireEvent.mouseLeave(s2);
    expect(s2).not.toHaveClass("is-hot");
  });

  it("the map names the shown time and says when positions lag the cursor", () => {
    const { rerender } = draw();
    expect(screen.getByText(/positions at 14:26:09\.3 UTC/)).toBeInTheDocument();
    expect(screen.queryByText(/positions lag the cursor/i)).toBeNull();
    rerender(<TrackMap view={view({ lagging: true })} moment={MOMENT40} selected={null} battle={null}
                       playing={false} rate={16} onSelect={vi.fn()} />);
    expect(screen.getByText(/positions lag the cursor/i)).toBeInTheDocument();
  });

  it("after location coverage ends there are no markers and the map says so", () => {
    const final = stateAt(3);
    expect(final.drivers.every((d) => d.status === "NO_COVERAGE")).toBe(true);
    const { container } = draw(view({ shown: { at: Date.parse(final.at), drivers: final.drivers } }));
    expect(markers(container)).toHaveLength(0);
    expect(screen.getByText("No position coverage at this moment")).toBeInTheDocument();
    expect(container.querySelector("path.sm-circuit")).not.toBeNull();
  });
});

describe("accessibility and motion", () => {
  it("the hidden table lists every driver's state in words", () => {
    draw();
    const table = screen.getByRole("table", { name: /spatial state of every car/i });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(S40.drivers.length);
    const off = S40.drivers.find((d) => d.flag === "OFF_REFERENCE");
    if (off) expect(within(table).getByText(code(off.driver_number)).closest("tr")).toHaveTextContent(/off reference/i);
    const none = noCoverage[0];
    expect(within(table).getByText(code(none.driver_number)).closest("tr")).toHaveTextContent(/no coverage/i);
  });

  it("reduced motion removes marker transitions", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q,
      addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {} }));
    const { container } = draw(view(), { playing: true });
    expect(container.querySelector("svg.sm-map")).toHaveClass("is-reduced");
  });

  it("markers glide only while playing, for at most one state step of wall time", () => {
    const { container, rerender } = draw(view(), { playing: true, rate: 16 });
    expect((container.querySelector("svg.sm-map") as SVGElement).style.getPropertyValue("--spatial-tween")).toBe("125ms");
    rerender(<TrackMap view={view()} moment={MOMENT40} selected={null} battle={null} playing={false} rate={16} onSelect={vi.fn()} />);
    expect((container.querySelector("svg.sm-map") as SVGElement).style.getPropertyValue("--spatial-tween")).toBe("0ms");
  });

  it("the info drawer lists provenance, validated and unavailable capabilities", () => {
    draw();
    fireEvent.click(screen.getByRole("button", { name: /map info/i }));
    const drawer = screen.getByRole("region", { name: /map info/i });
    expect(drawer).toHaveTextContent(track().track_id);
    expect(drawer).toHaveTextContent(/OpenF1/);
    for (const v of ["Map", "Sectors", "Timing lines", "Driver position"]) {
      expect(within(drawer).getByText(v)).toBeInTheDocument();
    }
    for (const c of Object.values(track().capabilities)) expect(drawer).toHaveTextContent(c.reason);
    expect(drawer).toHaveTextContent(/no corner-level distances/i);
    // review #9: STALE means the samples around the cursor are more than 2 s apart
    expect(drawer).toHaveTextContent(/more than 2 s apart/);
    expect(drawer).not.toHaveTextContent(/more than 2 s old/);
  });

  it("names no corner, apex, DRS zone or racing line outside the unavailable list", () => {
    const { container } = draw();
    fireEvent.click(screen.getByRole("button", { name: /map info/i }));
    const clone = container.cloneNode(true) as HTMLElement;
    clone.querySelectorAll(".sm-unavailable").forEach((el) => el.remove());
    expect(clone.textContent).not.toMatch(/\bturn \d|\bcorner|\bapex|drs zone|racing line|pit lane path/i);
  });
});

describe("the browser computes no spatial value (source scan)", () => {
  it("no distance, fraction or metre arithmetic in the spatial UI", () => {
    const roots = ["src/spatial", "src/components/spatial"].map((p) => resolve(process.cwd(), p));
    const files = roots.flatMap((r) => readdirSync(r).filter((f) => /\.tsx?$/.test(f)).map((f) => join(r, f)));
    expect(files.length).toBeGreaterThan(4);
    for (const f of files) {
      const src = readFileSync(f, "utf-8");
      expect(src, f).not.toMatch(/Math\.hypot/);
      expect(src, f).not.toMatch(/(reference_fraction|distance_m|lap_length_m|length_m)\s*[-+*/]/);
      expect(src, f).not.toMatch(/[-+*/]\s*(\w+\.)?(reference_fraction|distance_m|lap_length_m|length_m)\b/);
    }
  });
});

describe("the ghost of a hovered telemetry sample (Phase 12C)", () => {
  const pair = JSON.parse(readFileSync(resolve(process.cwd(), "tests", "fixtures", "evidence", "dutch_gp_pair.json"),
                                       "utf-8")) as { trace: { driver_number: number; samples: { ts: string; x: number; y: number }[] } };
  const own = pair.trace.samples[40];
  const ghost = { driver: pair.trace.driver_number, hovered: Date.parse(own.ts) + 150, at: Date.parse(own.ts),
                  x: own.x, y: own.y };

  it("sits at the driver's own location sample, labelled with that sample's time", () => {
    const { container } = draw(view(), { ghost });
    const g = container.querySelector<SVGGElement>("g.sm-ghost")!;
    const [px, py] = mapFit(track(), 640).toPx(own.x, own.y);
    expect(g.getAttribute("transform")).toBe(`translate(${px.toFixed(1)} ${py.toFixed(1)})`);
    const label = `#${ghost.driver} at ${fmtClockTenths(ghost.at)} (hovered)`;
    expect(g.getAttribute("aria-label")).toBe(label);
    expect(within(g as unknown as HTMLElement).getByText(label)).toBeInTheDocument();
  });

  it("no ghost, nothing drawn; an unvalidated map draws no ghost either", () => {
    expect(draw(view()).container.querySelector("g.sm-ghost")).toBeNull();
    const { container } = draw(view({ status: "unavailable", reason: "UNVALIDATED", track: null, shown: null }), { ghost });
    expect(container.querySelector("g.sm-ghost")).toBeNull();
  });
});
