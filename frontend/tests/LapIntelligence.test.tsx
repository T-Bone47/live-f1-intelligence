import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../src/state/store", () => ({
  useDriverSelection: vi.fn(),
}));

import { useDriverSelection } from "../src/state/store";
import { LapIntelligence } from "../src/components/analysis/LapIntelligence";

function mockSelection(selectedDriver: number | null) {
  vi.mocked(useDriverSelection).mockReturnValue({
    selectedDriver,
    comparisonDriver: null,
    selectDriver: vi.fn(),
    selectComparisonDriver: vi.fn(),
  });
}

describe("LapIntelligence", () => {
  it("prompts for a driver when none is selected", () => {
    mockSelection(null);
    render(<LapIntelligence />);
    expect(screen.getByText("Select a driver to view lap intelligence")).toBeInTheDocument();
  });

  it("stays honest about the missing backend endpoint once a driver is selected, rather than fabricating a lap list", () => {
    mockSelection(44);
    render(<LapIntelligence />);
    expect(screen.getByText("Lap Intelligence - Driver 44")).toBeInTheDocument();
    expect(screen.getByText(/needs a dedicated backend endpoint/)).toBeInTheDocument();
  });
});
