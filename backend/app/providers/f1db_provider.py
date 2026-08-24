"""F1DB provider - PLANNED, intentionally not implemented in Phase 1.5.

Investigated (verified 2026-08-24): github.com/f1db/f1db actively maintained;
latest release v2026.12.0 published 2026-08-23; ships bulk CSV/Parquet/JSON
datasets (seasons, races, drivers, teams, circuits, results back to 1950).

Strategy: F1DB will be a build-time/offline reference import (drivers,
constructors, circuits metadata), never a live or session-data source.
Integration is deferred until the analysis phase needs deep historical
metadata; importing multi-hundred-MB dumps now would be premature.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from app.core.models import SessionInfo
from app.providers.base import Capabilities, RawItem

log = logging.getLogger(__name__)


class F1DBProvider:
    name = "f1db"

    def capabilities(self) -> Capabilities:
        return Capabilities(
            # nothing claimed: integration deliberately deferred (honesty rule)
            notes=(
                "PLANNED reference/metadata importer - not implemented yet",
                "release v2026.12.0 verified active (published 2026-08-23)",
                "will serve drivers/teams/circuits reference data offline",
            ),
        )

    async def discover_sessions(self, year: int | None = None) -> list[SessionInfo]:
        return []

    async def resolve_session(self, session_ref: str) -> SessionInfo:
        raise NotImplementedError("F1DB carries no sessions")

    def run(self, session: SessionInfo) -> AsyncIterator[RawItem]:  # pragma: no cover
        raise NotImplementedError("planned Phase 3+")
        yield  # pragma: no cover - makes this an async generator
