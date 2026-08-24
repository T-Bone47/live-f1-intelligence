"""data_quality - render the most recent quality report for a session.

Usage:
    python scripts/data_quality.py openf1:11353 [--file path/to/quality.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from _common import setup_logging

setup_logging()
from app.config import get_settings  # noqa: E402
from app.ingest.quality import DataQualityMonitor  # noqa: E402
from app.storage.db import connect  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="Show data-quality report")
    ap.add_argument("session_id", nargs="?", default=None)
    ap.add_argument("--file", type=str, default=None, help="read a saved quality.json")
    args = ap.parse_args()

    if args.file:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
        monitor = DataQualityMonitor()
        monitor._print_from_report(data) if hasattr(monitor, "_print_from_report") else None
        _render(data)
        return 0

    if not args.session_id:
        print("need a session id or --file")
        return 2

    pool = await connect(get_settings().database_url)
    try:
        row = await pool.fetchrow(
            """SELECT report FROM quality_reports
               WHERE session_id = $1 ORDER BY created_at DESC LIMIT 1""",
            args.session_id,
        )
        if not row:
            print(f"No quality report stored for {args.session_id}")
            return 1
        _render(json.loads(row["report"]))
        return 0
    finally:
        await pool.close()


def _render(data: dict) -> None:
    from datetime import datetime

    from app.ingest.quality import DataQualityMonitor as _M

    # reuse the text renderer via a lightweight shim
    m = _M.__new__(_M)
    m.session = data.get("session", {})
    m.drivers_seen = set(data.get("driver_numbers", []))
    m.channel_counts = dict(data.get("channel_counts", {}))
    m.channel_last_ts = {}
    m.driver_channel_seen = {
        ch: set(nums) for ch, nums in data.get("availability_by_driver", {}).items()
    }
    m.malformed_events = data.get("malformed_events", 0)
    m.duplicate_events = data.get("duplicate_events", 0)
    m.reconnect_count = data.get("reconnects", 0)
    m.shed_events = data.get("shed_events", 0)
    try:
        m.started_at = datetime.fromisoformat(data.get("monitor_started_at"))
    except (TypeError, ValueError):
        m.started_at = datetime.now()
    m._latency = []  # type: ignore[attr-defined]
    m._latency_live_only = []  # type: ignore[attr-defined]
    text = m.render_text()
    pers = data.get("persistence")
    if pers:
        text += f"\nDB rows written: {pers.get('written_rows')} " \
                f"(conflicts: {pers.get('conflicts')})"
    print(text)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
