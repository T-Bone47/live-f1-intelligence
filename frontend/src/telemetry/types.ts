/**
 * Car telemetry route body (GET /api/v1/sessions/{sid}/telemetry/{driver},
 * RAW frequency). Every point is one stored sample; a null sample is omitted
 * from that channel by the backend, never sent as 0.
 */

export const CHANNELS = ["speed", "throttle", "brake", "gear", "rpm", "drs"] as const;
export type Channel = (typeof CHANNELS)[number];

/** Two samples further apart than this are never joined (the project's MAX_GAP_S). */
export const MAX_GAP_MS = 2000;

export type DataSource = "recording" | "database";

export interface TelemetryPoint { ts: string; value: number }

export interface TelemetryDoc {
  session_id: string;
  driver_number: number;
  frequency: string;
  lap: number | null;
  window: { start: string; end: string };
  provenance: { class: string | null; kind: string };
  series: Partial<Record<Channel, TelemetryPoint[]>>;
}

/** One stored sample: t in epoch milliseconds. */
export interface Sample { t: number; value: number }

/** A stretch longer than MAX_GAP_MS with no sample, between two real samples. */
export interface Gap { from: number; to: number }

export interface ChannelView {
  /** The channel has at least one sample in the loaded window. */
  available: boolean;
  /** Samples at or before the cursor, split wherever two are more than 2 s apart. */
  runs: Sample[][];
  gaps: Gap[];
  /** The last sample at or before the cursor. */
  latest: Sample | null;
  /** From the last sample to the cursor, when that is more than MAX_GAP_MS: the value is stale, not current. */
  trailing: Gap | null;
}

export interface TelemetryWindow {
  sid: string;
  driver: number;
  from: number;
  to: number;
  dataSource: DataSource;
  provenanceClass: string | null;
  samples: Record<Channel, Sample[]>;
  available: Record<Channel, boolean>;
}
