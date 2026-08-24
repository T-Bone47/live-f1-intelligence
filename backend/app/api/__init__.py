"""FastAPI application factory (Phase 3): REST + WebSocket delivery."""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.realtime.hub import SessionHub
from app.realtime.models import SCHEMA_VERSION

RATE_LIMIT_PER_MIN = 120


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HubRegistry:
    """One runtime per session; single upstream enforced by design (§11)."""

    def __init__(self) -> None:
        self.hubs: dict[str, SessionHub] = {}

    def get(self, session_id: str) -> SessionHub | None:
        return self.hubs.get(session_id)

    def register(self, hub: SessionHub) -> None:
        self.hubs[hub.session_id] = hub

    def remove(self, session_id: str) -> None:
        self.hubs.pop(session_id, None)


_registry: HubRegistry | None = None


def set_registry(registry: HubRegistry) -> None:
    global _registry
    _registry = registry


def get_registry() -> HubRegistry:
    if _registry is None:
        raise HTTPException(503, "no realtime registry configured")
    return _registry


def require_hub(session_id: str) -> SessionHub:
    hub = get_registry().get(session_id)
    if hub is None:
        raise HTTPException(404, f"no active realtime session '{session_id}'")
    return hub


# ------------------------------------------------------------- security -----

class RateLimiter:
    def __init__(self, per_minute: int = RATE_LIMIT_PER_MIN) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=per_minute))

    def check(self, key: str) -> bool:
        dq = self._hits[key]
        now = time.monotonic()
        while dq and now - dq[0] > 60:
            dq.popleft()
        if len(dq) >= self.per_minute:
            return False
        dq.append(now)
        return True


limiter = RateLimiter()


async def rate_limit_dependency(request: Request) -> None:
    client_ip = request.client.host if request.client else "anon"
    if not limiter.check(client_ip):
        raise HTTPException(429, "rate limit exceeded")


def validate_session_id(session_id: str) -> str:
    if not session_id or len(session_id) > 64 or \
            any(c in session_id for c in "/\\ \t"):
        raise HTTPException(422, "invalid session id")
    return session_id


# ----------------------------------------------------------------- REST -----

