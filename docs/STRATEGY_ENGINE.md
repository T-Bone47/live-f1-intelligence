# STRATEGY_ENGINE.md

Deterministic candidate generator. Outputs ranked candidates with
estimated_total_s, pit_time_s, tyre_contribution_s, stops, confidence,
assumptions[] - NEVER the word optimal.

Segments: remaining laps split at fractional windows (33/50/66% for one-stop);
segment cost = laps * (base + rate * avg_age) using stint fits; beyond-life
laps penalized +1.5 s/lap (ASSUMPTION). Fresh-tyre gain 0.8 s/lap (ASSUMPTION).
Pit loss = observed session median lane time; SC/VSC applies factor 0.55 until
an SC-window stop is actually observed (then observed value wins).

Confidence: assess_confidence(samples=fit presence, completeness=pit-loss
availability). ZERO_STOP always evaluated; ONE_STOP only when pit loss is
observed; TWO_STOP as three-segment variant.

UNDERCUT/OVERCUT 2.0: availability requires gap<=2.5 s AND attacker_age+4<=
defender_age WITH observed pit loss; risk flags when closing_rate>0.2 (gap
re-opening). Evidence dict carries every input used. OVERCUT needs gap<=1.8 s
AND car ahead in pits; risk when that car is on fresh tyres <=3 laps.

PIT WINDOWS: earliest=max(age, life-6), latest=life+(6 if rate<0.15 else 2),
best=[earliest+2, latest-2]; capped by laps_remaining-2. Confidence from fit
presence. SC/VSC opportunity block emits cheap-pit indicator + expected rejoin
position with claim text OPPORTUNITY INDICATOR - not a guaranteed gain.
