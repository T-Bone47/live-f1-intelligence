/**
 * TypeScript mirror of the Phase 11 backend contracts. The only description
 * of these shapes on the frontend:
 *   session_timeline_v1  backend/app/analysis/timeline.py (TimelineRecorder.to_dict)
 *   GET /api/v1/sessions and /sessions/{sid}/laps  backend/app/storage/db.py
 * Every value is the backend's; nullable fields are nullable upstream.
 */

export const TIMELINE_CONTRACT = "session_timeline_v1";

export type FrameKind = "START" | "LAP" | "FINAL";

/** SessionPhase (backend/app/core/session_state.py). */
export type SessionPhase =
  | "UNKNOWN" | "SCHEDULED" | "FORMATION" | "LIVE" | "SAFETY_CAR" | "VSC"
  | "RED_FLAG" | "SUSPENDED" | "CHEQUERED" | "FINISHED" | string;

/** TrackFlag (backend/app/core/session_state.py). */
export type TrackFlag =
  | "GREEN" | "YELLOW" | "DOUBLE_YELLOW" | "CLEAR" | "RED" | "CHEQUERED" | "UNKNOWN" | string;

/** BattleState (backend/app/analysis/battles.py). APPROACHING is never in a snapshot. */
export type BattleState =
  | "DRS_RANGE" | "ACTIVE_BATTLE" | "OVERTAKE" | "DEFENDING" | "SEPARATING" | string;

export interface SectorCrossing { time_s: number; status: "PURPLE" | "GREEN" | "YELLOW" | null }

/** One leaderboard row: AnalysisEngine snapshot row + observed extras. */
export interface TimingRow {
  position: number | null;
  driver_number: number;
  lap_number: number | null;
  last_lap_s: number | null;
  personal_best_s: number | null;
  gap_to_leader_raw: string | null;   // '+1 LAP' verbatim, never converted
  gap_to_leader_s: number | null;
  interval_s: number | null;
  compound: string | null;
  tyre_age: number | null;            // engine: laps since stint start lap (0-based)
  stint_number: number | null;
  rolling5_s: number | null;
  pace_trend_s_per_lap: number | null;
  clean_air: string | null;
  in_pit: boolean;
  retired: boolean;
  position_change: number | null;     // vs previous frame, + = places gained
  pit_stops: number;
  stint_laps_completed: number | null;
  tyre_age_at_start: number | null;
  tyre_laps_on_set: number | null;
  sectors_last: Record<string, SectorCrossing>;
}

export interface Battle {
  ahead: number;
  behind: number;
  state: BattleState;
  min_gap_s: number | null;
  last_gap_s: number | null;
  started_lap: number | null;
}

export interface WeatherNow {
  air_temp_c?: number;
  track_temp_c?: number;
  humidity_pct?: number;
  wind_speed_mps?: number;
  wind_direction_deg?: number;
  rainfall?: boolean;
}

export interface Frame {
  index: number;
  kind: FrameKind;
  lap: number | null;
  at: string | null;
  phase: SessionPhase;
  track_flag: TrackFlag;
  current_lap: number | null;
  fastest_lap: { driver: number | null; duration_s: number | null; at_lap: number | null } | null;
  sector_leaders: Record<string, { time_s: number; driver: number }>;
  weather: WeatherNow;
  active_battles: Battle[];
  rows: TimingRow[];
}

export interface DriverIdentity {
  driver_number: number;
  acronym: string | null;
  full_name: string | null;
  broadcast_name: string | null;
  team_id: string | null;
  team_name: string | null;
  team_colour: string | null;         // provider hex without '#', verbatim
}

export interface Stint {
  driver_number: number;
  stint_number: number;
  compound: string | null;
  lap_start: number | null;
  lap_end: number | null;
  tyre_age_at_start: number | null;
}

export interface PitStop {
  driver_number: number;
  ts: string | null;
  lap_number: number | null;
  lane_duration_s: number | null;
  stop_duration_s: number | null;
  frame_index: number;
  stint_before: number | null;
  compound_before: string | null;
  stint_after: number | null;
  compound_after: string | null;
}

export interface RaceControlMessage {
  ts: string | null;
  lap_number: number | null;
  category: string | null;
  flag: string | null;
  scope: string | null;
  marshal_sector: number | null;
  driver_number: number | null;
  message: string | null;
  rcm_key: string | null;
  frame_index: number;
}

export interface WeatherSample {
  ts: string | null;
  air_temp_c: number | null;
  track_temp_c: number | null;
  humidity_pct: number | null;
  pressure_hpa: number | null;
  rainfall: boolean | null;
  wind_direction_deg: number | null;
  wind_speed_mps: number | null;
  frame_index: number;
}

export interface TimelineEvent {
  event_key: string;
  event_type: string;
  timestamp: string;
  drivers: number[];
  severity: string;
  metrics: Record<string, unknown>;
  evidence: string[];
  frame_index: number;
}

export interface SessionMeta {
  session_id: string;
  provider: string | null;
  provider_session_key: string | null;
  provider_meeting_key: string | null;
  meeting_name: string | null;
  year: number | null;
  session_type: string | null;
  session_name: string | null;
  circuit_short_name: string | null;
  country_code: string | null;
  country_name: string | null;
  location: string | null;
  gmt_offset: string | null;
  date_start: string | null;
  date_end: string | null;
}

export interface Limitation { code: string; message: string }

export interface Timeline {
  contract_version: typeof TIMELINE_CONTRACT;
  builder_version: string;
  calc_version: string;
  profile: string | null;
  session: SessionMeta | null;
  source: {
    kind: "RECORDING" | "LIVE_HUB" | string;
    recording?: string;
    provider?: string | null;
    envelopes_folded: number;
    input_digest: string;
    [k: string]: unknown;
  };
  drivers: DriverIdentity[];
  laps_completed_max: number | null;
  frames: Frame[];
  stints: Stint[];
  pit_stops: PitStop[];
  race_control: RaceControlMessage[];
  weather: WeatherSample[];
  events: TimelineEvent[];
  capabilities: {
    drs_availability: boolean;
    undercut_overcut: boolean;
    track_geometry: boolean;
    retirement_status: boolean;
    scheduled_race_distance: boolean;
  };
  limitations: Limitation[];
}

// ------------------------------------------------------------- discovery --

export interface ActiveSession { session_id: string; clients: number; phase: string }

export interface StoredSession {
  session_id: string;
  provider: string;
  provider_session_key: string;
  meeting_name: string | null;
  year: number | null;
  session_type: string | null;
  session_name: string | null;
  circuit_short_name: string | null;
  country_code: string | null;
  country_name: string | null;
  location: string | null;
  date_start: string | null;
  date_end: string | null;
  status: string | null;
  drivers: number;
  laps: number | null;
  max_lap: number | null;
  has_car_telemetry: boolean;
  timeline_available: boolean;
}

export interface SessionCatalog {
  active: ActiveSession[];
  stored: StoredSession[];
  stored_error?: string;
}

export interface CatalogLap {
  lap_number: number;
  started_at: string | null;
  duration_s: number | null;
  deleted: boolean;
  is_pit_out_lap: boolean | null;
  has_car_telemetry: boolean;
}

export interface CatalogDriver {
  driver_number: number;
  acronym: string | null;
  full_name: string | null;
  team_name: string | null;
  team_colour: string | null;
  laps: CatalogLap[];
}

export interface LapCatalog { session_id: string; drivers: CatalogDriver[] }
