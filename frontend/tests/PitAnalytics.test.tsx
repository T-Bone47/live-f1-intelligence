import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../src/state/store", () => ({
  useSessionState: vi.fn(),
  useDriverSelection: vi.fn(),
  useEvents: vi.fn(),
}));

import { useSessionState, useDriverSelection, useEvents } from "../src/state/store";
import { PitAnalytics } from "../src/components/analysis/PitAnalytics";

function setup(selectedDriver: number | null, events: any[] = []) {
  vi.mocked(useSessionState).mockReturnValue({
    sessionId: "openf1:test",
    status: "LIVE",
    seq: 1,
    snapshot: { session_id: "openf1:test" },
    recentEvents: [],
    telemetry: {},
    lastUpdate: null,
    aiInsights: [],
  } as any);
  vi.mocked(useDriverSelection).mockReturnValue({
    selectedDriver,
    comparisonDriver: null,
    selectDriver: vi.fn(),
    selectComparisonDriver: vi.fn(),
  });
  vi.mocked(useEvents).mockReturnValue(events);
}

describe("PitAnalytics", () => {
  it("prompts for a driver when none is selected", () => {
    setup(null);
    render(<PitAnalytics />);
    expect(screen.getByText("Select a driver to view pit analytics")).toBeInTheDocument();
  });

  it("shows the empty state when the selected driver has no pit stops yet", () => {
    setup(44, []);
    render(<PitAnalytics />);
    expect(screen.getByText("No pit stops recorded yet")).toBeInTheDocument();
  });

  it("lists a pit stop with its lane duration for the selected driver", () => {
    setup(44, [
      {
        event_type: "PIT_STOP",
        drivers: [44],
        ts: "2026-05-01T12:00:00Z",
        metrics: { lane_duration_s: 22.4 },
      },
    ]);
    render(<PitAnalytics />);
    expect(screen.getByText("STOP 1")).toBeInTheDocument();
    expect(screen.getByText("22.400")).toBeInTheDocument();
  });

  it("ignores pit stops belonging to a different driver", () => {
    setup(44, [{ event_type: "PIT_STOP", drivers: [1], ts: "2026-05-01T12:00:00Z" }]);
    render(<PitAnalytics />);
    expect(screen.getByText("No pit stops recorded yet")).toBeInTheDocument();
  });

  it("ignores non-pit-stop event types", () => {
    setup(44, [{ event_type: "OVERTAKE", drivers: [44] }]);
    render(<PitAnalytics />);
    expect(screen.getByText("No pit stops recorded yet")).toBeInTheDocument();
  });
});
