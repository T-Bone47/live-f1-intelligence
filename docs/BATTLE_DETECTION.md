# BATTLE_DETECTION.md

Deterministic battle FSM (Phase 2) - thresholds are module constants.

## 1. Inputs

Per ordered pair (ahead A, behind B), sampled from B interval-to-A events:
gap_s, authoritative position swaps, pit/retired status. Symbolic-gap pairs
(lapped cars) never enter numeric logic.

## 2. States and transitions

NO_BATTLE -> APPROACHING        gap <= 2.0 s
          -> DRS_RANGE          gap <= 1.0 s
          -> ACTIVE_BATTLE      gap <= 0.6 s (from DRS_RANGE needs 2 consecutive)
ACTIVE -> DEFENDING             gap back in (0.6, 1.0]
       -> SEPARATING            gap > 2.5 s rising
any    -> NO_BATTLE             gap > 3.0 s for 3 samples, or pit/retire
pair position swap while engaged -> OVERTAKE (once)

NOTE on DRS naming: with OpenF1 intervals we approximate the DRS window by the
1.0 s gap convention; true DRS-zone state arrives via SignalR TimingData later
and will replace this proxy (documented upgrade path).

## 3. Evidence & determinism

Each pair tracks min_gap_s and last_gap_s as evidence. Identical sample
sequences always produce identical state sequences (unit-tested); no RNG,
no ML. Overtake PROBABILITY is explicitly out of scope until the ML phase.
