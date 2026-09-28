/**
 * Car telemetry client (Phase 12C): one RAW window of one driver's stored
 * samples from the existing route
 *   GET /api/v1/sessions/{sid}/telemetry/{driver}?start&end&frequency=RAW&fields=
 *
 * Fail closed: the body must belong to the requested session and driver,
 * answer the requested window at RAW frequency, carry a known X-Data-Source,
 * and list each channel's samples in strict time order with finite values.
 */

import { ApiError, getJson, sessionPath } from "../command/api";
import { toSamples } from "./select";
import {
  CHANNELS, type Channel, type DataSource, type Sample, type TelemetryPoint, type TelemetryDoc,
  type TelemetryWindow,
} from "./types";

const refuse = (message: string): never => { throw new ApiError("unsupported", message, 200); };
const SOURCES: DataSource[] = ["recording", "database"];

function checkSeries(points: unknown, channel: Channel): Sample[] {
  if (!Array.isArray(points)) refuse(`Telemetry has no ${channel} series.`);
  let prev = -Infinity;
  for (const p of points as { ts?: unknown; value?: unknown }[]) {
    const t = Date.parse(String(p?.ts));
    if (!(t > prev)) refuse(`Telemetry ${channel} samples are out of order.`);
    if (typeof p?.value !== "number" || !Number.isFinite(p.value)) {
      refuse(`Telemetry ${channel} has a value that is not a number.`);
    }
    prev = t;
  }
  return toSamples(points as TelemetryPoint[]);
}

export async function fetchTelemetryWindow(sid: string, driver: number, fromMs: number, toMs: number,
                                           signal?: AbortSignal, f: typeof fetch = fetch): Promise<TelemetryWindow> {
  const start = new Date(fromMs).toISOString(), end = new Date(toMs).toISOString();
  const q = new URLSearchParams({ start, end, frequency: "RAW", fields: CHANNELS.join(",") });
  const { body, response } = await getJson(`${sessionPath(sid)}/telemetry/${driver}?${q}`, signal, f);
  const source = response.headers.get("X-Data-Source") as DataSource | null;
  if (!source || !SOURCES.includes(source)) refuse(`Telemetry declared ${source ?? "no data source"}.`);
  const d = body as Partial<TelemetryDoc> | null;
  if (!d || d.session_id !== sid) refuse(`Telemetry belongs to ${d?.session_id ?? "an unknown session"}, not ${sid}.`);
  if (d!.driver_number !== driver) refuse(`Telemetry is for #${d!.driver_number}, not #${driver}.`);
  if (d!.frequency !== "RAW") refuse(`Telemetry is ${d!.frequency}, not RAW.`);
  if (Date.parse(d!.window?.start ?? "") !== fromMs || Date.parse(d!.window?.end ?? "") !== toMs) {
    refuse("Telemetry does not answer the requested window.");
  }
  const samples = {} as Record<Channel, Sample[]>;
  const available = {} as Record<Channel, boolean>;
  for (const c of CHANNELS) {
    samples[c] = checkSeries(d!.series?.[c], c);
    available[c] = samples[c].length > 0;
  }
  return { sid, driver, from: fromMs, to: toMs, dataSource: source!, provenanceClass: d!.provenance?.class ?? null,
           samples, available };
}
