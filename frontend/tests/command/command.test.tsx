/**
 * Race Intelligence Command Center against the REAL golden timeline (2026
 * Dutch GP race). fetch is the only mock. The central invariant: at any
 * cursor position every panel describes the same session moment.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import * as format from "../../src/command/format";

// review #4: count renders of the frame-row panels through a formatter only they call
vi.mock("../../src/command/format", async (orig) => {
  const m = await orig<typeof import("../../src/command/format")>();
  return { ...m, fmtAsOf: vi.fn(m.fmtAsOf) };
});
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { CommandCenter } from "../../src/components/command/CommandCenter";
import { fmtAsOf, fmtClockTenths, fmtGap } from "../../src/command/format";
import { frameIndexAt, frameTimes } from "../../src/command/moment";
import type { Timeline } from "../../src/command/types";
import { CATALOG, frameIndex, golden, json, mockApi, SID } from "./fixture";
import { stateAt } from "../spatial/fixture";

afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

const search = (extra = "") => `?session=${encodeURIComponent(SID)}${extra}`;

async function renderAt(extra = "", timeline?: () => Timeline) {
  mockApi(timeline ? { timeline: () => json(timeline(), 200, { "X-Timeline-Contract": "session_timeline_v1" }) } : {});
  const utils = render(<CommandCenter search={search(extra)} />);
  // the first render parses a 1.3 MB real timeline; allow for a loaded machine
  await screen.findByRole("heading", { name: /netherlands · zandvoort/i }, { timeout: 8000 });
  return utils;
}

const tower = () => screen.getByRole("table", { name: /^timing at/i });
const towerRows = () => within(tower()).getAllByRole("row").slice(1);
const lapHeader = (c: HTMLElement) => c.querySelector(".cc-lap-big")?.textContent;

describe("session context", () => {
  it("names the session from stored metadata only and marks it HISTORICAL", async () => {
    const { container } = await renderAt();
    expect(screen.getByText(/2026 · Race/)).toBeInTheDocument();
    expect(screen.getAllByText("HISTORICAL").length).toBeGreaterThan(0);
    expect(container.textContent).not.toMatch(/Dutch Grand Prix|Dutch GP/i);   // meeting_name is null
    expect(lapHeader(container)).toBe("FINAL");                                   // default: end of recording
  });

  it("opens at the lap in the URL and marks the moment as a replay", async () => {
    const { container } = await renderAt("&lap=30");
    expect(lapHeader(container)).toBe("LAP 30");
    expect(screen.getByText("REPLAY")).toBeInTheDocument();
  });
});

describe("timing tower renders the frame exactly", () => {
  it("shows every row in backend order with backend gaps", async () => {
    await renderAt();
    const t = golden();
    const frame = t.frames[t.frames.length - 1];
    const expected = [...frame.rows].sort((a, b) => (a.position ?? 99) - (b.position ?? 99));
    const rows = towerRows();
    expect(rows).toHaveLength(expected.length);
    rows.forEach((tr, i) => {
      expect(tr).toHaveAttribute("data-driver", String(expected[i].driver_number));
      expect(tr.querySelector(".cc-tt-gap")).toHaveTextContent(fmtGap(expected[i]));
    });
  });

  it("displays a tampered gap as received - nothing is recalculated", async () => {
    const tampered = () => {
      const t = golden();
      const f = t.frames[t.frames.length - 1];
      const p2 = f.rows.find((r) => r.position === 2)!;
      p2.gap_to_leader_s = 2.5;
      return t;
    };
    await renderAt("", tampered);
    const p2 = towerRows()[1];
    expect(p2.querySelector(".cc-tt-gap")).toHaveTextContent("+2.500");
  });
});

describe("ONE SESSION STATE: every panel moves with the cursor", () => {
  it.each([10, 20, 30])("at lap %i tower, header, stints, race control and weather agree", async (lap) => {
    const { container } = await renderAt(`&lap=${lap}`);
    const t = golden();
    const i = frameIndex(t, lap);
    const f = t.frames[i];
    expect(lapHeader(container)).toBe(`LAP ${lap}`);
    // tower compound / laps on set per driver = the frame row
    for (const r of f.rows) {
      const tr = container.querySelector(`tr[data-driver="${r.driver_number}"]`)!;
      if (r.tyre_laps_on_set != null) expect(tr.querySelector(".cc-tyre-laps")).toHaveTextContent(String(r.tyre_laps_on_set));
    }
    // race-control count = messages first included at or before this frame
    const known = t.race_control.filter((m) => m.frame_index <= i).length;
    expect(screen.getByText(`${known} messages up to this moment`)).toBeInTheDocument();
    // weather = the frame's own latest weather
    if (f.weather.track_temp_c != null) {
      const cell = within(document.getElementById("cc-weather")!).getByText("Track").closest(".cc-wx-cell")!;
      expect(cell).toHaveTextContent(`${f.weather.track_temp_c.toFixed(1)}°C`);
    }
    // stints never extend past the frame: no stint number above the row's current one
    const leader = f.rows.find((r) => r.position === 1)!;
    const stintRow = container.querySelectorAll(".cc-stint-row")[0];
    expect(stintRow.querySelectorAll(".cc-stint").length).toBeLessThanOrEqual(leader.stint_number ?? 0);
  });

  it("stepping with the keyboard moves every panel together", async () => {
    const { container } = await renderAt("&lap=20");
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(lapHeader(container)).toBe("LAP 21");
    const t = golden();
    const known = t.race_control.filter((m) => m.frame_index <= frameIndex(t, 21)).length;
    expect(screen.getByText(`${known} messages up to this moment`)).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(lapHeader(container)).toBe("LAP 19");
  });

  it("?t= mid-lap opens between frames", async () => {
    const t = golden();
    const frames = frameTimes(t);
    const i = t.frames.findIndex((f) => f.kind === "LAP" && f.lap === 39);
    const at = frames[i] + 20_000;
    expect(at).toBeLessThan(frames[i + 1]);
    const { container } = await renderAt(`&lap=12&t=${encodeURIComponent(new Date(at).toISOString())}`);
    expect(lapHeader(container)).toBe("LAP 39");
    expect(container.querySelector(".cc-replay-time")).toHaveTextContent(fmtClockTenths(at));
    const known = t.race_control.filter((m) => Date.parse(m.ts!) <= at).length;
    expect(screen.getByText(`${known} messages up to this moment`)).toBeInTheDocument();
  });

  it.each([["garbage"], ["2020-01-01T00:00:00Z"], ["2026-08-23T14:00:00"]])(
    "a malformed or out-of-range ?t= (%s) falls back to ?lap=", async (bad) => {
      const { container } = await renderAt(`&lap=30&t=${encodeURIComponent(bad)}`);
      expect(lapHeader(container)).toBe("LAP 30");
    });

  it("Shift+ArrowRight moves 10 s and every panel keeps one moment", async () => {
    const { container } = await renderAt("&lap=20");
    const t = golden();
    const frames = frameTimes(t);
    const i = t.frames.findIndex((f) => f.kind === "LAP" && f.lap === 20);
    fireEvent.keyDown(window, { key: "ArrowRight", shiftKey: true });
    const at = frames[i] + 10_000;
    expect(container.querySelector(".cc-replay-time")).toHaveTextContent(fmtClockTenths(at));
    expect(lapHeader(container)).toBe("LAP 20");
    const known = t.race_control.filter((m) => Date.parse(m.ts!) <= at).length;
    expect(screen.getByText(`${known} messages up to this moment`)).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowLeft", shiftKey: true });
    expect(container.querySelector(".cc-replay-time")).toHaveTextContent(fmtClockTenths(frames[i]));
  });

  it("frame-row panels say which frame they show", async () => {
    const { container } = await renderAt("&lap=40");
    const t = golden();
    const f = t.frames.find((x) => x.kind === "LAP" && x.lap === 40)!;
    for (const id of ["cc-timing", "cc-positions", "cc-battles", "cc-strategy"]) {
      expect(container.querySelector(`#${id} .cc-asof`)).toHaveTextContent(fmtAsOf(f));
    }
  });

  it("the lap-2 moment is inside the red flag", async () => {
    await renderAt("&lap=2");
    expect(screen.getAllByText("RED FLAG").length).toBeGreaterThan(0);
    expect(screen.getByText("RED FLAG - RACE SUSPENDED")).toBeInTheDocument();
  });
});

describe("no fabrication", () => {
  it("missing weather reads Unavailable, never 0 °C", async () => {
    const noWeather = () => { const t = golden(); t.frames.forEach((f) => { f.weather = {}; }); t.weather = []; return t; };
    const { container } = await renderAt("", noWeather);
    expect(screen.getByText("Weather unavailable")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/0\.0°C/);
  });

  it("missing stints read Unavailable, never a strategy", async () => {
    const noStints = () => {
      const t = golden(); t.stints = [];
      t.frames.forEach((f) => f.rows.forEach((r) => { r.stint_number = null; r.compound = null; r.tyre_laps_on_set = null; }));
      return t;
    };
    await renderAt("", noStints);
    expect(screen.getByText("Tyre data unavailable")).toBeInTheDocument();
    expect(screen.queryByText(/1 STOP|2 STOP/i)).toBeNull();
  });

  it("no battle in the data means no battle on screen", async () => {
    const noBattles = () => { const t = golden(); t.frames.forEach((f) => { f.active_battles = []; }); return t; };
    await renderAt("", noBattles);
    expect(screen.getByText("No battles at this moment")).toBeInTheDocument();
    expect(document.querySelectorAll(".cc-battle")).toHaveLength(0);
  });

  it("never generates track-geometry labels (official race-control text is quoted verbatim)", async () => {
    const { container } = await renderAt("&lap=40");
    const clone = container.cloneNode(true) as HTMLElement;
    // FIA messages such as "TURN 14 INCIDENT ..." are observed text, not derived geometry
    const quoted = clone.querySelectorAll(".cc-rc-msg");
    expect(quoted.length).toBeGreaterThan(0);
    quoted.forEach((el) => el.remove());
    // Phase 12B: a validated track map and "Track position" now exist; corners,
    // apexes, braking zones, DRS zones and racing lines still never do
    clone.querySelectorAll(".sm-unavailable").forEach((el) => el.remove());
    expect(clone.textContent).not.toMatch(/\bTurn \d|\bApex\b|Braking zone|\bcorner\b|DRS zone|racing line/i);
  });

  it("DRS is stated unavailable, not guessed", async () => {
    await renderAt("&lap=40");
    fireEvent.click(document.querySelectorAll<HTMLButtonElement>(".cc-battle")[0]);
    expect(screen.getByText("not in this data")).toBeInTheDocument();
  });
});

describe("interaction", () => {
  it("selecting a driver opens driver focus and puts the driver in the URL", async () => {
    await renderAt("&lap=40");
    const row = document.querySelector<HTMLTableRowElement>('tr[data-driver="12"]')!;
    fireEvent.click(row);
    expect(await screen.findByRole("heading", { name: "Driver focus" })).toBeInTheDocument();
    expect(screen.getByText("Kimi ANTONELLI")).toBeInTheDocument();
    await waitFor(() => expect(window.location.search).toContain("driver=12"));
  });

  it("the play button toggles playback; Escape clears the selection", async () => {
    await renderAt("&lap=40&driver=12");
    const play = screen.getByRole("button", { name: "Play replay" });
    fireEvent.click(play);
    expect(screen.getByRole("button", { name: "Pause replay" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Pause replay" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("heading", { name: "Session" })).toBeInTheDocument();
  });

  it("selecting a race-control message moves the cursor to its time", async () => {
    const { container } = await renderAt("&lap=40");
    act(() => { fireEvent.click(screen.getByRole("button", { name: "All" })); });
    const red = screen.getByText("RED FLAG - RACE SUSPENDED").closest("button")!;
    fireEvent.click(red);
    const t = golden();
    const m = t.race_control.find((x) => x.message === "RED FLAG - RACE SUSPENDED")!;
    const at = Date.parse(m.ts!);
    const f = t.frames[frameIndexAt(frameTimes(t), at)];
    expect(lapHeader(container)).toBe(f.kind === "LAP" ? `LAP ${f.lap}` : f.kind);
    expect(container.querySelector(".cc-replay-time")).toHaveTextContent(fmtClockTenths(at));
    expect(screen.getByText("RED FLAG - RACE SUSPENDED")).toBeInTheDocument();   // listed at its own time
  });
});

describe("failure states", () => {
  it("a timeline for another session is refused, nothing is rendered", async () => {
    mockApi({ timeline: () => { const t = golden(); t.session!.session_id = "openf1:1"; return json(t); } });
    render(<CommandCenter search={search()} />);
    expect(await screen.findByText("The session could not be loaded", {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: /^timing at/i })).toBeNull();
  });

  it("no recording is an explicit 404 with a way out", async () => {
    mockApi({ timeline: () => json({ detail: "no recording or running session for openf1:11353: timeline unavailable" }, 404) });
    render(<CommandCenter search={search()} />);
    expect(await screen.findByText("No timeline for this session")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Browse sessions" })).toHaveAttribute("href", "/sessions");
  });

  it("the sessions page offers Open only when a timeline exists", async () => {
    const catalog = structuredClone(CATALOG);
    catalog.stored.push({ ...catalog.stored[0], session_id: "openf1:9161", timeline_available: false, max_lap: 19 });
    mockApi({ catalog: () => json(catalog) });
    render(<CommandCenter search="" />);
    expect(await screen.findByRole("link", { name: /open/i })).toHaveAttribute("href", `/?session=${encodeURIComponent(SID)}`);
    expect(screen.getByText("No recording")).toBeInTheDocument();
  });
});

describe("track map in the command center (Phase 12B)", () => {
  const map = () => document.getElementById("cc-map") as HTMLElement;
  const mapMarkers = () => [...map().querySelectorAll("g.sm-marker")];
  const S40 = stateAt(2);

  it("the map shows the LAP 40 moment from the real fixture and names its time", async () => {
    await renderAt("&lap=40");
    expect(await within(map()).findByText(/positions at 14:26:09\.3 UTC/, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(mapMarkers()).toHaveLength(S40.drivers.filter((d) => d.status !== "NO_COVERAGE").length);
  });

  it("moving the cursor requests the new moment's state", async () => {
    const t = golden();
    const fetchMock = mockApi();
    render(<CommandCenter search={search("&lap=40")} />);
    await screen.findByRole("heading", { name: /netherlands · zandvoort/i }, { timeout: 8000 });
    fireEvent.keyDown(window, { key: "ArrowRight" });
    const next = Date.parse(t.frames[frameIndex(t, 41)].at!);
    await waitFor(() => {
      const ats = fetchMock.mock.calls.map((c) => new URL(String(c[0]), "http://x"))
        .filter((u) => decodeURIComponent(u.pathname).endsWith("/spatial"))
        .map((u) => Date.parse(u.searchParams.get("at")!));
      expect(ats).toContain(next);
    }, { timeout: 4000 });
  });

  it("after location coverage ends there are no markers and the map says so", async () => {
    await renderAt();                                       // FINAL frame
    expect(await within(map()).findByText("No position coverage at this moment", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(mapMarkers()).toHaveLength(0);
    expect(map().querySelector("path.sm-circuit")).not.toBeNull();
  });

  it("the red-flag frame shows the RED FLAG banner from the timeline", async () => {
    await renderAt("&lap=2");
    await within(map()).findByText(/positions at/, {}, { timeout: 4000 });
    expect(map().querySelector(".sm-phase")).toHaveTextContent(/RED FLAG/);
  });

  it("selecting a driver highlights it on the map and fills Track position in driver focus", async () => {
    const d = S40.drivers.find((x) => x.status === "POSITIONED" && x.sector != null)!;
    await renderAt(`&lap=40&driver=${d.driver_number}`);
    await within(map()).findByText(/positions at/, {}, { timeout: 4000 });
    expect(map().querySelector(`g.sm-marker[data-driver="${d.driver_number}"]`)).toHaveClass("is-selected");
    const focus = document.getElementById("cc-focus") as HTMLElement;
    const block = within(focus).getByText("Track position").closest(".cc-focus-block") as HTMLElement;
    expect(block).toHaveTextContent(`S${d.sector}`);
    expect(block).toHaveTextContent(`${Math.round(d.distance_m!).toLocaleString("en-US")} m`);
    expect(block).toHaveTextContent(/positions at 14:26:09\.3 UTC/);
  });

  it("selecting a battle highlights both cars", async () => {
    await renderAt("&lap=40");
    await within(map()).findByText(/positions at/, {}, { timeout: 4000 });
    const t = golden();
    const b = t.frames[frameIndex(t, 40)].active_battles[0];
    fireEvent.click(document.querySelectorAll<HTMLButtonElement>(".cc-battle")[0]);
    const lit = [b.ahead, b.behind].map((n) => map().querySelector(`g.sm-marker[data-driver="${n}"]`)).filter(Boolean);
    expect(lit.length).toBeGreaterThan(0);
    for (const m of lit) expect(m).toHaveClass("is-battle");
  });

  it.each([
    ["404 on the track", { track: () => json({ detail: "no recording for openf1:11353" }, 404) }, /Spatial map unavailable/],
    ["409 on the state", { state: () => json({ detail: { message: "spatial geometry not validated for this session",
                                                         status: "UNVALIDATED", reasons: ["NO_CITED_LAP_LENGTH"] } }, 409) },
     /NO_CITED_LAP_LENGTH/],
    ["422 on the state", { state: () => json({ detail: "at must carry a UTC offset" }, 422) }, /at must carry a UTC offset/],
    ["500 on the state", { state: () => json({ detail: "spatial output withheld (fail closed)" }, 500) }, /spatial output withheld/],
  ])("%s shows its map state", async (_n, opts, text) => {
    mockApi(opts as Parameters<typeof mockApi>[0]);
    render(<CommandCenter search={search("&lap=40")} />);
    await screen.findByRole("heading", { name: /netherlands · zandvoort/i }, { timeout: 8000 });
    expect(await within(map()).findByText(text, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(mapMarkers()).toHaveLength(0);
  });

  it("mobile: the Track tab shows the map", async () => {
    await renderAt("&lap=40");
    fireEvent.click(screen.getByRole("button", { name: "Track" }));
    expect(screen.getByRole("button", { name: "Track" })).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelector(".cc-tab-track")).not.toBeNull();
    expect(map().closest("[data-tab]")).toHaveAttribute("data-tab", "track");
  });
});

describe("final review fixes (Phase 12B)", () => {
  it("a live session asks for no spatial data (review #7)", async () => {
    const live = () => { const t = golden(); t.source.kind = "LIVE_HUB"; return t; };
    const fetchMock = mockApi({ timeline: () => json(live(), 200, { "X-Timeline-Contract": "session_timeline_v1" }) });
    render(<CommandCenter search={search("&lap=40")} />);
    await screen.findByRole("heading", { name: /netherlands · zandvoort/i }, { timeout: 8000 });
    await new Promise((r) => setTimeout(r, 400));
    const spatial = fetchMock.mock.calls.map((c) => String(c[0])).filter((u) => /\/track$|\/spatial/.test(u));
    expect(spatial).toEqual([]);
    expect(within(document.getElementById("cc-map")!).getByText("Spatial map unavailable")).toBeInTheDocument();
  });

  it("moving the cursor within a frame re-renders no frame-row panel (review #4)", async () => {
    const { container } = await renderAt("&lap=40");
    const t = golden();
    const times = frameTimes(t);
    const i = frameIndex(t, 40);
    const stamps = [...t.race_control, ...t.pit_stops, ...t.weather].map((x) => Date.parse(x.ts!));
    let target = times[i] + 1000;
    while (stamps.some((ms) => ms > times[i] && ms <= target)) target += 1000;
    expect(target).toBeLessThan(times[i + 1]);
    vi.mocked(format.fmtAsOf).mockClear();
    const input = container.querySelector<HTMLInputElement>(".cc-scrub-input")!;
    fireEvent.change(input, { target: { value: String((target - times[0]) / 1000) } });
    expect(container.querySelector(".cc-replay-time")).toHaveTextContent(fmtClockTenths(target));
    expect(vi.mocked(format.fmtAsOf)).not.toHaveBeenCalled();
  });
});

describe("car telemetry at the cursor (Phase 12C)", () => {
  async function withTelemetry(extra: string) {
    const { serveTelemetry, pair } = await import("../telemetry/fixture");
    const api = mockApi();
    const fn = vi.fn(async (input: RequestInfo | URL) => {
      const u = new URL(String(input), "http://localhost");
      return /\/telemetry\/\d+$/.test(decodeURIComponent(u.pathname)) ? serveTelemetry(u) : api(input);
    });
    vi.stubGlobal("fetch", fn);
    render(<CommandCenter search={search(extra)} />);
    await screen.findByRole("heading", { name: /netherlands · zandvoort/i }, { timeout: 8000 });
    const telemetryCalls = () => fn.mock.calls.map((c) => new URL(String(c[0]), "http://x"))
      .filter((u) => /\/telemetry\/\d+$/.test(decodeURIComponent(u.pathname)));
    return { pair: pair(), telemetryCalls };
  }

  it("draws the selected car's stored samples up to the cursor", async () => {
    const { pair, telemetryCalls } = await withTelemetry("&lap=40&driver=16");
    const cursor = Date.parse(pair.provenance.cursor);
    const last = pair.telemetry.series.speed!.filter((p) => Date.parse(p.ts) <= cursor).at(-1)!;
    const panel = document.getElementById("cc-telemetry")!;
    await waitFor(() => expect(within(panel).getByTestId("latest-speed").textContent).toBe(`${last.value} kph`),
                  { timeout: 4000 });
    const [u] = telemetryCalls();
    expect(decodeURIComponent(u.pathname)).toMatch(/\/telemetry\/16$/);
    expect(Date.parse(u.searchParams.get("start")!)).toBe(cursor - 60_000);
    expect(within(panel).getByText(/DRS: not in this data/)).toBeInTheDocument();
  });

  it("no selected driver, no telemetry request", async () => {
    const { telemetryCalls } = await withTelemetry("&lap=40");
    expect(await screen.findByText("Select a driver to see car telemetry")).toBeInTheDocument();
    await act(async () => { await new Promise((r) => setTimeout(r, 300)); });
    expect(telemetryCalls()).toHaveLength(0);
  });
});
