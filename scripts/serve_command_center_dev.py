"""serve_command_center_dev - local API for the Phase 11 command center.

Serves the REST API on 127.0.0.1:8000 (Vite proxies /api) over:
  - a database holding recorded sessions (default f1intel_dev, filled by
    scripts/record_session.py), and
  - a recordings directory holding their recordings (for the lap timeline).
No realtime hub is started and nothing is seeded or synthesized.

    cd backend
    .\\.venv\\Scripts\\python.exe ..\\scripts\\serve_command_center_dev.py
    # other data: --database-url postgresql://.../db --recordings ..\\recordings\\dutchgp

Then open http://localhost:5173/sessions (npm run dev in frontend/).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from _common import setup_logging

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = "postgresql://f1intel:f1intel_dev@localhost:5432/f1intel_dev"
DEFAULT_RECORDINGS = ROOT / "recordings" / "dutchgp"


def main() -> None:
    ap = argparse.ArgumentParser(description="Command center dev API")
    ap.add_argument("--database-url", default=DEFAULT_DB)
    ap.add_argument("--recordings", type=Path, default=DEFAULT_RECORDINGS)
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    # settings are read from the environment by app.config
    os.environ["DATABASE_URL"] = args.database_url
    os.environ["RECORDINGS_DIR"] = str(args.recordings.resolve())
    setup_logging()

    import uvicorn

    from app.api import HubRegistry, create_app

    print(f"API  http://127.0.0.1:{args.port}/api/v1/sessions")
    print(f"DB   {args.database_url.rsplit('@', 1)[-1]}")
    print(f"REC  {args.recordings.resolve()}")
    uvicorn.run(create_app(HubRegistry()), host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
