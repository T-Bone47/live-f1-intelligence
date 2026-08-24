"""AI job queue + runtime (Phase 6).

    engine.sig listener (critical/high events) ─┐
    user questions (REST) ──────────────────────┤
                                                ▼
                                    bounded asyncio AI queue (20)
                                                ▼
                              worker: build pack -> gateway -> validate
                                                ▼
                          JobRecord store + broadcast callback (WS kind=ai)

Cooldowns: automatic commentary per (kind, drivers) 90 s; user jobs are never
cooldown-blocked. Queue-full raises AIJobQueueFull -> REST maps to 429.
Stale protection: snapshot_seq captured at enqueue; compared at completion
(gap > STALE_SEQ_GAP marks the response STALE).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque

from app.ai.change import build_change_pack
from app.ai.gateway import LLMGateway
from app.ai.models import (
    AIJobQueueFull,
    AIResponse,
    JobRecord,
    JobStatus,
)

log = logging.getLogger(__name__)

QUEUE_SIZE = 20
AUTO_COOLDOWN_S = 90.0
STALE_SEQ_GAP = 15


class AIRuntime:
    def __init__(self, gateway: LLMGateway, *, auto_enabled: bool = True,
                 get_mode=None) -> None:
        self.gateway = gateway
        self.auto_enabled = auto_enabled
        self._get_mode = get_mode or (lambda: "LIVE")
        self.queue: asyncio.Queue[JobRecord] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.jobs: dict[str, JobRecord] = {}
        self.recent_order: deque[str] = deque(maxlen=200)
        self._cooldowns: dict[str, float] = {}
        self._engine = None
        self._broadcast = None            # callable(dict) -> WS kind=ai frame
        self._get_current_seq = lambda: 0  # set via attach()
        self._prev_snapshot: dict | None = None
        self._worker_task: asyncio.Task | None = None
        self._stopping = False

    def attach(self, engine, *, broadcast=None,
               get_current_seq=None) -> None:  # noqa: ANN001
        self._engine = engine
        self._broadcast = broadcast
        if get_current_seq:
            self._get_current_seq = get_current_seq

    # ------------------------------------------------------------ intake ---

    def trigger_from_event(self, event) -> str | None:  # noqa: ANN001
        if not self.auto_enabled:
            return None
        severity_ok = event.severity.value in ("IMPORTANT", "CRITICAL")
        critical_type = event.event_type in (
            "RED_FLAG", "SAFETY_CAR", "VSC", "SESSION_STATE_CHANGE", "OVERTAKE",
            "FASTEST_LAP_CHANGE", "QUALIFYING_CUTOFF_CHANGE")
        if not (severity_ok or critical_type):
            return None
        key = f"auto:{event.event_type}:{','.join(map(str, event.driver_numbers))}"
        now = time.monotonic()
        if now - self._cooldowns.get(key, -1e9) < AUTO_COOLDOWN_S:
            return None
        self._cooldowns[key] = now
        return self.enqueue(kind=key[:80], question=(
            f"Explain this {event.event_type} for driver(s) "
            f"{list(event.driver_numbers)} using the context pack."))

    def ask(self, session_id: str, question: str, snapshot_seq: int) -> str:
        if len(self.jobs) > 500:
            self._prune_old()
        return self.enqueue(kind="user", question=question[:500],
                            session_id=session_id, snapshot_seq=snapshot_seq)

    def enqueue(self, *, kind: str, question: str,
                session_id: str | None = None,
                snapshot_seq: int = 0) -> str:
        if self.queue.full():
            raise AIJobQueueFull("AI queue saturated")
        job_id = uuid.uuid4().hex[:12]
        rec = JobRecord(job_id=job_id,
                        session_id=session_id or (self._engine.session_id
                                                  if self._engine else "unknown"),
                        kind=kind, question=question,
                        snapshot_seq=snapshot_seq)
        self.jobs[job_id] = rec
        self.recent_order.append(job_id)
        try:
            self.queue.put_nowait(rec)
        except asyncio.QueueFull:
            del self.jobs[job_id]
            raise AIJobQueueFull("AI queue saturated") from None
        return job_id

    def _prune_old(self) -> None:
        while len(self.recent_order) > 300:
            old = self.recent_order.popleft()
            self.jobs.pop(old, None)

    def status(self) -> dict:
        m = self.gateway.metrics.as_dict()
        return {"queue_depth": self.queue.qsize(),
                "auto_commentary": self.auto_enabled,
                "tracked_jobs": len(self.jobs),
                **m}

    # ------------------------------------------------------------- worker --

    async def start_worker(self) -> None:
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._stopping = False

        async def loop() -> None:
            while not self._stopping:
                job = await self.queue.get()
                try:
                    await self._process(job)
                except Exception:  # noqa: BLE001 - worker must survive
                    log.exception("AI job %s crashed", job.job_id)
                    job.status = JobStatus.FAILED
                    job.error = "worker crash"

        self._worker_task = asyncio.create_task(loop(), name="ai-worker")

    async def stop(self) -> None:
        self._stopping = True
        if self._worker_task:
            self._worker_task.cancel()

    # ----------------------------------------------------------- process ---

    async def _process(self, job: JobRecord) -> None:
        t0 = time.perf_counter()
        job.status = JobStatus.RUNNING
        engine = self._engine
        if engine is None:
            job.status = JobStatus.FAILED
            job.error = "no analysis engine attached"
            return
        engine.flush_deferred()

        snap = engine.snapshot_dict()
        pack = build_pack_from_engine(engine, snap)
        change = None
        if self._prev_snapshot is not None:
            change = build_change_pack(self._prev_snapshot, snap)
        self._prev_snapshot = snap

        current_seq = self._get_current_seq()
        try:
            resp = await self.gateway.run_job(
                session_id=job.session_id, question=job.question,
                pack=pack, mode=self._get_mode(),
                snapshot_seq=job.snapshot_seq, current_seq=current_seq,
                job_id=job.job_id)
            job.status = JobStatus.DONE
        except Exception as exc:  # noqa: BLE001 - provider/validation failure
            log.warning("AI job %s failed (%s) - deterministic fallback",
                        job.job_id, exc)
            resp = self.gateway.deterministic_fallback(
                job_id=job.job_id, session_id=job.session_id,
                question=job.question, pack=pack, mode=self._get_mode(),
                snapshot_seq=job.snapshot_seq, reason=str(exc)[:60])
            job.status = JobStatus.FALLBACK

        if change is not None and job.response:
            job.usage["meaningful_changes"] = change.get("count", 0)
            job.usage["change_lines"] = change.get("summary_lines", [])[:5]

        if current_seq - job.snapshot_seq > STALE_SEQ_GAP:
            job.status = JobStatus.STALE
            resp.stale = True

        job.response = resp
        job.timings_ms["total"] = round((time.perf_counter() - t0) * 1000, 1)
        if self._broadcast:
            payload = resp.as_dict()
            payload["kind"] = "ai"
            if change is not None:
                payload["changes"] = change.get("summary_lines", [])[:5]
            self._broadcast(payload)


def build_pack_from_engine(engine, snap: dict) -> dict:  # noqa: ANN001
    """Deterministic race_v1 pack assembly from live engine state."""
    facts = []
    for r in (snap.get("leaderboard") or [])[:10]:
        facts.append({
            "id": f"lb{r['driver_number']}", "class": "C",
            "statement": (f"P{r.get('position')} #{r['driver_number']} "
                          f"lap {r.get('lap_number')} best "
                          f"{r.get('personal_best_s')} rolling5 "
                          f"{r.get('rolling5_s')} tyre "
                          f"{r.get('compound')}/{r.get('tyre_age')}"),
            "values": {"position": r.get("position"),
                       "driver": r["driver_number"],
                       "best": r.get("personal_best_s")},
        })
    fl = snap.get("fastest_lap")
    if fl:
        facts.append({"id": "fastest_lap", "class": "A",
                      "statement": f"Fastest lap #{fl['driver']} "
                                   f"{fl['duration_s']}s on lap {fl.get('at_lap')}",
                      "values": {"duration": fl["duration_s"]}})
    intel = engine.intelligence()
    for n, stints in (intel.get("tyres_2") or {}).items():
        for s in stints[-1:]:
            facts.append({"id": f"deg{n}", "class": "D",
                          "statement": f"#{n} stint {s['stint_number']} "
                                       f"estimated degradation "
                                       f"{s['estimated_degradation']} s/lap",
                          "values": {"rate": s["estimated_degradation"]},
                          "confidence": s["confidence"]})
    for b in (snap.get("active_battles") or [])[:4]:
        facts.append({"id": f"battle{b['behind']}v{b['ahead']}", "class": "C",
                      "statement": (f"Battle #{b['behind']} vs #{b['ahead']} "
                                    f"{b['state']} last gap {b.get('last_gap_s')}"),
                      "values": {"gap": b.get("last_gap_s")}})
    for c in ((intel.get("strategy_candidates") or {}).get("candidates")) or []:
        facts.append({"id": f"strat{c['strategy_rank']}", "class": "D",
                      "statement": (f"{c['name']} rank {c['strategy_rank']} "
                                    f"estimated total {c['estimated_total_s']}s "
                                    f"stops {c['stops']}"),
                      "values": {"total": c["estimated_total_s"],
                                 "rank": c["strategy_rank"], "stops": c["stops"]},
                      "assumptions": c.get("assumptions")})
    wx = snap.get("weather") or {}
    if wx:
        facts.append({"id": "weather", "class": "A",
                      "statement": json.dumps(wx, default=str)[:160]})
    rc_state = f"{snap.get('phase')}/{snap.get('track_flag')}"
    facts.append({"id": "race_control", "class": "A",
                  "statement": f"Session phase {rc_state}"})
    return {"pack": "race_v1", "session_id": snap.get("session_id"),
            "facts": facts[:40], "recent_events":
                (snap.get("recent_events") or [])[-10:]}
