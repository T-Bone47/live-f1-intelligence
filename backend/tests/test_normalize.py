"""Regression coverage for app.ingest.normalize's error paths.

NormalizationError is raised directly by name in normalize() (not via the
`om.` alias used for every other openf1-mapping call in this module), so a
missing import here is invisible until one of these two branches actually
fires — pyflakes/ruff flags it as F821 (undefined name), but nothing in the
existing suite exercised either branch before this file.
"""

from __future__ import annotations

import pytest

from app.ingest.normalize import normalize
from app.providers.openf1.mapping import NormalizationError
from app.providers.base import Channel, RawItem

SESSION = "openf1:11353"


def test_unhandled_channel_raises_normalization_error():
    """TEAM_RADIO is a real Channel member with no dispatch branch (reserved,
    not implemented). It must hit the generic `else` and raise
    NormalizationError - not NameError from an unimported name."""
    item = RawItem(Channel.TEAM_RADIO, {}, None, "B")
    with pytest.raises(NormalizationError, match="unhandled channel"):
        normalize(item, SESSION, None)


def test_unknown_results_kind_raises_normalization_error():
    """A RESULTS item whose payload kind is neither "race" nor "quali" must
    hit the same NormalizationError path inside the RESULTS branch."""
    item = RawItem(Channel.RESULTS, {"kind": "bogus", "row": {}}, None, "B")
    with pytest.raises(NormalizationError, match="unknown results kind"):
        normalize(item, SESSION, None)
