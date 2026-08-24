"""Live source failover: try providers in priority order; degrade honestly.

Rules:
- A provider is promoted only on demonstrated delivery (first successful item)
  or clean exhaustion of the previous one.
- Failure = provider exception, or watchdog silence (no items within
  `stall_timeout_s`) while it claimed to be live.
- When every live option for a channel is exhausted we DO NOT fabricate: the
  coordinator reports the channel as unavailable and stops.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable

from app.providers.base import RawItem

log = logging.getLogger(__name__)

ProviderFactory = Callable[[], object]  # -> object with run(session) + name


@dataclass
class FailoverReport:
    attempts: list[dict] = field(default_factory=list)
    active_provider: str | None = None


class ProviderChainRunner:
    def __init__(self, factories: list[ProviderFactory],
                 stall_timeout_s: float = 90.0) -> None:
        if not factories:
            raise ValueError("need at least one provider factory")
        self._factories = factories
        self._stall = stall_timeout_s
        self.report = FailoverReport()

    async def run(self, session) -> AsyncIterator[RawItem]:  # noqa: ANN001 SessionInfo
        last_error: Exception | None = None
        for index, factory in enumerate(self._factories):
            provider = factory()
            name = getattr(provider, "name", f"provider{index}")
            started = time.monotonic()
            delivered = 0
            log.info("failover chain: trying %s (priority %d)", name, index)
            try:
                agen = provider.run(session)
                while True:
                    try:
                        item = await asyncio.wait_for(
                            agen.__anext__(), timeout=self._stall
                        )
                    except StopAsyncIteration:
                        break
                    delivered += 1
                    self.report.active_provider = name
                    yield item
                # clean exhaustion
                self.report.attempts.append({
                    "provider": name, "outcome": "exhausted",
                    "delivered": delivered,
                    "seconds": round(time.monotonic() - started, 1),
                })
                if delivered:
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - failover IS the point
                last_error = exc
                log.warning("provider %s failed: %s", name, exc)
                self.report.attempts.append({
                    "provider": name, "outcome": f"error:{type(exc).__name__}",
                    "delivered": delivered,
                    "detail": str(exc)[:200],
                    "seconds": round(time.monotonic() - started, 1),
                })
                continue
            # exhausted with zero deliveries: treat as failure, advance
            last_error = None
            log.warning("provider %s delivered nothing - advancing chain", name)
            self.report.attempts.append({
                "provider": name, "outcome": "empty", "delivered": 0,
                "seconds": round(time.monotonic() - started, 1),
            })
        if all(a.get("delivered", 0) == 0 for a in self.report.attempts):
            log.error("all providers in chain failed; channel unavailable")
            if last_error:
                raise RuntimeError(f"all providers failed; last: {last_error}")
