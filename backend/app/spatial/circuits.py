"""Phase 12A: cited circuit lap lengths - the only source of spatial metres.

There is no circuit geometry in the data, so a lap length is never guessed:
metres exist only for circuits listed in circuits.json with a source that was
checked when the entry was written. A circuit that is not listed gets
fractions of the lap only, and its geometry cannot pass the gate.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

CIRCUITS_PATH = Path(__file__).with_name("circuits.json")


@dataclass(frozen=True)
class CitedLength:
    lap_length_m: float
    source: str


def load_circuits(path: Path | None = None) -> dict[str, CitedLength]:
    """{circuit_short_name as stored: cited length}. Reads CIRCUITS_PATH at
    call time, so tests can point it elsewhere. Invalid entries fail loudly."""
    raw = json.loads(Path(path or CIRCUITS_PATH).read_text(encoding="utf-8"))
    out: dict[str, CitedLength] = {}
    for name, entry in raw.items():
        length, source = entry.get("lap_length_m"), entry.get("source")
        if not isinstance(length, int | float) or not math.isfinite(length) or length <= 0:
            raise ValueError(f"circuits.json: {name!r} lap_length_m must be a positive number")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"circuits.json: {name!r} needs a source")
        out[name] = CitedLength(lap_length_m=float(length), source=source)
    return out


def cited_lap_length(circuit_short_name: str | None,
                     circuits: Mapping[str, CitedLength] | None = None) -> CitedLength | None:
    if circuit_short_name is None:
        return None
    table = circuits if circuits is not None else load_circuits()
    return table.get(circuit_short_name)
