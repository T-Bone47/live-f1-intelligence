"""Two-source cross-check (Jolpica primary vs Blacktop challenger) on REAL data.

Every expected discrepancy below was found by hand in the recorded 2023
Singapore GP responses before this module existed. The module must find
exactly these - no more (false alarms), no fewer (missed conflicts).

Identity: session results match on the car number raced in that session
(both vendors verified to agree for all 20 cars); standings match on the
normalized family name. Duplicates on either side are refused.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.analysis.source_crosscheck import (
    AmbiguousIdentityError,
    crosscheck_quali,
    crosscheck_race,
    crosscheck_standings,
    name_key,
    time_to_seconds,
)
from app.core.source_policy import Resolution
from app.providers.blacktop import mapping as bt
from app.providers.jolpica import mapping as jp

FX = Path(__file__).parent / "fixtures" / "blacktop" / "2023-singapore-grand-prix"


def _load(name: str):
    path = FX / name
    if not path.exists():
        pytest.skip(f"real fixture missing: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("raw,key", [
    ("Hülkenberg", "hulkenberg"), ("Hulkenberg", "hulkenberg"),
    ("Pérez", "perez"), ("de Vries", "devries"), ("De Vries", "devries"),
])
def test_name_key_folds_case_accents_and_spaces(raw, key):
    assert name_key(raw) == key


@pytest.mark.parametrize("raw,secs", [
    ("1:46:37.418", 6397.418), ("1:30.984", 90.984), ("+0.812", 0.812),
    ("+0.812s", 0.812), ("+65.918s", 65.918), ("+1:05.918", 65.918),
    ("DNF", None), ("", None), (None, None),
])
def test_time_to_seconds_parses_both_vendor_formats(raw, secs):
    got = time_to_seconds(raw)
    assert got == (pytest.approx(secs, abs=1e-9) if secs is not None else None)


def _race():
    j = [jp.result_row_to_race_result(r, "s") for r in _load("jolpica_race_results.json")]
    b = [bt.race_row_to_result(r, "s") for r in _load("results_race.json")]
    return crosscheck_race(j, b)


def test_race_real_pair_only_disagreement_is_strolls_missing_row():
    rep = _race()
    assert rep.compared == 19
    assert [d for d in rep.discrepancies if d.resolution is Resolution.CONFLICT] == []
    rows_missing = [d for d in rep.discrepancies if d.field == "row"]
    assert [(d.subject, d.primary_value, d.challenger_value) for d in rows_missing] == [
        ("#18", "present", None)]


def test_race_gap_formats_are_compared_as_times_not_strings():
    # Jolpica "+1:05.918" vs Blacktop "+65.918s" (Lawson #40) is agreement.
    rep = _race()
    assert not any(d.subject == "#40" for d in rep.discrepancies)


def test_race_retirements_are_no_contest_not_conflict():
    # Blacktop leaves DNF laps / time / NC position unmapped (None). One side
    # silent is NO_CONTEST - never a fabricated agreement or conflict.
    rep = _race()
    russell = [d for d in rep.discrepancies if d.subject == "#63"]
    assert {d.field for d in russell} == {"laps_completed"}
    assert all(d.resolution is Resolution.NO_CONTEST for d in russell)
    bottas = {d.field for d in rep.discrepancies if d.subject == "#77"}
    assert bottas == {"laps_completed", "position"}


def test_quali_real_pair_agrees_completely():
    j = [jp.quali_row_to_result(r, "s") for r in _load("jolpica_quali_results.json")]
    b = [bt.quali_row_to_result(r, "s") for r in _load("results_qualifying.json")]
    rep = crosscheck_quali(j, b)
    assert rep.compared == 20
    assert rep.discrepancies == []


def test_standings_real_pair_flags_verstappen_points_and_the_6_point_tie_order():
    j = [jp.standing_row_to_entry(r, 2023) for r in _load("jolpica_driver_standings.json")]
    b = [bt.standing_row_to_entry(r, 2023) for r in _load("standings_drivers.json")]
    rep = crosscheck_standings(j, b)
    assert rep.compared == 22
    got = sorted((d.subject, d.field, d.primary_value, d.challenger_value)
                 for d in rep.discrepancies if d.resolution is Resolution.CONFLICT)
    assert got == [
        ("ricciardo", "position", 17, 18),
        ("verstappen", "points", 575.0, 556.0),
        ("zhou", "position", 18, 17),
    ]


def test_duplicate_identity_on_one_side_is_refused_not_guessed():
    j = [jp.quali_row_to_result(r, "s") for r in _load("jolpica_quali_results.json")]
    j[1] = j[1].model_copy(update={"driver_number": 55})
    with pytest.raises(AmbiguousIdentityError):
        crosscheck_quali(j, j)


def test_single_changed_value_is_detected():
    # Sensitivity: flip one real quali time by 1 ms -> exactly one CONFLICT.
    j = [jp.quali_row_to_result(r, "s") for r in _load("jolpica_quali_results.json")]
    b = [bt.quali_row_to_result(r, "s") for r in _load("results_qualifying.json")]
    b[0] = b[0].model_copy(update={"q3_raw": "1:30.985"})
    rep = crosscheck_quali(j, b)
    assert [(d.subject, d.field, d.resolution) for d in rep.discrepancies] == [
        ("#55", "q3", Resolution.CONFLICT)]
