"""discover_sessions - list sessions visible through a provider.

Usage:
    python scripts/discover_sessions.py [--latest] [--meeting 1292] [--ref openf1:11353]
"""

from __future__ import annotations

import argparse

from _common import setup_logging  # noqa: F401

import asyncio  # noqa: E402
import sys  # noqa: E402

setup_logging()
from app.config import get_settings  # noqa: E402
from app.providers.openf1.client import OpenF1Client, OpenF1Error  # noqa: E402
from app.providers.openf1.provider import OpenF1Provider  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser(description="Discover F1 sessions via OpenF1")
    ap.add_argument("--latest", action="store_true", help="resolve session_key=latest")
    ap.add_argument("--meeting", type=str, default=None, help="list sessions of one meeting")
    ap.add_argument("--ref", type=str, default=None, help="resolve a specific session reference")
    args = ap.parse_args()

    settings = get_settings()
    client = OpenF1Client(settings)
    provider = OpenF1Provider(client, settings)
    print("CONNECTING to api.openf1.org ...")
    try:
        if args.latest or args.ref:
            sess = await provider.resolve_session(args.ref or "latest")
            print("SESSION FOUND:")
            _print_session(sess)
        elif args.meeting:
            rows = await client.sessions_for_meeting(args.meeting)
            print(f"SESSIONS for meeting {args.meeting}: {len(rows)}")
            from app.providers.openf1.mapping import safe, to_session

            for row in rows:
                _print_session(safe(to_session, row))
        else:
            sessions = await provider.discover_sessions()
            print(f"SESSIONS FOUND: {len(sessions)}")
            for s in sessions[:25]:
                _print_session(s, brief=True)
    finally:
        await client.aclose()


def _print_session(s, brief: bool = False) -> None:  # noqa: ANN001
    line = (
        f"  {s.session_id:<18} {str(s.year):<6} {s.session_type.value:<20} "
        f"{s.country_code or '---'} {s.circuit_short_name or '---':<16} "
        f"{s.date_start.isoformat() if s.date_start else '-':<25} [{s.status.value}]"
    )
    if brief:
        print(line)
    else:
        print(line.rstrip())
        print(f"    meeting={s.provider_meeting_key} name={s.session_name!r} "
              f"end={(s.date_end.isoformat() if s.date_end else '-')}")


if __name__ == "__main__":
    asyncio.run(main())
