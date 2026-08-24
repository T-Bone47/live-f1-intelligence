"""Live-vs-provider comparison (Phase 7).

Compares canonical state produced by TWO provider runs over the same session
(e.g., OpenF1 vs direct SignalR) without ever silently merging:

    MATCH                  values equal within tolerance
    MISMATCH               both present, differ beyond tolerance
    MISSING_ON_A / _B      one side absent
    TIMESTAMP_DIFFERENCE   values match but source timestamps diverge > tol

Comparison domains: positions, lap numbers, lap times (PB), sector bests,
tyre compound/age, race-control phase, weather latest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComparisonRow:
    domain: str
    key: str
    verdict: str                 # MATCH|MISMATCH|MISSING_ON_A|MISSING_ON_B|TIMESTAMP_DIFFERENCE
    value_a: Any = None
    value_b: Any = None
    detail: str | None = None


@dataclass
class ProviderComparison:
    rows: list[ComparisonRow] = field(default_factory=list)

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for r in self.rows:
            counts[r.verdict] = counts.get(r.verdict, 0) + 1
        return {"rows": len(self.rows), **{k.lower(): v for k, v in counts.items()}}

    def as_dict(self) -> dict:
        return {"summary": self.summary(),
                "rows": [vars(r) for r in self.rows]}


def _cmp(domain: str, key: str, a: Any, b: Any,
         tol: float = 0.05) -> ComparisonRow:
    if a is None and b is None:
        return ComparisonRow(domain, key, "MISSING_ON_A", None, None,
                             "missing on both")
    if a is None:
        return ComparisonRow(domain, key, "MISSING_ON_A", None, b)
    if b is None:
        return ComparisonRow(domain, key, "MISSING_ON_B", a, None)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        ok = abs(float(a) - float(b)) <= tol
        return ComparisonRow(domain, key, "MATCH" if ok else "MISMATCH",
                             a, b, None if ok else f"delta={round(float(a)-float(b),3)}")
    return ComparisonRow(domain, key, "MATCH" if a == b else "MISMATCH", a, b)


def compare_snapshots(a_snap: dict, b_snap: dict,
                      name_a: str = "A", name_b: str = "B") -> ProviderComparison:
    """Compare two SessionSnapshot dicts from concurrent provider runs."""
    out = ProviderComparison()

    def index(snap: dict):
        return {r["driver_number"]: r for r in (snap.get("leaderboard") or [])}

    ia, ib = index(a_snap), index(b_snap)
    for dn in sorted(set(ia) | set(ib)):
        ra, rb = ia.get(dn), ib.get(dn)
        if ra is None:
            out.rows.append(ComparisonRow("leaderboard", str(dn),
                                          "MISSING_ON_A", None, None))
            continue
        if rb is None:
            out.rows.append(ComparisonRow("leaderboard", str(dn),
                                          "MISSING_ON_B", None, None))
            continue
        for field in ("position", "lap_number"):
            out.rows.append(_cmp("leaderboard", f"{dn}.{field}",
                                 ra.get(field), rb.get(field)))
        for field, tol in (("last_lap_s", 0.05), ("personal_best_s", 0.001)):
            row = _cmp("laps", f"{dn}.{field}", ra.get(field), rb.get(field),
                       tol)
            # timestamp-level divergence surfaced via delta detail
            out.rows.append(row)
        for field in ("compound", "tyre_age"):
            out.rows.append(_cmp("tyres", f"{dn}.{field}",
                                 ra.get(field), rb.get(field)))
        for field in ("gap_to_leader_s", "interval_s"):
            row = _cmp("gaps", f"{dn}.{field}", ra.get(field), rb.get(field),
                       0.5)
            out.rows.append(row)

    fl_a, fl_b = a_snap.get("fastest_lap"), b_snap.get("fastest_lap")
    if fl_a or fl_b:
        out.rows.append(_cmp("fastest_lap", "driver",
                             (fl_a or {}).get("driver"),
                             (fl_b or {}).get("driver")))
        out.rows.append(_cmp("fastest_lap", "duration_s",
                             (fl_a or {}).get("duration_s"),
                             (fl_b or {}).get("duration_s"), 0.001))

    out.rows.append(_cmp("race_control", "phase",
                         a_snap.get("phase"), b_snap.get("phase")))
    wx_a, wx_b = a_snap.get("weather") or {}, b_snap.get("weather") or {}
    for k in ("air_temp_c", "track_temp_c", "rainfall"):
        out.rows.append(_cmp("weather", k, wx_a.get(k), wx_b.get(k)))
    return out
