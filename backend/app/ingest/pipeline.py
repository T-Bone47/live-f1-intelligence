"""Ingestion pipeline: provider -> validation -> normalization -> bus.

Responsibilities:
- dedupe (in-memory LRU keyed by envelope.dedupe_key; DB unique constraints
  are the durable second layer)
- malformed-record isolation with counters (never crash, never fabricate)
- seq assignment is delegated to the Recorder when recording, otherwise a
  local counter
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Iterable

from app.core.events import Envelope, EventBus
from app.ingest.normalize import normalize
from app.ingest.quality import DataQualityMonitor
from app.providers.base import RawItem

log = logging.getLogger(__name__)


class IngestPipeline:
    def __init__(self, session_id: str, bus: EventBus | None = None) -> None:
        self.session_id = session_id
        self.bus = bus or EventBus()
        self.quality = DataQualityMonitor()
        self._seq = 0
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._seen_cap = 200_000

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _is_duplicate(self, key: str | None) -> bool:
        if key is None:
            return False
        if key in self._seen:
            return True
        self._seen[key] = None
        if len(self._seen) > self._seen_cap:
            self._seen.popitem(last=False)
        return False

    async def process(self, item: RawItem) -> int:
        """Validate + normalize one raw item; publish canonical envelopes.

        Returns number of events published.
        """
        source = "replay" if "__envelope" in item.payload else getattr(
            item.channel, "value", str(item.channel)
        )
        try:
            envelopes = normalize(item, self.session_id, datetime.now(tz=timezone.utc))
        except Exception as exc:  # noqa: BLE001 - malformed data must not kill ingestion
            self.quality.note_malformed(_provider_for_channel(item))
            log.warning(
                "malformed %s item dropped (%s): %.160s",
                getattr(item.channel, "value", item.channel),
                type(exc).__name__,
                str(exc),
            )
            return 0

        published: list[Envelope] = []
        for env in envelopes:
            if self._is_duplicate(env.dedupe_key):
                self.quality.note_duplicate(env.source)
                continue
            env.seq = self._next_seq()
            if env.origin == "replay":
                # replayed frames keep their original ingestion timestamps;
                # latency stats are meaningless for them
                pass
            self.quality.note_event(
                event_type=env.event_type,
                driver_number=env.driver_number,
                source_timestamp=env.source_timestamp,
                ingestion_timestamp=env.ingestion_timestamp,
                provenance_class=env.provenance_class,
                source=env.source,
            )
            published.append(env)

        if published:
            await self.bus.publish_many(published)
        return len(published)

    async def process_many(self, items: Iterable[RawItem]) -> int:
        total = 0
        for item in items:
            total += await self.process(item)
        return total


async def drain_bus(bus: EventBus, settle_seconds: float = 1.5) -> None:
    """Give subscribers a moment to flush queues before shutdown."""
    await asyncio.sleep(settle_seconds)


def _provider_for_channel(item: RawItem) -> str:
    """Best-effort provider attribution for malformed-item metrics."""
    if "__envelope" in item.payload:
        env = item.payload["__envelope"]
        if isinstance(env, dict):
            return str(env.get("source", "replay"))
    from app.providers.base import Channel as _C

    mapping = {
        _C.RESULTS: "jolpica",
        _C.STANDINGS: "jolpica",
        _C.SCHEDULE: "jolpica",
    }
    return mapping.get(item.channel, "openf1")
