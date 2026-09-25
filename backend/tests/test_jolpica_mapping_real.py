"""Jolpica mapper on REAL Ergast-shaped rows (2023 Singapore GP fixture).

Regression: the mapper read Driver["number"], a key Ergast rows do not have
(the car number is row["number"]; Driver carries permanentNumber, which is
the CURRENT number - Verstappen "3" in a 2023 row). Every Jolpica result
therefore had driver_number=None. Found by the Blacktop cross-check.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.providers.jolpica.mapping import quali_row_to_result, result_row_to_race_result

FX = Path(__file__).parent / "fixtures" / "blacktop" / "2023-singapore-grand-prix"


def _load(name: str):
    path = FX / name
    if not path.exists():
        pytest.skip(f"real fixture missing: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _by_family(rows, family):
    return next(r for r in rows if r["Driver"]["familyName"] == family)


def test_race_driver_number_is_the_car_number_raced_that_day():
    rows = _load("jolpica_race_results.json")
    ver = result_row_to_race_result(_by_family(rows, "Verstappen"), "s")
    assert ver.driver_number == 1  # permanentNumber says 3 - must not be used
    assert all(result_row_to_race_result(r, "s").driver_number is not None for r in rows)


def test_quali_driver_number_is_the_car_number():
    rows = _load("jolpica_quali_results.json")
    assert quali_row_to_result(_by_family(rows, "Sainz"), "s").driver_number == 55
    assert quali_row_to_result(_by_family(rows, "Verstappen"), "s").driver_number == 1
