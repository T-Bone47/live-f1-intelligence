/**
 * Race Intelligence Command Center (Phase 11) - container.
 *
 * Owns: the timeline (server state, immutable), ONE cursor and the selection
 * (UI state, URL-backed). Every panel receives the same Moment, so all of them
 * describe the same session moment. No analytical value is computed here.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchTimeline } from "../../command/api";
import {
  buildMoment, frameIndexAt, frameTimes, indexForLapToken, knownTime, lapTokenForIndex,
} from "../../command/moment";
import { NUDGE_MS, parseUrlTime, readUrl, usePlayback, useUi, writeUrl, type Density } from "../../command/state";
import { dataOf, useResource } from "../../command/useResource";
import { useSpatial } from "../../spatial/useSpatial";
import { useGhost } from "../../telemetry/useGhost";
import { useTelemetryWindow } from "../../telemetry/useTelemetryWindow";
import { CarTelemetryPanel } from "../telemetry/CarTelemetryPanel";
import { TrackMap } from "../spatial/TrackMap";
import { BattlePanel } from "./BattlePanel";
import { FocusPanel } from "./FocusPanel";
import { PositionChart } from "./PositionChart";
import { RaceControlPanel } from "./RaceControlPanel";
import { ReplayBar } from "./ReplayBar";
import { SessionLauncher } from "./SessionLauncher";
import { AppHeader, Page, SessionHeader, ShortcutHelp, type Mode } from "./Shell";
import { StrategyPanel } from "./StrategyPanel";
import { TimingTower } from "./TimingTower";
import { ErrorState, SkeletonRows } from "./ui";
import { WeatherPanel } from "./WeatherPanel";
import "./command.css";

type Tab = "timing" | "track" | "race" | "strategy" | "events";
const TABS: { id: Tab; label: string }[] = [
  { id: "timing", label: "Timing" }, { id: "track", label: "Track" }, { id: "race", label: "Race" },
  { id: "strategy", label: "Strategy" }, { id: "events", label: "Events" },
];

function isTyping(el: EventTarget | null): boolean {
  const t = el as HTMLElement | null;
  return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
}

function LoadingLayout() {
  return (
    <main id="cc-main" className="cc-main cc-loading" aria-busy="true">
      <div className="cc-skel-block cc-skel-header" />
      <div className="cc-grid">
        <div className="cc-skel-block cc-area-timing"><SkeletonRows rows={14} label="Loading timing" /></div>
        <div className="cc-skel-block cc-area-map" />
        <div className="cc-skel-block cc-area-chart" />
        <div className="cc-skel-block cc-area-focus" />
      </div>
    </main>
  );
}

function Workspace({ sid, search }: { sid: string; search: string }) {
  const url = useMemo(() => readUrl(search), [search]);
  const [reload, setReload] = useState(0);
  const res = useResource(sid, fetchTimeline, reload);
  const timeline = dataOf(res);
  const [ui, dispatch] = useUi({ driver: url.driver });
  const [help, setHelp] = useState(false);
  const [tab, setTab] = useState<Tab>("timing");

  // on arrival: cursor from a valid URL time, else the URL lap token, else the end
  useEffect(() => {
    if (!timeline) return;
    const frames = frameTimes(timeline);
    const last = frames.length - 1;
    const t = parseUrlTime(url.t, frames) ?? frames[indexForLapToken(timeline, url.lap) ?? last];
    dispatch({ type: "load", frames, t });
  }, [timeline, url.t, url.lap, dispatch]);

  usePlayback(ui.playing, dispatch);

  // the frame and the content time change far less often than t: the moment
  // object is reused between playback ticks that change nothing it lists
  const ready = !!timeline && ui.frames.length > 0;
  const index = ready ? frameIndexAt(ui.frames, ui.t) : 0;
  const knownAt = ready ? knownTime(timeline, index, ui.t) : 0;
  const moment = useMemo(() => (ready ? buildMoment(timeline, index, knownAt) : null),
    [ready, timeline, index, knownAt]);

  // URL mirrors the cursor (replaceState: scrubbing does not flood history);
  // ?t= only while the cursor sits between frames, not rewritten during playback
  useEffect(() => {
    if (!ready || typeof history === "undefined" || ui.playing) return;
    const between = ui.t !== ui.frames[index];
    const next = writeUrl({ session: sid, lap: lapTokenForIndex(timeline, index),
                            t: between ? new Date(ui.t).toISOString() : null, driver: ui.driver });
    if (next !== location.search) history.replaceState(null, "", `${location.pathname}${next}`);
  }, [ready, timeline, sid, index, ui.t, ui.frames, ui.playing, ui.driver]);

  const seek = useCallback((i: number) => dispatch({ type: "seekFrame", index: i }), [dispatch]);
  const seekTime = useCallback((ms: number) => dispatch({ type: "seekTime", t: ms }), [dispatch]);
  const selectDriver = useCallback((n: number | null) => dispatch({ type: "driver", driver: n }), [dispatch]);
  const selectBattle = useCallback((key: string | null) => dispatch({ type: "battle", key }), [dispatch]);
  const selectEvent = useCallback((key: string | null, at?: number) => dispatch({ type: "event", key, t: at }), [dispatch]);
  const setDensity = useCallback((d: Density) => dispatch({ type: "density", density: d }), [dispatch]);
  const closeFocus = useCallback(() => dispatch({ type: "driver", driver: null }), [dispatch]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || isTyping(e.target) || e.altKey || e.ctrlKey || e.metaKey) return;
      const onControl = (e.target as HTMLElement | null)?.closest?.("button, a, [role='row']");
      if ((e.key === " " && !onControl) || e.key === "k" || e.key === "K") { e.preventDefault(); dispatch({ type: "toggle" }); }
      else if (e.key === "ArrowLeft" && e.shiftKey) { e.preventDefault(); dispatch({ type: "nudge", ms: -NUDGE_MS }); }
      else if (e.key === "ArrowRight" && e.shiftKey) { e.preventDefault(); dispatch({ type: "nudge", ms: NUDGE_MS }); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); dispatch({ type: "step", by: -1 }); }
      else if (e.key === "ArrowRight") { e.preventDefault(); dispatch({ type: "step", by: 1 }); }
      else if (e.key === "Home" && !onControl) { e.preventDefault(); dispatch({ type: "seekFrame", index: 0 }); }
      else if (e.key === "End" && !onControl) { e.preventDefault(); dispatch({ type: "seekFrame", index: Number.MAX_SAFE_INTEGER }); }
      else if (e.key === "Escape") { if (help) setHelp(false); else dispatch({ type: "clear" }); }
      else if (e.key === "?") { e.preventDefault(); setHelp((v) => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dispatch, help]);

  const live = timeline?.source.kind === "LIVE_HUB";
  // Phase 12B: the backend's spatial state for the same cursor (never computed here)
  // until the timeline says whether the session is live, nothing spatial is asked for
  const spatial = useSpatial({ sid, t: ready ? ui.t : null, playing: ui.playing, rate: ui.rate, live: !timeline || !!live });
  const focusSpatial = useMemo(() => {
    if (ui.driver == null || spatial.status !== "ready" || !spatial.shown) return null;
    const d = spatial.shown.drivers.find((x) => x.driver_number === ui.driver);
    return d ? { state: d, at: spatial.shown.at } : null;
  }, [ui.driver, spatial.status, spatial.shown]);
  // Phase 12C: the selected car's stored telemetry up to the same cursor, and the
  // map ghost for a hovered sample (the driver's own location sample at or before it)
  const telemetry = useTelemetryWindow({ sid, driver: ui.driver, t: ready ? ui.t : null, playing: ui.playing,
                                         rate: ui.rate, live: !timeline || !!live });
  const [hover, setHover] = useState<{ driver: number; t: number } | null>(null);
  const hovered = hover && hover.driver === ui.driver && hover.t <= ui.t ? hover.t : null;
  const onHoverSample = useCallback((t: number | null) => {
    setHover(t == null || ui.driver == null ? null : { driver: ui.driver, t });
  }, [ui.driver]);
  const validatedTrack = spatial.status !== "unavailable" && spatial.track?.status === "VALIDATED_MAP_SECTOR"
    ? spatial.track.track_id : null;
  const ghost = useGhost({ sid, driver: ui.driver, hovered, trackId: validatedTrack });
  const mode: Mode = !timeline ? { kind: "none" }
    : live ? { kind: "live", connected: res.status === "success" }
      : { kind: "historical", replaying: ui.playing || ui.t < (ui.frames[ui.frames.length - 1] ?? 0) };
  const battlePair = useMemo((): [number, number] | null => {
    if (!ui.battle) return null;
    const [a, b] = ui.battle.split("-").map(Number);
    return [a, b];
  }, [ui.battle]);

  const header = (
    <AppHeader active="command" mode={mode} commandHref={`/?session=${encodeURIComponent(sid)}`} onHelp={() => setHelp(true)} />
  );

  if (res.status === "error" && !timeline) {
    const notFound = res.error.kind === "not_found";
    return (
      <Page>
        {header}
        <main id="cc-main" className="cc-main cc-center">
          <ErrorState
            title={notFound ? "No timeline for this session" : "The session could not be loaded"}
            message={notFound ? `${res.error.message}. Pick a recorded session on the Sessions page.` : res.error.message}
            onRetry={notFound ? undefined : () => setReload((r) => r + 1)} />
          <a className="cc-btn" href="/sessions">Browse sessions</a>
        </main>
      </Page>
    );
  }
  if (!moment) return <Page>{header}<LoadingLayout /></Page>;

  return (
    <Page className={`cc-tab-${tab}`}>
      {header}
      <main id="cc-main" className="cc-main" tabIndex={-1}>
        <SessionHeader moment={moment} />
        <nav className="cc-tabs" aria-label="Command center sections" style={{ ["--tab" as string]: TABS.findIndex((x) => x.id === tab) }}>
          {TABS.map((x) => (
            <button key={x.id} type="button" className="cc-tab" aria-pressed={tab === x.id} onClick={() => setTab(x.id)}>{x.label}</button>
          ))}
          <span className="cc-tab-indicator" aria-hidden="true" />
        </nav>
        <div className="cc-grid">
          <div className="cc-area-timing" data-tab="timing">
            <TimingTower moment={moment} selected={ui.driver} battlePair={battlePair} density={ui.density}
                         onSelect={selectDriver} onDensity={setDensity} />
          </div>
          <div className="cc-area-map" data-tab="track">
            <TrackMap view={spatial} moment={moment} selected={ui.driver} battle={battlePair}
                      playing={ui.playing} rate={ui.rate} onSelect={selectDriver} ghost={ghost.ghost} />
          </div>
          <div className="cc-area-chart" data-tab="race">
            <PositionChart moment={moment} selected={ui.driver} onSelect={selectDriver} onSeek={seek} />
          </div>
          <div className="cc-area-battles" data-tab="race">
            <BattlePanel moment={moment} selected={ui.battle} onSelect={selectBattle} />
          </div>
          <div className="cc-area-focus" data-tab="timing">
            <FocusPanel moment={moment} driver={ui.driver} spatial={focusSpatial}
                        onClose={closeFocus} onSeek={seek} />
          </div>
          <div className="cc-area-telemetry" data-tab="timing">
            <CarTelemetryPanel telemetry={telemetry} driver={ui.driver}
                               ident={ui.driver != null ? moment.driver.get(ui.driver) : undefined}
                               playing={ui.playing} hovered={hovered} onHover={onHoverSample} ghostStatus={ghost.status} />
          </div>
          <div className="cc-area-strategy" data-tab="strategy">
            <StrategyPanel moment={moment} selected={ui.driver} onSelectDriver={selectDriver} onSeek={seek} />
          </div>
          <div className="cc-area-rc" data-tab="events">
            <RaceControlPanel moment={moment} selectedKey={ui.rcKey} onSelect={selectEvent} />
          </div>
          <div className="cc-area-weather" data-tab="events">
            <WeatherPanel moment={moment} />
          </div>
        </div>
      </main>
      <ReplayBar moment={moment} t={ui.t} playing={ui.playing} rate={ui.rate} live={live}
                 onSeekTime={seekTime} onSeekFrame={seek} onStep={(by) => dispatch({ type: "step", by })}
                 onToggle={() => dispatch({ type: "toggle" })} onRate={(r) => dispatch({ type: "rate", rate: r })} />
      <ShortcutHelp open={help} onClose={() => setHelp(false)} />
    </Page>
  );
}

/** Route entry: with ?session= the workspace, without it the session list. */
export function CommandCenter({ search = typeof location !== "undefined" ? location.search : "" }: { search?: string }) {
  const sid = readUrl(search).session;
  if (!sid) return <SessionLauncher />;
  return <Workspace key={sid} sid={sid} search={search} />;
}
