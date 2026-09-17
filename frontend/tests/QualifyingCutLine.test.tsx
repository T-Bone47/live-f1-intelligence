import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../src/state/store", () => ({
  useSessionState: vi.fn(),
}));

import { useSessionState } from "../src/state/store";
import { QualifyingCutLine } from "../src/components/analysis/QualifyingCutLine";

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

const board15 = Array.from({ length: 20 }, (_, i) => ({
  driver_number: i + 1,
  position: i + 1,
  personal_best_s: 80 + i * 0.1,
}));

describe("QualifyingCutLine", () => {
  it("renders nothing outside a qualifying session", () => {
    mockSnapshot({ session_type: "Practice", leaderboard: board15 });
    const { container } = render(<QualifyingCutLine />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when session_type is missing entirely", () => {
    mockSnapshot({ leaderboard: board15 });
    const { container } = render(<QualifyingCutLine />);
    expect(container).toBeEmptyDOMElement();
  });

  it("defaults to a P15 cut line (Q1) when phase gives no Q2/Q3 hint", () => {
    mockSnapshot({ session_type: "Qualifying", leaderboard: board15 });
    render(<QualifyingCutLine />);
    expect(screen.getByText("Top 15 advance to the next session")).toBeInTheDocument();
  });

  it("shows a P10 cut line when phase indicates Q2", () => {
    mockSnapshot({ session_type: "Qualifying", phase: "Q2", leaderboard: board15 });
    render(<QualifyingCutLine />);
    expect(screen.getByText("Top 10 advance to the next session")).toBeInTheDocument();
  });

  it("renders nothing in Q3 (no cut line to show)", () => {
    mockSnapshot({ session_type: "Qualifying", phase: "Q3", leaderboard: board15 });
    const { container } = render(<QualifyingCutLine />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing with an empty leaderboard", () => {
    mockSnapshot({ session_type: "Qualifying", leaderboard: [] });
    const { container } = render(<QualifyingCutLine />);
    expect(container).toBeEmptyDOMElement();
  });
});
