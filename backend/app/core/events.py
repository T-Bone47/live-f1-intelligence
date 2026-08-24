"""Canonical event envelope + in-process event bus.

Every normalized fact travels as an Envelope. The envelope is also the
recording format, so live and replay share one interface (Phase 1 contract).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable, Iterable, Literal

from pydantic import BaseModel, Field, SerializationInfo, field_serializer

from app.core.enums import ProvenanceClass
from app.core.models import CanonicalModel, Provenance

log = logging.getLogger(__name__)


def make_event_id() -> str:
    return str(uuid.uuid4())


class Envelope(BaseModel):
    event_id: str = Field(default_factory=make_event_id)
    seq: int | None = None  # assigned by the pipeline per session, monotonic
    event_type: str  # e.g. "lap.completed", "telemetry.car_sample"
    category: Literal["domain", "derived", "ai", "system"] = "domain"
    session_id: str
    driver_number: int | None = None
    source: str  # provider name or "replay"
    source_timestamp: datetime | None = None
    ingestion_timestamp: datetime
    provenance_class: ProvenanceClass
    origin: Literal["live", "replay"] = "live"
    dedupe_key: str | None = None
    payload: dict[str, Any]

    @field_serializer("payload", mode="plain")
    def _serialize_payload(self, payload: dict[str, Any], info: SerializationInfo) -> Any:
        # Canonical models nested in payloads are dumped via their own schema so
        # recording round-trips stay lossless.
        out: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, BaseModel):
                out[key] = value.model_dump(mode="json")
            else:
                out[key] = value
        return out


SubscriberFn = Callable[[Envelope], Awaitable[None]]


class EventBus:
    """Deterministic in-process fan-out bus.

    Phase 1 design choice: subscribers are awaited INLINE in publish order.
    This keeps ordering guarantees strict, makes persistence/recording
    deterministic, and avoids hidden task scheduling. All Phase-1 subscribers
    are fast (DB batch insert, file append, counters); when a slow consumer
    arrives (Phase 3+ analysis), this class grows bounded queues behind the
    same interface.
    """

    def __init__(self, max_queue: int = 10000) -> None:
        self._subscribers: dict[str, SubscriberFn] = {}
        self.errors: list[str] = []

    def subscribe(self, name: str, fn: SubscriberFn) -> None:
        if name in self._subscribers:
            raise ValueError(f"subscriber {name!r} already registered")
        self._subscribers[name] = fn

    async def publish_many(self, envelopes: Iterable[Envelope]) -> int:
        count = 0
        for env in envelopes:
            for name, fn in self._subscribers.items():
                try:
                    await fn(env)
                except Exception as exc:  # noqa: BLE001 - subscriber isolation
                    msg = f"subscriber {name} failed on {env.event_type}: {exc}"
                    log.exception(msg)
                    if len(self.errors) < 100:
                        self.errors.append(msg)
            count += 1
        return count

    async def publish(self, envelope: Envelope) -> None:
        await self.publish_many([envelope])

    async def stop(self) -> None:
        return None


def make_envelope(
    *,
    event_type: str,
    session_id: str,
    model: CanonicalModel,
    source: str,
    dedupe_key: str | None,
    provenance_class: ProvenanceClass | None = None,
    ingestion_timestamp: datetime | None = None,
    origin: Literal["live", "replay"] = "live",
    driver_number: int | None = None,
) -> Envelope:
    prov: Provenance = model.provenance  # type: ignore[attr-defined]
    if driver_number is None:
        driver_number = getattr(model, "driver_number", None)
    return Envelope(
        event_type=event_type,
        session_id=session_id,
        driver_number=driver_number,
        source=source,
        source_timestamp=prov.source_timestamp,
        ingestion_timestamp=ingestion_timestamp or prov.ingestion_timestamp,
        provenance_class=provenance_class or prov.provenance_class,
        dedupe_key=dedupe_key,
        origin=origin,
        payload={"model": {"type": type(model).__name__, **_strip_model(model)}},
    )


def _strip_model(model: BaseModel) -> dict[str, Any]:
    data = model.model_dump(mode="json")
    return {k: v for k, v in data.items()}
