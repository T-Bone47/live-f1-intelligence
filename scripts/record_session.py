"""record_session - ingest a session through OpenF1, persist + record it.

This is the Phase-1 acceptance harness:

    REAL SESSION -> OPENF1 -> pipeline -> canonical events
                 -> PostgreSQL  +  recordings/<name>/frames.jsonl.zst

Usage:
    python scripts/record_session.py --latest
    python scripts/record_session.py --ref openf1:11353
    python scripts/record_session.py --ref 11353 [--max-seconds 300]

States printed: CONNECTING -> SESSION FOUND -> RECEIVING DATA -> RECORDING ->
STOPPED (+ data-quality report at the end).
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

from _common import setup_logging

setup_logging()
import logging  # noqa: E402

log = logging.getLogger("record_session")

from app.config import get_settings  # noqa: E402
from app.core.events import EventBus  # noqa: E402
from app.ingest.persistence import PersistenceSubscriber  # noqa: E402
from app.ingest.pipeline import IngestPipeline  # noqa: E402
from app.ingest.recorder import Recorder  # noqa: E402
from app.providers.openf1.client import OpenF1Client, OpenF1Error  # noqa: E402
from app.providers.openf1.provider import OpenF1Provider  # noqa: E402
from app.storage.db import Repository, apply_migrations, connect  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="Record an F1 session (OpenF1)")
    ap.add_argument("--ref", type=str, default=None,
                    help="session reference: 'latest', raw key or canonical id")
    ap.add_argument("--latest", action="store_true", help="shorthand for --ref latest")
    ap.add_argument("--max-seconds", type=int, default=0,
                    help="hard time limit for the recording run (0 = until exhausted/Ctrl+C)")
    args = ap.parse_args()

    ref = "latest" if (args.latest and not args.ref) else (args.ref or "latest")
    settings = get_settings()

    print("CONNECTING ...")
    client = OpenF1Client(settings)
    provider = OpenF1Provider(client, settings)
    pool = await connect(settings.database_url)
    applied = await apply_migrations(pool)
    if applied:
        print(f"migrations applied: {applied}")
    repo = Repository(pool)

    try:
        session = await provider.resolve_session(ref)
    except OpenF1Error as exc:
        print(f"FAILED: {exc}")
        await client.aclose()
        await pool.close()
        return 2

    state = provider.classify_session_state(session)
    print(
        f"SESSION FOUND: {session.session_id} "
        f"{session.year} {session.session_type.value} @ {session.circuit_short_name} "
        f"[{state}]"
    )
    if state == "scheduled":
        print("Session has not started - nothing to record.")
        await client.aclose()
        await pool.close()
        return 0
    if state == "live" and not settings.openf1_api_token:
        print(
            "WARNING: session is in its live window; without OPENF1_API_TOKEN the\n"
            "free API may restrict access during live sessions (verified behavior).\n"
            "Continuing - if restricted, run later as historical backfill."
        )

    bus = EventBus()
    persistence = PersistenceSubscriber(repo)

    async def _record(env) -> None:  # noqa: ANN001 Envelope
        recorder.write(env)

    import os

    analysis_engine = None
    if os.environ.get("F1_ANALYZE", "").lower() in ("1", "true", "yes") or \
            os.environ.get("ANALYZE", "").lower() in ("1", "true", "yes"):
        from app.analysis import AnalysisEngine

        analysis_engine = AnalysisEngine(session_id=session.session_id)

        async def _analyze(env) -> None:  # noqa: ANN001 Envelope
            for out in analysis_engine.process_envelope(env):
                pass

        bus.subscribe("analysis", _analyze)
        print("analysis engine: ENABLED")

    # canonical session-state projection (Phase 1.5)
    from app.core.session_state import SessionStateProjection

    projection = SessionStateProjection()
    if session.date_start and session.date_end:
        from datetime import datetime, timezone as _tz

        projection.fold_session_window(session.date_start, session.date_end,
                                       datetime.now(tz=_tz.utc))

    async def _project(env) -> None:  # noqa: ANN001 Envelope
        info = env.payload.get("model", {})
        mtype = info.get("type")
        if mtype == "RaceControlEvent":
            before = projection.phase
            lap = info.get("lap_number")
            if lap is not None:
                projection.fold_lap_count(int(lap))
            projection.fold_rcm(info.get("message") or "", info.get("category"),
                                info.get("flag"), env.source_timestamp)
            if projection.phase is not before:
                print(f"\nSESSION STATE: {before.value} -> {projection.phase.value} "
                      f"({(info.get('message') or '')[:60]})")
                await repo.execute_log_state(session.session_id, projection)

    bus.subscribe("recorder", _record)
    bus.subscribe("db", persistence.__call__)
    bus.subscribe("state", _project)

    pipeline = IngestPipeline(session_id=session.session_id, bus=bus)
    quality = pipeline.quality
    quality.session = {
        "session_id": session.session_id,
        "provider_session_key": session.provider_session_key,
        "session_name": session.session_name,
        "country_code": session.country_code,
        "status": session.status.value,
        "date_start": session.date_start.isoformat() if session.date_start else None,
    }

    rec_name = f"openf1-{session.provider_session_key}-{session.session_type.value.lower()}"
    recorder = Recorder(settings.recordings_dir, rec_name)
    mode = "live" if state == "live" else "historical"

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: SIGINT handled by KeyboardInterrupt
            pass

    timeout_task = None
    if args.max_seconds > 0:
        async def _timeout() -> None:
            await asyncio.sleep(args.max_seconds)
            stop.set()
        timeout_task = asyncio.create_task(_timeout())

    print("RECEIVING DATA ...")

    async def consume() -> int:
        count = 0
        first = True
        async for item in provider.run(session):
            if first:
                print("RECORDING ...")
                first = False
            if item.channel is not None and hasattr(item.payload, "get"):
                pass
            count += await pipeline.process(item)
            if count % 500 < 8:
                print(f"  events: {count} (seq={pipeline._seq}, "
                      f"dup={quality.duplicate_events}, bad={quality.malformed_events})",
                      end="\r", flush=True)
            if stop.is_set():
                break
        return count

    try:
        total = await consume()
    except KeyboardInterrupt:
        print("\nSTOPPED (keyboard interrupt)")
        total = pipeline._seq
    except OpenF1Error as exc:
        log.error("provider failure: %s", exc)
        print(f"\nPROVIDER FAILURE: {exc}")
        total = pipeline._seq
    finally:
        if timeout_task:
            timeout_task.cancel()
        if persistence is not None:
            await persistence.flush()

    await bus.stop()

    report = quality.report()
    recorder.write_meta(
        session_payload={
            **quality.session,
            "date_end": session.date_end.isoformat() if session.date_end else None,
            "meeting_name": session.provider_meeting_key,
            "year": session.year,
            "session_type": session.session_type.value,
        },
        provider_name="openf1",
        capabilities_notes=list(provider.capabilities().notes),
    )
    recorder.finalize()

    print("\nSTOPPED")
    print(f"events published : {total}")
    print(f"recording        : {recorder.frames_path} ({recorder.seq} frames)")

    if analysis_engine is not None:
        analysis_engine.flush_deferred()
        snap = analysis_engine.snapshot_dict()
        import json as _json

        snapshot_path = Path(str(recorder.dir) + "/snapshot.json")
        snapshot_path.write_text(_json.dumps(snap, indent=2), encoding="utf-8")
        print(f"analysis phase   : {snap['phase']} | fastest lap: "
              f"{snap['fastest_lap']}")
        print(f"snapshot         : {snapshot_path}")
        intel_path = Path(str(recorder.dir) + "/intelligence_events.jsonl")
        with open(intel_path, "w", encoding="utf-8") as fh:
            for ev in analysis_engine.sig.events:
                fh.write(_json.dumps(ev.as_dict()) + "\n")
        print(f"intelligence     : {len(analysis_engine.sig.events)} events -> "
              f"{intel_path}")

    db_report = {"written_rows": persistence.written, "conflicts": persistence.conflicts}
    try:
        await repo.save_quality_report(session.session_id, mode, {**report, "persistence": db_report})
    except Exception as exc:  # noqa: BLE001
        print(f"(quality report DB save skipped: {exc})")
    report_path = Path(str(recorder.dir) + "/quality.json")
    import json

    report_path.write_text(json.dumps({**report, "persistence": db_report}, indent=2),
                           encoding="utf-8")
    print(quality.render_text())
    print(f"DB rows written  : {persistence.written} (dedupe conflicts: {persistence.conflicts})")
    print(f"quality report   : {report_path}")

    await client.aclose()
    await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
