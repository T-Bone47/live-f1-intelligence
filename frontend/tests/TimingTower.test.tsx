import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

vi.mock("../src/state/store", () => ({
  useSessionState: vi.fn(),
  useDriverSelection: vi.fn(),
  apiGet: vi.fn(),
}));

import { useSessionState, useDriverSelection, apiGet } from "../src/state/store";
import { TimingTower } from "../src/components/timing/TimingTower";

function mockState(board: any[], overrides: { selectedDriver?: number | null; comparisonDriver?: number | null } = {}) {
  vi.mocked(useSessionState).mockReturnValue({
    sessionId: "openf1:test",
    status: "LIVE",
    seq: 1,
    snapshot: { session_id: "openf1:test", leaderboard: board, fastest_lap: { driver: board[0]?.driver_number } },
    recentEvents: [],
    telemetry: {},
    lastUpdate: null,
    aiInsights: [],
  } as any);
  const selectDriver = vi.fn();
  const selectComparisonDriver = vi.fn();
  vi.mocked(useDriverSelection).mockReturnValue({
    selectedDriver: overrides.selectedDriver ?? null,
    comparisonDriver: overrides.comparisonDriver ?? null,
    selectDriver,
    selectComparisonDriver,
  });
  vi.mocked(apiGet).mockResolvedValue({ available: false });
  return { selectDriver, selectComparisonDriver };
}

const row = (n: number, position: number) => ({
  driver_number: n, position, team_name: "Test Team", last_lap_s: 80 + n,
  personal_best_s: 79 + n, lap_number: 10, in_pit: false, compound: "SOFT", tyre_age: 5,
});

describe("TimingTower", () => {
  it("shows a waiting message with an empty leaderboard", () => {
    mockState([]);
    render(<TimingTower />);
    expect(screen.getByText("WAITING FOR TIMING DATA")).toBeInTheDocument();
  });

  it("renders one row per driver on the board", () => {
    mockState([row(44, 1), row(1, 2)]);
    render(<TimingTower />);
    expect(screen.getAllByRole("row")).toHaveLength(3); // header + 2 drivers
  });

  it("selects a driver on row click", () => {
    const { selectDriver } = mockState([row(44, 1)]);
    render(<TimingTower />);
    const dataRow = screen.getAllByRole("row")[1];
    fireEvent.click(dataRow);
    expect(selectDriver).toHaveBeenCalledWith(44);
  });

  it("sets the comparison driver on ctrl+click instead of the primary selection", () => {
    const { selectDriver, selectComparisonDriver } = mockState([row(44, 1)]);
    render(<TimingTower />);
    const dataRow = screen.getAllByRole("row")[1];
    fireEvent.click(dataRow, { ctrlKey: true });
    expect(selectComparisonDriver).toHaveBeenCalledWith(44);
    expect(selectDriver).not.toHaveBeenCalled();
  });

  it("marks the currently selected driver's row via aria-selected", () => {
    mockState([row(44, 1), row(1, 2)], { selectedDriver: 44 });
    render(<TimingTower />);
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveAttribute("aria-selected", "true");
    expect(rows[2]).toHaveAttribute("aria-selected", "false");
  });

  it("toggles between expanded and compact column sets", () => {
    mockState([row(44, 1)]);
    render(<TimingTower />);
    expect(screen.getByText("TM")).toBeInTheDocument(); // expanded-only team column
    fireEvent.click(screen.getByTitle("Compact view"));
    expect(screen.queryByText("TM")).not.toBeInTheDocument();
  });
});
