import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("../src/state/store", () => ({
  useSessionState: vi.fn(),
  useDriverSelection: vi.fn(),
  apiGet: vi.fn(),
}));

import { useSessionState, useDriverSelection, apiGet } from "../src/state/store";
import { TimeDelta, TheoreticalLap } from "../src/components/analysis/TimeDelta";

function mockState(selectedDriver: number | null, comparisonDriver: number | null = null) {
  vi.mocked(useSessionState).mockReturnValue({
    sessionId: "openf1:test",
    status: "LIVE",
    seq: 1,
    snapshot: { session_id: "openf1:test", leaderboard: [{ driver_number: 44, personal_best_s: 79.0 }] },
    recentEvents: [],
    telemetry: {},
    lastUpdate: null,
    aiInsights: [],
  } as any);
  vi.mocked(useDriverSelection).mockReturnValue({
    selectedDriver,
    comparisonDriver,
    selectDriver: vi.fn(),
    selectComparisonDriver: vi.fn(),
  });
  vi.mocked(apiGet).mockResolvedValue({ available: false });
}

describe("TimeDelta", () => {
  it("renders nothing until both a selected and comparison driver are picked", () => {
    mockState(44, null);
    const { container } = render(<TimeDelta />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while sector data has not loaded yet", () => {
    mockState(44, 1);
    vi.mocked(apiGet).mockReturnValue(new Promise(() => {})); // never resolves
    const { container } = render(<TimeDelta />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the sector-by-sector delta once both drivers' sectors are available", async () => {
    mockState(44, 1);
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (path.includes("/44")) {
        return { available: true, personal_best: { S1: 20.0, S2: 30.0, S3: 25.0 }, theoretical_lap_s: 74.5 };
      }
      return { available: true, personal_best: { S1: 20.5, S2: 29.5, S3: 25.2 }, theoretical_lap_s: 74.9 };
    });
    render(<TimeDelta />);
    await waitFor(() => expect(screen.getByText("WHERE DID THE TIME GO?")).toBeInTheDocument());
    expect(screen.getByText("#44")).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("TOTAL DELTA")).toBeInTheDocument();
    expect(screen.getByText("THEORETICAL DELTA")).toBeInTheDocument();
  });
});

describe("TheoreticalLap", () => {
  it("renders nothing with no driver selected", () => {
    mockState(null);
    const { container } = render(<TheoreticalLap />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows actual vs theoretical best and the potential gain once sectors load", async () => {
    mockState(44);
    vi.mocked(apiGet).mockResolvedValue({ available: true, theoretical_lap_s: 78.0 });
    render(<TheoreticalLap />);
    await waitFor(() => expect(screen.getByText("THEORETICAL LAP")).toBeInTheDocument());
    expect(screen.getByText("ACTUAL BEST")).toBeInTheDocument();
    expect(screen.getByText("POTENTIAL GAIN")).toBeInTheDocument();
  });
});
