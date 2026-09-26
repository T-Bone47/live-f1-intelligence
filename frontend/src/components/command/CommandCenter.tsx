/**
 * Race Intelligence Command Center (Phase 11) - container.
 *
 * Owns: the timeline (server state, immutable), ONE cursor and the selection
 * (UI state, URL-backed). Every panel receives the same Moment, so all of them
 * describe the same session moment. No analytical value is computed here.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchTimeline } from "../../command/api";
import { buildMoment, indexForLapToken, lapTokenForIndex } from "../../command/moment";
import { readUrl, usePlayback, useUi, writeUrl, type Density } from "../../command/state";
import { dataOf, useResource } from "../../command/useResource";
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

type Tab = "timing" | "race" | "strategy" | "events";
const TABS: { id: Tab; label: string }[] = [
  { id: "timing", label: "Timing" }, { id: "race", label: "Race" },
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

  // on arrival: cursor from the URL lap token, else the end of the recording
  useEffect(() => {
    if (!timeline) return;
    const last = timeline.frames.length - 1;
    dispatch({ type: "load", last, index: indexForLapToken(timeline, url.lap) ?? last });
  }, [timeline, url.lap, dispatch]);

  usePlayback(ui.playing, ui.speed, dispatch);

  const moment = useMemo(() => (timeline ? buildMoment(timeline, ui.index) : null), [timeline, ui.index]);

  // URL mirrors the moment (replaceState: scrubbing does not flood history)
  useEffect(() => {
    if (!timeline || typeof history === "undefined") return;
    const next = writeUrl({ session: sid, lap: lapTokenForIndex(timeline, ui.index), driver: ui.driver });
    if (next !== location.search) history.replaceState(null, "", `${location.pathname}${next}`);
  }, [timeline, sid, ui.index, ui.driver]);

  const seek = useCallback((i: number) => dispatch({ type: "seek", index: i }), [dispatch]);
  const selectDriver = useCallback((n: number | null) => dispatch({ type: "driver", driver: n }), [dispatch]);
  const selectBattle = useCallback((key: string | null) => dispatch({ type: "battle", key }), [dispatch]);
  const selectEvent = useCallback((key: string | null, index?: number) => dispatch({ type: "event", key, index }), [dispatch]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || isTyping(e.target) || e.altKey || e.ctrlKey || e.metaKey) return;
      const onControl = (e.target as HTMLElement | null)?.closest?.("button, a, [role='row']");
      if ((e.key === " " && !onControl) || e.key === "k" || e.key === "K") { e.preventDefault(); dispatch({ type: "toggle" }); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); dispatch({ type: "step", by: -1 }); }
      else if (e.key === "ArrowRight") { e.preventDefault(); dispatch({ type: "step", by: 1 }); }
      else if (e.key === "Home" && !onControl) { e.preventDefault(); dispatch({ type: "seek", index: 0 }); }
      else if (e.key === "End" && !onControl) { e.preventDefault(); dispatch({ type: "seek", index: Number.MAX_SAFE_INTEGER }); }
      else if (e.key === "Escape") { if (help) setHelp(false); else dispatch({ type: "clear" }); }
      else if (e.key === "?") { e.preventDefault(); setHelp((v) => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dispatch, help]);

  const live = timeline?.source.kind === "LIVE_HUB";
  const mode: Mode = !timeline ? { kind: "none" }
    : live ? { kind: "live", connected: res.status === "success" }
      : { kind: "historical", replaying: ui.playing || ui.index < ui.last };
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
                         onSelect={selectDriver} onDensity={(d: Density) => dispatch({ type: "density", density: d })} />
          </div>
          <div className="cc-area-chart" data-tab="race">
            <PositionChart moment={moment} selected={ui.driver} onSelect={selectDriver} onSeek={seek} />
          </div>
          <div className="cc-area-battles" data-tab="race">
            <BattlePanel moment={moment} selected={ui.battle} onSelect={selectBattle} />
          </div>
          <div className="cc-area-focus" data-tab="timing">
            <FocusPanel moment={moment} driver={ui.driver} onClose={() => selectDriver(null)} onSeek={seek} />
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
      <ReplayBar moment={moment} playing={ui.playing} speed={ui.speed} live={live}
                 onSeek={seek} onStep={(by) => dispatch({ type: "step", by })}
                 onToggle={() => dispatch({ type: "toggle" })} onSpeed={(s) => dispatch({ type: "speed", speed: s })} />
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
