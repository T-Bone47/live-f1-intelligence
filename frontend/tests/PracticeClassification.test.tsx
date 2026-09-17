import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../src/state/store", () => ({
  useSessionState: vi.fn(),
}));

import { useSessionState } from "../src/state/store";
import { PracticeClassification } from "../src/components/analysis/PracticeClassification";

function mockSnapshot(snapshot: any) {
  vi.mocked(useSessionState).mockReturnValue({
    sessionId: "openf1:test",
    status: "LIVE",
    seq: 1,
    snapshot,
    recentEvents: [],
    telemetry: {},
    lastUpdate: null,
    aiInsights: [],
  } as any);
}

describe("PracticeClassification", () => {
  it("renders nothing outside a practice session (real backend value is title-cased)", () => {
    mockSnapshot({ session_type: "Qualifying", leaderboard: [] });
    const { container } = render(<PracticeClassification />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when session_type is missing entirely", () => {
    mockSnapshot({ leaderboard: [] });
    const { container } = render(<PracticeClassification />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the classification panel when session_type is Practice", () => {
    mockSnapshot({
      session_type: "Practice",
      leaderboard: [
        { driver_number: 44, in_pit: false, tyre_age: 2, compound: "SOFT", last_lap_s: 78.2 },
        { driver_number: 1, in_pit: false, tyre_age: 12, compound: "HARD", rolling5_s: 80.1 },
      ],
    });
    render(<PracticeClassification />);
    expect(screen.getByText("Practice Session Classification")).toBeInTheDocument();
  });

  it("splits drivers into short vs long runs by tyre age", () => {
    mockSnapshot({
      session_type: "Practice",
      leaderboard: [
        { driver_number: 44, in_pit: false, tyre_age: 2, compound: "SOFT", last_lap_s: 78.2 },
        { driver_number: 1, in_pit: false, tyre_age: 12, compound: "HARD", rolling5_s: 80.1 },
      ],
    });
    render(<PracticeClassification />);
    expect(screen.getByText(/Tyres: SOF/)).toBeInTheDocument();
    expect(screen.getByText(/Tyres: HAR/)).toBeInTheDocument();
    expect(screen.queryByText("No active short runs")).not.toBeInTheDocument();
    expect(screen.queryByText("No active long runs")).not.toBeInTheDocument();
  });

  it("excludes drivers currently in the pit from both columns", () => {
    mockSnapshot({
      session_type: "Practice",
      leaderboard: [{ driver_number: 7, in_pit: true, tyre_age: 3, compound: "SOFT" }],
    });
    render(<PracticeClassification />);
    expect(screen.getByText("No active short runs")).toBeInTheDocument();
  });
});
