"""live_latency_report - render measured source->ingestion latency percentiles
per provider and per channel from quality_reports data (or a live monitor).

Run this DURING/AFTER a live-window recording:
    python scripts/record_session.py --ref latest --max-seconds <session len>
    python scripts/live_latency_report.py openf1:<key>

This tool reports ONLY observed values. If no class-A samples exist it says so
explicitly - latency is never estimated or assumed.
"""

import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.storage.db import connect  # noqa: E402


def _stats(samples: list[float]) -> dict:
    if not samples:
        return {"n": 0}
    s = sorted(samples)

    def pct(p: float) -> float:
        return s[min(len(s) - 1, max(0, round((p / 100.0) * (len(s) - 1))))]

    return {
        "n": len(s),
        "min": round(s[0], 3),
        "mean": round(sum(s) / len(s), 3),
        "p50": round(pct(50), 3),
        "p95": round(pct(95), 3),
        "p99": round(pct(99), 3),
        "max": round(s[-1], 3),
    }


def _render(report: dict) -> None:
    print("=" * 68)
    print("LIVE LATENCY REPORT (measured only)")
    print("=" * 68)
    sess = report.get("session", {})
    print(f"Session : {sess.get('session_name', '?')} "
          f"({sess.get('provider_session_key', '?')})")
    print(f"Status  : {sess.get('status', '?')}")

    providers = report.get("providers", {})
    if not providers:
        print("\nNo provider metrics recorded.")
        return

    any_live = False
    for pname, pdata in sorted(providers.items()):
        lat = pdata.get("latency", {})
        print(f"\nPROVIDER: {pname}")
        if lat.get("n"):
            flag = "(class A/live)" if pname != "openf1" or sess.get("status") == "LIVE" else ""
            print(f"  overall latency: min={lat['min']} mean={lat['mean']} p50={lat['p50']} "
                  f"p95={lat['p95']} p99={lat['p99']} max={lat['max']} n={lat['n']} {flag}")
        else:
            print("  overall latency: NO SAMPLES (historical backfill or idle)")
        for ch, count in sorted((pdata.get("channel_counts") or {}).items()):
            print(f"    {ch:<12} events={count}")
        if pdata.get("malformed"):
            print(f"    malformed={pdata['malformed']} duplicates={pdata.get('duplicates', 0)}")

    total_live = report.get("latency_live_class_a", {}).get("n", 0)
    print("-" * 68)
    if total_live == 0:
        print("VERDICT: no class-A (live) latency samples exist in this report.")
        print("Do NOT quote this run as evidence of real-time behavior.")
    else:
        any_live = True
        la = report["latency_live_class_a"]
        print(f"VERDICT: measured LIVE latency p50={la['p50']}s p95={la['p95']}s "
              f"p99={round(sorted([0]) and la['p99'], 3)}s over n={la['n']}")
    print("=" * 68)


async def main() -> int:
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    file_arg = None
    if "--file" in sys.argv:
        file_arg = sys.argv[sys.argv.index("--file") + 1]

    if file_arg:
        data = json.loads(Path(file_arg).read_text(encoding="utf-8-sig"))
        _render(data)
        return 0
    if not sid:
        print("usage: live_latency_report.py <session_id> | --file <quality.json>")
        return 2

    pool = await connect(get_settings().database_url)
    try:
        row = await pool.fetchrow(
            "SELECT report FROM quality_reports WHERE session_id=$1 "
            "ORDER BY created_at DESC LIMIT 1",
            sid,
        )
        if not row:
            print(f"no quality report stored for {sid} - record the session first")
            return 1
        _render(json.loads(row["report"]))
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
