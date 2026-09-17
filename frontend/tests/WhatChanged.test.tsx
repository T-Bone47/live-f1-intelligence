import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../src/state/store", () => ({
  useSessionState: vi.fn(),
}));

import { useSessionState } from "../src/state/store";
import { WhatChanged } from "../src/components/analysis/WhatChanged";

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

describe("WhatChanged", () => {
  it("shows the empty state with no recent events", () => {
    mockSnapshot({ recent_events: [] });
    render(<WhatChanged />);
    expect(screen.getByText("NO SIGNIFICANT RECENT EVENTS")).toBeInTheDocument();
  });

  it("shows the empty state when snapshot is null", () => {
    mockSnapshot(null);
    render(<WhatChanged />);
    expect(screen.getByText("NO SIGNIFICANT RECENT EVENTS")).toBeInTheDocument();
  });

  it("lists a significant event by its description", () => {
    mockSnapshot({
      recent_events: [
        { event_type: "OVERTAKE", ts: "2026-05-01T12:00:00Z", description: "Car 1 passes Car 44 for P1" },
      ],
    });
    render(<WhatChanged />);
    expect(screen.getByText("Car 1 passes Car 44 for P1")).toBeInTheDocument();
    expect(screen.queryByText("NO SIGNIFICANT RECENT EVENTS")).not.toBeInTheDocument();
  });

  it("filters out event types that are not on the significant list", () => {
    mockSnapshot({
      recent_events: [{ event_type: "DRS_ENABLED", description: "DRS enabled" }],
    });
    render(<WhatChanged />);
    expect(screen.getByText("NO SIGNIFICANT RECENT EVENTS")).toBeInTheDocument();
    expect(screen.queryByText("DRS enabled")).not.toBeInTheDocument();
  });

  it("caps the list at the 10 most recent significant events, newest first", () => {
    const events = Array.from({ length: 12 }, (_, i) => ({
      event_type: "PIT_STOP",
      description: `Pit stop #${i}`,
    }));
    mockSnapshot({ recent_events: events });
    render(<WhatChanged />);
    expect(screen.getByText("Pit stop #11")).toBeInTheDocument();
    expect(screen.getByText("Pit stop #2")).toBeInTheDocument();
    expect(screen.queryByText("Pit stop #1")).not.toBeInTheDocument();
    expect(screen.queryByText("Pit stop #0")).not.toBeInTheDocument();
  });
});
