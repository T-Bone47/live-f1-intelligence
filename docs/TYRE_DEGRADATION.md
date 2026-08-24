# TYRE_DEGRADATION.md

Normative methodology for ESTIMATED degradation (Phase 2).

## 1. Model

    lap_time(age) = base_pace + degradation_rate * age   [s]

Ordinary least squares over one stint window of representative laps.
Robustness: single MAD pass (threshold 2.5) removes spike laps (traffic,
mistakes) before fitting; removed count reported as n_excluded.

## 2. Guards against overfitting / noise

- MIN_SAMPLES = 4: below this the estimate is None (never guessed).
- MAD pass needs >=4 points and non-zero MAD; degenerate series skip removal.
- Confidence: HIGH n>=8 AND r2>=0.5 | MEDIUM n>=5 | LOW n==4 band |
  NONE insufficient. r2 is clipped at 0; perfectly flat stints have undefined
  r2 and are contractually reported as 0 -> confidence capped at MEDIUM.

## 3. Inputs and exclusions

Inputs: classified REPRESENTATIVE laps inside [lap_start, lap_end] of the
stint record; x = lap_number - lap_start. Excluded: all classification-flagged
laps plus MAD outliers (count surfaced). Compound comes from the stint record;
UNKNOWN until upstream delivers it (honest nulls in snapshots).

## 4. Labeling rule (hard requirement)

Every surface presenting this value MUST include:
    label = ESTIMATED DEGRADATION
and never present it as official F1 data. Events set prediction=True.

## 5. Limitations

- Linear model: cannot capture thermal-cliff or graining-then-recovery shapes.
- No fuel/track-evolution correction (cross-stint base_pace comparisons drift).
- Short final stints (<4 clean laps) produce no estimate by design.
