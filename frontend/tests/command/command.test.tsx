/**
 * Race Intelligence Command Center against the REAL golden timeline (2026
 * Dutch GP race). fetch is the only mock. The central invariant: at any
 * cursor position every panel describes the same session moment.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { CommandCenter } from "../../src/components/command/CommandCenter";
import { fmtGap } from "../../src/command/format";
import type { Timeline } from "../../src/command/types";
import { CATALOG, frameIndex, golden, json, mockApi, SID } from "./fixture";

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
    expect(screen.getByText(`${known} messages up to this lap`)).toBeInTheDocument();
    // weather = the frame's own latest weather
    if (f.weather.track_temp_c != null) {
      const cell = screen.getByText("Track").closest(".cc-wx-cell")!;
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
    expect(screen.getByText(`${known} messages up to this lap`)).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(lapHeader(container)).toBe("LAP 19");
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
    expect(clone.textContent).not.toMatch(/\bTurn \d|\bApex\b|Braking zone|Track position|track map/i);
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

  it("selecting a race-control message moves the cursor to its lap", async () => {
    const { container } = await renderAt("&lap=40");
    act(() => { fireEvent.click(screen.getByRole("button", { name: "All" })); });
    const red = screen.getByText("RED FLAG - RACE SUSPENDED").closest("button")!;
    fireEvent.click(red);
    const t = golden();
    const m = t.race_control.find((x) => x.message === "RED FLAG - RACE SUSPENDED")!;
    const f = t.frames[m.frame_index];
    expect(lapHeader(container)).toBe(f.kind === "LAP" ? `LAP ${f.lap}` : f.kind);
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
