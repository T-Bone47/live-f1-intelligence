# PROVIDER_GUIDE.md

How to add a data provider to LIVE F1 INTELLIGENCE — and what OpenF1
actually provides (verified 2026-08-23).

---

## 1. Provider contract

Implement `app/providers/base.py::DataProvider` (Protocol):

```python
class MyProvider:
    name = "myprovider"

    def capabilities(self) -> Capabilities: ...          # honest descriptor
    async def discover_sessions(self, year=None) -> list[SessionInfo]: ...
    async def resolve_session(self, ref: str) -> SessionInfo: ...
    def run(self, session) -> AsyncIterator[RawItem]: ... # yields vendor items
```

Rules:
1. `run()` yields `RawItem(channel, payload_dict, source_ts, provenance_class)`.
   Payloads stay verbatim vendor JSON — normalization is NOT the provider's job.
2. Declare only capabilities you truly deliver; downstream degrades honestly.
3. Live providers run until cancelled; historical providers terminate when
   exhausted. Never fabricate a "session finished" signal you don't have.
4. Class A provenance = real-time observation; class B = backfill/historical.

## 2. OpenF1 provider notes (verified empirically)

| Fact | Detail |
|---|---|
| Base | `https://api.openf1.org/v1/<resource>` returns JSON arrays |
| Filters | any field as query param; operators embedded in key (`date>`, `lap_number<=`) |
| Empty results | `{"detail":"No results found."}` with HTTP **200 or 404** (both seen) |
| `year=` filter | BROKEN upstream (returns empty for existing seasons) — use meeting/session keys |
| `session_key=latest` | works |
| laps timestamps | filter with **`date_start>`** — plain `date>` silently returns [] |
| intervals gap fields | MIXED TYPE: float OR string like `"+1 LAP"` for lapped cars |
| car_data.drs | nullable |
| drivers.country_code | nullable |
| pit.stop_duration | nullable (lane_duration always present in observed data) |
| rcm.sector | MARSHAL-POST number (values up to 18+), NOT timing sector 1–3 |
| stints | NO timestamps → full refresh + dedupe (stint_number 1-based) |
| position | change-events only, not a stream of current table |
| rate limits | documented 3 rps/30 rpm free tier; empirically stricter — client defaults to 1.8 rps / 20 rpm and honors Retry-After |
| live window | session_start−30min … end+30min requires sponsor token; outside = free historical |

## 3. Adding a provider — checklist

1. Package under `backend/app/providers/<name>/` with `client.py` (transport),
   `mapping.py` (vendor→canonical), `provider.py`.
2. Map into closed canonical enums via `enum_or_unknown` — never extend enums
   implicitly from upstream strings.
3. Reuse `safe()` wrapper so pydantic failures become counted NormalizationErrors.
4. Register channels you emit in `app/ingest/normalize.py` (one elif branch +
   dedupe keys).
5. Add persistence mapping in `_MODEL_REGISTRY` (models are shared; usually no
   DB changes needed).
6. Tests: fixtures from REAL responses under `tests/fixtures/<name>/`; cover
   nullability quirks and malformed records.
7. Update `docs/DATA_SOURCES.md` with verified facts + limitations.

## 4. ReplayProvider

Reads recording directories (format: docs/DATA_PIPELINE.md §6).
- `resolve_session(path)` loads meta.json (tolerates minimal metadata).
- `run()` re-emits stored envelopes through the pipeline unchanged;
  pacing scales original inter-frame wall delays by `speed` (0 = max).
- Capabilities derive from what the recording actually contains.

## 5. Provider catalogue (Phase 1.5)

| Provider | Module | Status | Provenance |
|---|---|---|---|
| OpenF1 | `providers/openf1/` | production (Phase-1 accepted) | A (live) / B (historical) |
| Replay | `providers/replay.py` | production | preserved from recording |
| SignalR direct | `providers/signalr/` | implemented; disabled by default; feed verified at negotiate/snapshot level 2026-08-24 | A |
| Jolpica | `providers/jolpica/` | implemented (schedule/results/standings) | B only |
| FastF1 | `providers/fastf1/` | adapter implemented; heavy loads deferred | B only, never live |
| F1DB | `providers/f1db_provider.py` | planned stub (honest zero claims) | B (future) |

Capability honesty rule: every provider declares `verified` and `assumed`
note-tuples alongside its boolean capabilities. Consumers should treat
assumed-only channels as unavailable until first successful delivery.

## 6. Planned providers

- Additional archive backfills (ergast-era history via F1DB import) — Phase 3+.
