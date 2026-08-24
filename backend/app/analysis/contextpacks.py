"""AI-ready context packs (Phase 5).

Structured, bounded summaries per session profile that a FUTURE LLM will
consume INSTEAD of raw telemetry. Built deterministically from engine state;
every fact carries confidence/evidence where applicable. No LLM calls here.
"""

from __future__ import annotations

from typing import Any


def _fact(fid: str, cls: str, statement: str,
          values: dict | None = None, confidence: str | None = None) -> dict:
    f: dict[str, Any] = {"id": fid, "class": cls, "statement": statement}
    if values:
        f["values"] = values
    if confidence:
        f["confidence"] = confidence
    return f


def build_race_pack(*, snapshot: dict, degradation: dict,
                    strategy: dict | None, traffic: dict | None,
                    battles: list[dict], pace2: dict | None) -> dict:
    facts: list[dict] = []
    lb = (snapshot.get("leaderboard") or [])[:10]
    for r in lb:
        facts.append(_fact(
            f"lb{r['driver_number']}", "C",
            f"P{r.get('position')} #{r['driver_number']}: "
            f"best {r.get('personal_best_s')} rolling5 {r.get('rolling5_s')} "
            f"tyre {r.get('compound')}/{r.get('tyre_age')}",
            {"driver": r["driver_number"], "position": r.get("position")},
        ))
    fl = snapshot.get("fastest_lap")
    if fl:
        facts.append(_fact("fastest_lap", "A",
                           f"Fastest lap #{fl['driver']} {fl['duration_s']}s "
                           f"on lap {fl.get('at_lap')}"))
    for dn, deg in list((degradation or {}).items())[:6]:
        facts.append(_fact(f"deg{dn}", "D",
                           f"#{dn} estimated degradation {deg['estimated_degradation_s_per_lap']} s/lap",
                           deg, deg.get("confidence")))
    for b in battles[:4]:
        facts.append(_fact(f"battle{b['behind']}v{b['ahead']}", "C",
                           f"Battle #{b['behind']} vs #{b['ahead']}: {b['state']}",
                           b))
    if strategy:
        facts.append(_fact("strategy", "D", json_compact(strategy),
                           confidence="MEDIUM"))
    if traffic:
        facts.append(_fact("traffic", "C", json_compact(traffic)))
    return {
        "pack": "race_v1",
        "session_id": snapshot.get("session_id"),
        "facts": facts[:40],
        "recent_events": snapshot.get("recent_events", [])[-10:],
    }


def build_qualifying_pack(*, snapshot: dict, quali_intel: dict) -> dict:
    return {
        "pack": "qualifying_v1",
        "session_id": snapshot.get("session_id"),
        "phase": quali_intel.get("phase"),
        "facts": [
            _fact("cutoff", "C", json_compact(quali_intel.get("cutoff", {})),
                  confidence=quali_intel.get("cutoff_confidence")),
            _fact("evolution", "C", json_compact(quali_intel.get("evolution", {}))),
        ] + [
            _fact(f"drv{d['driver_number']}", "C", json_compact(d))
            for d in quali_intel.get("drivers", [])[:20]
        ],
        "recent_events": snapshot.get("recent_events", [])[-8:],
    }


def build_practice_pack(*, snapshot: dict, practice_intel: dict) -> dict:
    return {
        "pack": "practice_v1",
        "session_id": snapshot.get("session_id"),
        "facts": [
            _fact(k, "C", json_compact(v)) for k, v in
            list(practice_intel.items())[:30]
        ],
        "recent_events": snapshot.get("recent_events", [])[-8:],
    }


def json_compact(obj) -> str:
    import json

    return json.dumps(obj, separators=(",", ":"), default=str)[:300]
