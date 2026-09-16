# PHASE J — DATA PROVIDER AUDIT

> Re-verified fresh against HEAD (`717fcab`), not carried over from the
> original state audit. Every claim below is grounded in a real command
> run this pass.

| Provider | Code size | Status | Live-tested | Replay-tested | Historical-tested | Notes |
|---|---|---|---|---|---|---|
| OpenF1 | 1027 lines | Implemented | No — network-restricted sandbox | N/A | Via `test_provider_contract.py`, `test_openf1_mapping.py` (55 passed, 1 skipped) | Largest, most complete provider module |
| SignalR | 445 lines | Implemented, **disabled by default** | No — network-restricted sandbox | N/A | Via `test_provider_contract.py` (protocol/negotiate logic) | `app/config.py: signalr_enabled: bool = False` — confirmed, must be explicitly enabled |
| FastF1 | 220 lines | Adapter implemented | N/A (historical-only source) | N/A | Via `test_provider_contract.py` (`FastF1Provider`, `lap_row_to_raw`) | Class-B provenance |
| Jolpica | 391 lines | Implemented | N/A (historical/reference source) | N/A | Via `test_provider_contract.py` (`JolpicaClient`, `JolpicaProvider`, mapping functions) | |
| F1DB | 45 lines | **Deliberately stubbed** | N/A | N/A | Via `test_provider_contract.py` (`F1DBProvider`, contract-only) | In-code comment confirms `f1db/f1db` v2026.12.0 verified active 2026-08-23; capabilities honestly report nothing built yet. Unchanged this phase — building it is explicitly greenfield (57-section spec), not foundation-hardening |
| Replay | 193 lines | Implemented | N/A | **Partially** — app construction and real HTTP serving verified live this phase (Phase G); actual replay playback not exercised (no recording exists in this sandbox, confirmed and now correctly reported after this phase's path-doubling fix) | N/A | One real bug found and fixed this phase (path doubling in `resolve_session`'s fallback branch) |

**What changed this phase:** only Replay — the path-doubling fix (see
Phase G). Every other provider's status is unchanged from the original
audit; re-verification here found no drift.

**Live-tested column, honestly:** nothing in this row set has been
live-tested this session, for either provider, because this sandbox's
network allowlist doesn't reach OpenF1, SignalR, Jolpica, or FastF1's
backing sources — only GitHub/PyPI/npm are reachable. This is unchanged
from every prior report in this conversation and needs an environment
with real network access to close.
