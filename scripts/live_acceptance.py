"""live_acceptance - Phase 7 automated acceptance harness.

Run DURING a genuine live F1 session window:

    python scripts/live_acceptance.py                # auto-detect latest session
    python scripts/live_acceptance.py --duration 3600 --signalr

Writes artifacts/live-<session_key>/:
    acceptance.json   measured latencies per channel (p50/p95/p99), event
                      counts, AI metrics, security scan
    snapshot.json     final SessionSnapshot
    intelligence.json Phase-5 intelligence summary
    ai_events.jsonl   every intelligence event raised during the window
    quality.json      data-quality report
    recordings/...    raw+canonical frames for LIVE->REPLAY determinism

If no session is live: prints WAITING_FOR_LIVE_SESSION and exits 3.
Replay determinism check runs separately after the session:
    python scripts/backtest_analysis.py <the recording produced here>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("live_acceptance")


from app.config import get_settings  # noqa: E402


def security_scan() -> dict:
    key = get_settings().gemini_api_key or ""
    if not key or key == "your_key_here":
        return {"status": "NO_KEY", "violations": []}
    violations: list[str] = []
    skip = (".venv", "node_modules", ".local-pg", "recordings",
            "__pycache__", ".git")
    for f in Path(".").rglob("*"):
        if any(x in str(f) for x in skip):
            continue
        if f.is_file() and f.suffix in (".py", ".md", ".ts", ".tsx", ".json",
                                        ".yml", ".yaml", ".example", ".toml"):
            try:
                if key in f.read_text(encoding="utf-8", errors="ignore"):
                    violations.append(str(f))
            except Exception:
                pass
    gi = Path(".gitignore").read_text(encoding="utf-8")
    return {"status": "PASS" if (not violations and ".env" in gi.splitlines())
            else "FAIL", "violations": violations,
            "env_gitignored": ".env" in gi.splitlines()}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="latest")
    ap.add_argument("--provider", choices=["openf1"], default="openf1")
    ap.add_argument("--signalr", action="store_true",
                    help="attempt concurrent SignalR capture when available")
    ap.add_argument("--duration", type=int, default=0,
                    help="seconds to capture; 0 = until Ctrl+C/session end")
    args = ap.parse_args()

    s = get_settings()

    # ------------------------------------------------------------ connect --
    from app.providers.openf1.client import OpenF1Client, OpenF1Error
    from app.providers.openf1.provider import OpenF1Provider

    print("CONNECTING to OpenF1 ...")
    client = OpenF1Client(s)
    provider = OpenF1Provider(client, s)

    signalr_status = "NOT_ATTEMPTED"
    if args.signalr:
        print("SIGNALR: probe deferred to scripts/probe_signalr.py "
              "(run concurrently; results merge into the report)")
        signalr_status = "PROBE_SEPARATELY"

    try:
        session = await provider.resolve_session(args.ref)
    except OpenF1Error as exc:
        print(f"FAILED: {exc}")
        await client.aclose()
        return 2

    state = provider.classify_session_state(session)
    if state != "live":
        print("WAITING_FOR_LIVE_SESSION")
        print(f"  {session.session_id} [{state}] "
              f"{session.session_name} @ {session.circuit_short_name}")
        print("  Per Phase-7 rule 23 the live acceptance is deferred.")
        print("  Next window probe: python scripts/next_session_probe.py")
        await client.aclose()
        return 3

    print(f"SESSION FOUND: {session.session_id} "
          f"{session.session_type.value} @ {session.circuit_short_name}")

    # ------------------------------------------------------------- stack ---
    from app.ai.gateway import LLMGateway
    from app.ai.jobs import AIRuntime
    from app.ai.providers import build_provider
    from app.analysis import AnalysisEngine
    from app.core.events import EventBus
    from app.ingest.persistence import PersistenceSubscriber
    from app.ingest.pipeline import IngestPipeline
    from app.realtime.hub import SessionHub
    from app.storage.db import Repository, apply_migrations, connect

    pool = None
    repo = None
    persistence = None
    try:
        pool = await connect(s.database_url)
        applied = await apply_migrations(pool)
        if applied:
            log.info("migrations applied: %s", applied)
        repo = Repository(pool)
        persistence = PersistenceSubscriber(repo)
    except Exception as exc:  # noqa: BLE001 - DB optional for capture
        log.warning("database unavailable (%s) - capturing without persistence",
                    exc)

    engine = AnalysisEngine(session_id=session.session_id)
    pipeline = IngestPipeline(session_id=session.session_id)
    hub = SessionHub(session_id=session.session_id)
    # share ONE pipeline/bus across hub + analysis (production wiring)
    hub_pipeline_bus = pipeline.bus

    ai_provider = build_provider(
        s.llm_provider,
        base_url=(None if s.llm_provider == "gemini" else s.llm_base_url),
        api_key=(s.gemini_api_key if s.llm_provider == "gemini"
                 else s.llm_api_key),
        model=s.llm_model)
    air = AIRuntime(LLMGateway(ai_provider),
                    auto_enabled=s.llm_auto_commentary,
                    get_mode=lambda: "LIVE")
    hub.attach_ai(air)
    await air.start_worker()

    # subscribers on the shared bus
    async def _analysis(env) -> None:  # noqa: ANN001 Envelope
        t0 = time.perf_counter()
        hub.engine.process_envelope(env)
        hub.metrics.observe_analysis((time.perf_counter() - t0) * 1000)

    def _ai_trigger(ev) -> None:  # noqa: ANN001 IntelligenceEvent
        try:
            air.trigger_from_event(ev)
        except Exception:  # noqa: BLE001
            log.exception("ai trigger failed")

    pipeline.bus.subscribe("analysis", _analysis)
    engine.sig.listeners.append(_ai_trigger)
    if persistence is not None:
        pipeline.bus.subscribe("db", persistence.__call__)

    from app.ingest.recorder import Recorder  # local import (artifact-scoped)

    rec_name = f"live-{session.provider_session_key}-" \
               f"{session.session_type.value.lower()}"
    recorder_dir = Path(s.recordings_dir)
    recorder_dir.mkdir(parents=True, exist_ok=True)
    recorder = Recorder(recorder_dir, rec_name)

    async def _record(env) -> None:  # noqa: ANN001 Envelope
        recorder.write(env)

    pipeline.bus.subscribe("recorder", _record)

    # ------------------------------------------------------------- loops --

    stop = asyncio.Event()

    async def upstream() -> None:
        hub.metrics.provider_status = "CONNECTED"
        log.info("upstream connected")
        try:
            async for item in provider.run(session):
                await hub.feed(item)
        except Exception as exc:  # noqa: BLE001
            log.exception("upstream failed")
            hub.metrics.provider_status = f"FAILED: {type(exc).__name__}"
        engine.flush_deferred()
        log.info("upstream finished")
        up_done.set()

    up_done = asyncio.Event()
    up_task = asyncio.create_task(upstream())
    publish_task = asyncio.create_task(hub.run())

    deadline = time.monotonic() + args.duration if args.duration else None
    try:
        while not up_done.is_set():
            if deadline and time.monotonic() > deadline:
                break
            await asyncio.sleep(5)
            m = hub.metrics.as_dict()
            q = pipeline.quality.report()["latency_live_class_a"]
            print(f"  ev/s={m['events_per_sec']} seq={hub.history.current} "
                  f"src->ing p50={q.get('p50')}s "
                  f"clients={m['websocket']['clients']}", flush=True)
    except KeyboardInterrupt:
        print("\nCtrl+C - finalizing")

    hub.stop()
    engine.flush_deferred()
    await air.stop()
    up_task.cancel()
    publish_task.cancel()
    for t in (up_task, publish_task):
        try:
            await t
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    # ---------------------------------------------------------- artifacts --
    out_dir = Path("artifacts") / f"live-{session.provider_session_key}"
    out_dir.mkdir(parents=True, exist_ok=True)

    snap = engine.snapshot_dict()
    intel = engine.intelligence()
    quality = pipeline.quality.report()

    channel_latency = {
        ch: quality.get("channel_latency", {}).get(ch)
        for ch in ("timing", "telemetry", "position", "sector", "tyre",
                   "weather", "rc")}
    m = hub.metrics.as_dict()

    acceptance = {
        "phase7": True,
        "mode": "LIVE",
        "session": {
            "id": session.session_id,
            "type": session.session_type.value,
            "name": session.session_name,
            "circuit": session.circuit_short_name,
            "country": session.country_code,
            "start": session.date_start.isoformat() if session.date_start else None,
        },
        "providers": {
            "primary": {"name": "openf1",
                        "status": hub.metrics.provider_status,
                        "reconnects": hub.metrics.reconnects},
            "signalr": signalr_status,
        },
        "event_counts": pipeline.quality.report()["channel_counts"],
        "latency": {
            "source_to_ingestion_per_channel": channel_latency,
            "ingestion_to_analysis_ms": m["analysis_latency_ms"],
            "snapshot_build_ms": m["snapshot_latency_ms"],
            "diff_ms": m["diff_latency_ms"],
            "ws_broadcast_ms": m["ws_broadcast_latency_ms"],
            "note": "snapshot->WS->browser segment measured separately by "
                    "load_test_ws.py (loopback); browser leg requires the UI",
        },
        "ai": {
            **air.status(),
            "intelligence_events_raised":
                sum(1 for e in engine.sig.events),
        },
        "quality_report": {
            k: quality[k] for k in
            ("malformed_events", "duplicate_events", "reconnects",
             "drivers_detected")},
        "security": security_scan(),
        "measured_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "acceptance.json").write_text(json.dumps(acceptance, indent=2),
                                             encoding="utf-8")
    (out_dir / "snapshot.json").write_text(json.dumps(snap, indent=2),
                                           encoding="utf-8")
    (out_dir / "intelligence.json").write_text(json.dumps(intel, indent=2),
                                               encoding="utf-8")
    quality_path = out_dir / "quality.json"
    quality_path.write_text(json.dumps(quality, indent=2), encoding="utf-8")
    with open(out_dir / "ai_events.jsonl", "w", encoding="utf-8") as fh:
        for ev in engine.sig.events:
            fh.write(json.dumps(ev.as_dict()) + "\n")

    print("\nLIVE CAPTURE COMPLETE")
    print(json.dumps({
        "events": sum(quality.get("channel_counts", {}).values()),
        "malformed": quality["malformed_events"],
        "duplicates": quality["duplicate_events"],
        "src_to_ing_p50_p95_per_channel":
            {k: (v or {}).get("p50") for k, v in channel_latency.items()},
        "ai_insights": len(engine.sig.events),
        "security": acceptance["security"]["status"],
    }, indent=2))
    print(f"artifacts: {out_dir}")
    print(f"recording: {recorder.frames_path}")

    if pool:
        try:
            await repo.save_quality_report(session.session_id, "LIVE",
                                           acceptance)
        except Exception as exc:  # noqa: BLE001
            log.warning("quality report DB save skipped: %s", exc)
        await pool.close()
    await client.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