def create_app(registry: HubRegistry | None = None) -> FastAPI:
    if registry is not None:
        set_registry(registry)

    app = FastAPI(title="LIVE F1 INTELLIGENCE - realtime API", version="phase3")

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/live-data-status")
    async def live_data_status(_: None = Depends(rate_limit_dependency)):
        reg = get_registry()
        hubs = []
        for sid, hub in reg.hubs.items():
            d = hub.metrics.as_dict()
            # attach measured provider latency from the quality monitor
            q = hub.pipeline.quality.report()["latency_live_class_a"]
            d["provider"]["latency"] = q
            d["provider"]["reconnects"] = getattr(
                getattr(hub, "_provider", None), "reconnects", 0)
            hubs.append(d)
        return {"hubs": hubs}

    @app.get("/api/v1/sessions")
    async def list_sessions(_: None = Depends(rate_limit_dependency)):
        reg = get_registry()
        return {
            "active": [
                {"session_id": sid,
                 "clients": hub.metrics.clients_connected,
                 "phase": hub.engine.rc.phase().value}
                for sid, hub in sorted(reg.hubs.items())
            ]
        }

    @app.get("/api/v1/sessions/{session_id}/snapshot")
    async def get_snapshot(session_id: str,
                           _: None = Depends(rate_limit_dependency)):
        hub = require_hub(validate_session_id(session_id))
        snap = hub.engine.snapshot_dict()
        snap["seq"] = hub.history.current
        snap["schema"] = "f1intel-snapshot-1"
        return JSONResponse(snap)

    @app.get("/api/v1/sessions/{session_id}/drivers")
    async def get_drivers(session_id: str,
                          _: None = Depends(rate_limit_dependency)):
        hub = require_hub(validate_session_id(session_id))
        t = hub.engine.timing.state.drivers
        return {
            "session_id": session_id,
            "drivers": [
                {"driver_number": n, "position": d.position,
                 "lap_number": d.lap_number, "in_pit": d.in_pit,
                 "retired": d.retired}
                for n, d in sorted(t.items())
            ],
        }

    @app.get("/api/v1/sessions/{session_id}/leaderboard")
    async def get_leaderboard(session_id: str,
                              _: None = Depends(rate_limit_dependency)):
        hub = require_hub(validate_session_id(session_id))
        snap = hub.engine.snapshot_dict()
        rows = [
            {k: v for k, v in r.items()
             if k in ("position", "driver_number", "lap_number",
                      "last_lap_s", "personal_best_s", "gap_to_leader_raw",
                      "gap_to_leader_s", "interval_s", "compound", "tyre_age")}
            for r in snap["leaderboard"]
        ]
        return {"session_id": session_id, "leaderboard": rows}

    @app.get("/api/v1/sessions/{session_id}/events")
    async def get_events(session_id: str,
                         limit: int = Query(default=100, le=500),
                         _: None = Depends(rate_limit_dependency)):
        hub = require_hub(validate_session_id(session_id))
        evs = [e.as_dict() for e in hub.engine.sig.events[-limit:]]
        return {"session_id": session_id, "count": len(evs), "events": evs}

    @app.get("/api/v1/sessions/{session_id}/sectors/{driver_number}")
    async def get_sectors(session_id: str, driver_number: int,
                          _: None = Depends(rate_limit_dependency)):
        hub = require_hub(validate_session_id(session_id))
        se = hub.engine.sectors
        if driver_number not in se.drivers:
            raise HTTPException(404, "driver not present in session analysis")
        pb = se.personal_bests(driver_number)
        theo = se.theoretical_lap(driver_number)
        return {
            "session_id": session_id, "driver_number": driver_number,
            "personal_best": {f"S{k}": v for k, v in sorted(pb.items())},
            "last": {f"S{k}": v for k, v in sorted(se.drivers[driver_number].last.items())},
            "theoretical_lap_s": theo,
            "available": bool(pb),
        }

    @app.get("/api/v1/sessions/{session_id}/tyres/{driver_number}")
    async def get_tyres(session_id: str, driver_number: int,
                        _: None = Depends(rate_limit_dependency)):
        hub = require_hub(validate_session_id(session_id))
        st = hub.engine.stints.current(driver_number)
        if st is None:
            return {"session_id": session_id, "driver_number": driver_number,
                    "available": False,
                    "note": "stint context not yet delivered by provider"}
        fit = hub.engine.stints.fit_driver_current(driver_number)
        return {
            "session_id": session_id, "driver_number": driver_number,
            "available": True,
            "stint_number": st.stint_number,
            "compound": st.compound.value if st.compound else None,
            "lap_start": st.lap_start, "lap_end": st.lap_end,
            "laps_sampled": len(st.laps),
            "degradation": {
                "label": "ESTIMATED DEGRADATION - not official data",
                "rate_s_per_lap": fit.degradation_rate_s_per_lap,
                "base_pace_s": fit.base_pace_s,
                "r_squared": fit.r_squared,
                "samples": fit.n_samples,
                "excluded_outliers": fit.n_excluded,
                "confidence": fit.confidence.value,
            } if fit else None,
        }

    @app.get("/api/v1/sessions/{session_id}/pace/{driver_number}")
    async def get_pace(session_id: str, driver_number: int,
                       _: None = Depends(rate_limit_dependency)):
        hub = require_hub(validate_session_id(session_id))
        p = hub.engine.pace
        return {
            "session_id": session_id, "driver_number": driver_number,
            "rolling_3_s": p.rolling_pace(driver_number, 3),
            "rolling_5_s": p.rolling_pace(driver_number, 5),
            "rolling_10_s": p.rolling_pace(driver_number, 10),
            "median_s": p.median_pace(driver_number),
            "trend_s_per_lap": p.pace_trend(driver_number),
        }

    @app.get("/api/v1/sessions/{session_id}/telemetry/{driver_number}")
    async def get_telemetry(session_id: str, driver_number: int,
                            start: str | None = None, end: str | None = None,
                            lap: int | None = None,
                            frequency: str = "MEDIUM",
                            fields: str | None = None):
        """Canonical telemetry query with RAW/HIGH/MEDIUM/LOW LTTB
        downsampling. RAW windows are capped at 20 minutes."""
        from datetime import datetime, timedelta

        from app.storage.downsample import FREQ_TARGETS, lttb, normalize_frequency
        from app.storage.db import connect as db_connect

        freq = normalize_frequency(frequency)
        validate_session_id(session_id)
        pool = await db_connect(get_settings().database_url)
        try:
            if lap:
                win = await pool.fetchrow(
                    "SELECT started_at, duration_s FROM laps WHERE session_id=$1"
                    " AND driver_number=$2 AND lap_number=$3",
                    session_id, driver_number, lap)
                if not win or not win["started_at"]:
                    raise HTTPException(404, f"lap {lap} unknown for driver")
                start_dt = win["started_at"]
                end_dt = (start_dt + timedelta(seconds=win["duration_s"])
                          if win["duration_s"] else start_dt + timedelta(minutes=3))
            else:
                end_row = await pool.fetchrow(
                    "SELECT max(ts) AS m FROM telemetry_car WHERE session_id=$1"
                    " AND driver_number=$2", session_id, driver_number)
                if not end_row or not end_row["m"]:
                    raise HTTPException(404,
                                        "no stored telemetry for this driver/session")
                start_dt = end_row["m"] - timedelta(minutes=(20 if freq == "RAW" else 30))
                end_dt = end_row["m"]
            if start and end:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                if freq == "RAW" and (end_dt - start_dt).total_seconds() > 1200:
                    raise HTTPException(422, "RAW windows are capped at 20 minutes")

            rows = await pool.fetch(
                """SELECT ts, rpm, speed_kph, gear, throttle_pct, brake_pct, drs
                   FROM telemetry_car WHERE session_id=$1 AND driver_number=$2
                   AND ts BETWEEN $3 AND $4 ORDER BY ts""",
                session_id, driver_number, start_dt, end_dt)
            loc_rows = await pool.fetch(
                """SELECT ts, x, y, z FROM telemetry_location
                   WHERE session_id=$1 AND driver_number=$2
                   AND ts BETWEEN $3 AND $4 ORDER BY ts""",
                session_id, driver_number, start_dt, end_dt)
        finally:
            await pool.close()

        key_map = {"speed": "speed_kph", "gear": "gear", "drs": "drs",
                   "throttle": "throttle_pct", "brake": "brake_pct", "rpm": "rpm"}

        def numeric_series(k: str) -> list[dict]:
            src = loc_rows if k in ("x", "y", "z") else rows
            col = key_map.get(k, k)
            xs: list[float] = []
            ys: list[float] = []
            for r in src:
                v = r.get(col)
                if v is None:
                    continue
                xs.append(r["ts"].timestamp())
                ys.append(float(v))
            target = FREQ_TARGETS.get(freq) or len(xs)
            dxs, dys = lttb(xs, ys, target)
            return [{"ts": datetime.fromtimestamp(x, tz=_UTC).isoformat(), "value": y}
                    for x, y in zip(dxs, dys)]

        def gps_series() -> list[dict]:
            target = FREQ_TARGETS.get(freq) or len(loc_rows)
            step = max(1, len(loc_rows) // (target or 1))
            return [
                {"ts": r["ts"].isoformat(), "x": r["x"], "y": r["y"], "z": r["z"]}
                for r in loc_rows[::step]
            ]

        keys = ([f.strip() for f in fields.split(",")] if fields else
                ["speed", "throttle", "brake", "gear", "rpm", "drs", "gps"])
        series_out: dict[str, Any] = {}
        for k in keys:
            series_out[k] = gps_series() if k == "gps" else numeric_series(k)

        live = hub_active(session_id)
        return JSONResponse({
            "session_id": session_id, "driver_number": driver_number,
            "frequency": freq, "lap": lap,
            "window": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
            "provenance": {"class": "A" if live else "B",
                           "kind": "stored canonical telemetry"},
            "series": series_out,
        })

    @app.get("/api/v1/sessions/{session_id}/telemetry/compare")
    async def compare_telemetry(session_id: str, drivers: str,
                                lap: int | None = None,
                                frequency: str = "MEDIUM"):
        """Driver-vs-driver comparison. Aligned by normalized lap progress when
        ?lap= is provided; otherwise timestamp alignment only - and we say so."""
        validate_session_id(session_id)
        nums = [int(d) for d in drivers.split(",")[:3]]
        if len(nums) < 2:
            raise HTTPException(422, "provide >=2 drivers")
        series: dict[str, Any] = {}
        for dn in nums:
            resp = await get_telemetry(session_id, dn, lap=lap,
                                       frequency=frequency,
                                       fields="speed,throttle,brake,gps")
            series[str(dn)] = resp.json()["series"]
        return {
            "session_id": session_id, "drivers": nums, "lap": lap,
            "alignment": {
                "mode": "normalized_lap_progress" if lap else "timestamp",
                "valid": bool(lap),
                "note": None if lap else
                        "timestamp alignment only; pass ?lap= for per-lap comparison",
            },
            "series": series,
        }

    @app.get("/api/v1/sessions/{session_id}/intelligence")
    async def get_intelligence(session_id: str,
                               _: None = Depends(rate_limit_dependency)):
        hub = require_hub(validate_session_id(session_id))
        hub.engine.flush_deferred()
        return JSONResponse(hub.engine.intelligence())

    @app.get("/api/v1/sessions/{session_id}/strategy/candidates")
    async def get_strategy_candidates(session_id: str,
                                      _: None = Depends(rate_limit_dependency)):
        hub = require_hub(validate_session_id(session_id))
        hub.engine.flush_deferred()
        intel = hub.engine.intelligence()
        sc = (intel.get("strategy_candidates") or {})
        return {"session_id": session_id, **sc}

    @app.get("/api/v1/sessions/{session_id}/contextpack")
    async def get_context_pack(session_id: str,
                               _: None = Depends(rate_limit_dependency)):
        """AI-ready context pack (consumed by a future LLM - no LLM here)."""
        from app.analysis.contextpacks import build_race_pack

        hub = require_hub(validate_session_id(session_id))
        hub.engine.flush_deferred()
        snap = hub.engine.snapshot_dict()
        deg = {}
        for n in sorted(hub.engine.stints.stints):
            fit = hub.engine.stints.fit_driver_current(n)
            if fit and fit.degradation_rate_s_per_lap is not None:
                deg[str(n)] = {
                    "estimated_degradation_s_per_lap": fit.degradation_rate_s_per_lap,
                    "confidence": fit.confidence.value}
        battles = [{**{k: getattr(b, k) for k in
                       ("ahead", "behind", "state", "min_gap_s", "last_gap_s")},
                    "state": b.state.value}
                   for b in hub.battles.active_battles()]
        pack = build_race_pack(snapshot=snap, degradation=deg,
                               strategy=(hub.engine.intelligence().
                                         get("strategy_candidates")),
                               traffic={"states": hub.engine.intelligence()["traffic"]},
                               battles=battles, pace2=None)
        return JSONResponse(pack)

    @app.post("/api/v1/sessions/{session_id}/ai/ask")
    async def ai_ask(session_id: str, body: dict,  # noqa: ANN001
                     _: None = Depends(rate_limit_dependency)):
        from app.ai.jobs import AIJobQueueFull

        hub = require_hub(validate_session_id(session_id))
        runtime = getattr(hub, "ai_runtime", None)
        if runtime is None:
            raise HTTPException(503, "AI runtime not enabled on this hub")
        question = str(body.get("question", "")).strip()
        if not question:
            raise HTTPException(422, "question required")
        job_id = runtime.ask(session_id=hub.session_id,
                             question=question,
                             snapshot_seq=hub.history.current)
        return JSONResponse({"job_id": job_id}, status_code=202)

    @app.get("/api/v1/ai/jobs/{job_id}")
    async def ai_job(job_id: str):
        reg = get_registry()
        for hub in reg.hubs.values():
            runtime = getattr(hub, "ai_runtime", None)
            if runtime and job_id in runtime.jobs:
                job = runtime.jobs[job_id]
                return {"job_id": job_id, "status": job.status.value,
                        "timings_ms": job.timings_ms, "usage": job.usage,
                        "response": (job.response.as_dict()
                                     if job.response else None),
                        "error": job.error}
        raise HTTPException(404, "job not found")

    @app.get("/api/v1/ai/status")
    async def ai_status(_: None = Depends(rate_limit_dependency)):
        reg = get_registry()
        out = []
        for sid, hub in reg.hubs.items():
            runtime = getattr(hub, "ai_runtime", None)
            if runtime:
                s = runtime.status()
                s["session_id"] = sid
                out.append(s)
        return {"runtimes": out}

    @app.get("/api/v1/sessions/{session_id}/circuit")
    async def circuit_geometry(session_id: str):
        """Circuit outline availability. We never invent geometry: without a
        verified source the UI receives available=false and renders its clean
        fallback state. Verified hook: OpenF1 meetings expose circuit_info_url
        (MultiViewer) - integration deferred until licensed/verified."""
        require_hub(validate_session_id(session_id))
        return {"session_id": session_id, "available": False,
                "fallback": "position_list",
                "note": "no verified circuit geometry source integrated yet"}

    @app.post("/api/v1/replay/{session_id}/control")
    async def replay_control(session_id: str, body: dict):  # noqa: ANN001
        """Replay transport controls on the runtime upstream (same pipeline)."""
        hub = require_hub(validate_session_id(session_id))
        provider = getattr(hub, "_provider", None)
        action = body.get("action")
        speed = body.get("speed")
        if hasattr(provider, "set_speed") and speed is not None:
            provider.set_speed(float(speed))
        if action == "pause":
            setattr(hub, "_paused", True)
        elif action in ("resume", "play"):
            setattr(hub, "_paused", False)
        return {"session_id": session_id, "action": action or f"speed={speed}",
                "ok": True}

    @app.websocket("/ws/session/{session_id}")
    async def ws_session(ws: WebSocket, session_id: str):
        await ws.accept()
        try:
            hub = require_hub(validate_session_id(session_id))
        except HTTPException as exc:
            await ws.send_json({"kind": "error", "detail": exc.detail})
            await ws.close(code=4404)
            return

        conn = await hub.subscribe(f"ws-{id(ws)}-{time.time()}")
        client_id = conn.client_id
        last_seq = 0
        try:
            while True:
                # interleave inbound control messages with outbound queue
                recv_task = asyncio.create_task(ws.receive_text())
                send_task = asyncio.create_task(hub.next_for(conn))
                done, pending = await asyncio.wait(
                    {recv_task, send_task}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                if send_task in done:
                    item = send_task.result()
                    if isinstance(item, str) and item == "__evicted__":
                        await ws.send_json({"kind": "evicted", "reason": "slow consumer"})
                        break
                    payload = dict(item.payload)
                    payload.setdefault("seq", item.seq)
                    await ws.send_json(payload)
                if recv_task in done:
                    raw = recv_task.result()
                    msg = json.loads(raw)
                    action = msg.get("action")
                    if action == "ping":
                        await ws.send_json({"kind": "pong", "server_time": utcnow_iso()})
                    elif action == "resume":
                        target = int(msg.get("last_seq", 0))
                        missed = hub.history.since(target)
                        oldest = hub.history.oldest_available
                        if not missed or (oldest is not None and target < oldest - 1):
                            fresh = hub.engine.snapshot_dict()
                            seq_frame = hub.history.next("snapshot", {"data": fresh})
                            await ws.send_json({"kind": "snapshot", "data": fresh,
                                                "seq": seq_frame.seq,
                                                "schema": SCHEMA_VERSION})
                            last_seq = seq_frame.seq
                        else:
                            for f in missed:
                                out = dict(f.payload)
                                out["seq"] = f.seq
                                await ws.send_json(out)
                            last_seq = missed[-1].seq
                    elif action == "subscribe":
                        drivers = msg.get("drivers")
                        if isinstance(drivers, list):
                            conn.drivers = {int(d) for d in drivers}
                        tele = msg.get("telemetry_drivers")
                        if isinstance(tele, list):
                            conn.telemetry_drivers = {int(d) for d in tele}
                        wants = msg.get("deltas")
                        if isinstance(wants, bool):
                            conn.wants_deltas = wants
                        await ws.send_json({"kind": "control",
                                            "subscribed": True})
        except WebSocketDisconnect:
            pass
        except ConnectionError:
            pass
        finally:
            hub.unsubscribe(client_id)
            try:
                await ws.close()
            except RuntimeError:
                pass

    return app


def _get_settings():
    from app.config import get_settings as _gs

    return _gs()


_UTC = timezone.utc


def hub_active(session_id: str) -> bool:
    reg = get_registry()
    return reg is not None and reg.get(session_id) is not None


get_settings = _get_settings
