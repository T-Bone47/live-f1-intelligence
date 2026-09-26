/**
 * TypeScript mirror of the Phase 12A/12B spatial contracts
 * (backend/app/spatial/contract.py). The only description of them on the
 * frontend. Coordinates are OpenF1 feed units (arbitrary origin, undocumented
 * unit): they place things on screen, never become metres. Metres come only
 * from the contract's own `distance_m` / `length_m` (cited lap length).
 */

export const TRACK_CONTRACT = "track_reference_v1";
export const STATE_CONTRACT = "spatial_state_v1";
export const WINDOW_CONTRACT = "spatial_window_v1";

export type LineName = "FINISH" | "S1" | "S2";
export type SpatialStatus = "POSITIONED" | "STALE" | "NO_COVERAGE";
export type SpatialFlag = "ON_REFERENCE" | "PIT_LANE" | "OFF_REFERENCE";
export type Grade = "HIGH" | "MEDIUM" | "LOW" | "NONE";

export interface Limitation { code: string; message: string }

export interface Dispersion { median: number; p90: number; p95: number; p99: number; max: number }

export interface TimingLine {
  line: LineName;
  loop_fraction: number | null;
  distance_m: number | null;
  x: number | null;
  y: number | null;
  n: number;
  exclusions: Record<string, number>;
  dispersion_m: Dispersion | null;
  dispersion_fraction: Dispersion;
  worst: { driver_number: number; lap_number: number; value: number; unit: "m" | "fraction" }[];
}

export interface SectorGeometry {
  sector: 1 | 2 | 3;
  from_line: LineName;
  to_line: LineName;
  length_m: number;
  polyline: number[][];
  label_point: number[];
}

export interface Gate {
  claim: "MAP_SECTOR" | "CORNER";
  passed: boolean;
  threshold_m: number;
  observed_p95_m: Record<string, number | null>;
  reasons: string[];
}

export interface Capability { available: false; reason: string; evidence: Record<string, number | null> }

export interface TrackReference {
  contract_version: typeof TRACK_CONTRACT;
  builder_version: string;
  track_id: string;
  status: "VALIDATED_MAP_SECTOR" | "UNVALIDATED";
  session: { session_id: string; circuit_short_name: string | null; session_type: string | null;
             year: number | null; date_start: string | null };
  circuit: { short_name: string | null; lap_length_m: number | null; lap_length_source: string | null };
  coordinate_system: { kind: "OPENF1_LOCATION_FEED"; units: "undocumented"; origin: "arbitrary";
                       measured_units_per_metre: number | null };
  reference: { driver_number: number; lap_number: number; started_at: string; duration_s: number;
               point_count: number; loop_length_feed_units: number; polyline: number[][] | null } | null;
  timing_lines: TimingLine[];
  sectors: SectorGeometry[];
  validation: {
    gates: Record<string, Gate>;
    reference_independence_m: number | null;
    on_reference_tol: { feed_units: number; n: number; lateral_percentiles: Record<string, number>;
                        pit_inside_share: number | null; provisional: boolean } | null;
    pit_windows: { mode: "ENTRY" | "EXIT" | "NONE"; share_entry: number | null; share_exit: number | null;
                   samples_entry: number; samples_exit: number } | null;
    reasons: string[];
  };
  capabilities: Record<"racing_line" | "drs_zones" | "corners" | "pit_lane_geometry", Capability>;
  limitations: Limitation[];
  provenance: { chain: string[]; input_digest: string; counts: Record<string, number>;
                reference_candidates: { driver_number: number; lap_number: number; duration_s: number }[] };
}

export interface DriverState {
  driver_number: number;
  status: SpatialStatus;
  flag: SpatialFlag | null;
  confidence: Grade | null;
  x: number | null;
  y: number | null;
  reference_fraction: number | null;
  distance_m: number | null;
  sector: 1 | 2 | 3 | null;
  lap_number: number | null;
  bracket: { before: string; after: string; gap_s: number } | null;
  age_s: number | null;
}

export interface SpatialState {
  contract_version: typeof STATE_CONTRACT;
  builder_version: string;
  session_id: string;
  track_id: string;
  at: string;
  lap_length_m: number | null;
  line_placement_p95_m: Record<string, number> | null;
  drivers: DriverState[];
  limitations: Limitation[];
}

export interface SpatialWindow {
  contract_version: typeof WINDOW_CONTRACT;
  builder_version: string;
  session_id: string;
  track_id: string;
  from_ts: string;
  to_ts: string;
  step_s: number;
  lap_length_m: number | null;
  line_placement_p95_m: Record<string, number> | null;
  states: { at: string; drivers: DriverState[] }[];
  limitations: Limitation[];
}
