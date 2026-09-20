"""LTTB downsampling: ordering, edge cases, and peak preservation.

No prior coverage existed for app/storage/downsample.py at all. Synthetic
signals are used deliberately here - proving the algorithm's own properties
(does it preserve order? does a real spike survive?) doesn't need real F1
data, and this project's only real recording (39 samples, fetched live from
OpenF1 for the Phase 10.1A acceptance test) is smaller than even the lowest
frequency tier's target (120), so it can't exercise actual point reduction.
The acceptance test proves the real-data wiring is correct; these prove the
algorithm itself is.
"""

from __future__ import annotations

from app.storage.downsample import FREQ_TARGETS, lttb, normalize_frequency


def test_returns_input_unchanged_when_within_budget():
    xs = [0.0, 1.0, 2.0, 3.0]
    ys = [10.0, 20.0, 15.0, 25.0]
    out_x, out_y = lttb(xs, ys, target_points=120)
    assert out_x == xs
    assert out_y == ys


def test_empty_input_stays_empty():
    out_x, out_y = lttb([], [], target_points=120)
    assert out_x == []
    assert out_y == []


def test_first_and_last_points_always_preserved():
    xs = list(range(500))
    ys = [float(i % 7) for i in xs]  # noisy but bounded
    out_x, out_y = lttb(xs, ys, target_points=50)
    assert out_x[0] == xs[0]
    assert out_x[-1] == xs[-1]
    assert out_y[0] == ys[0]
    assert out_y[-1] == ys[-1]


def test_output_x_values_stay_in_ascending_order():
    xs = list(range(1000))
    ys = [float((i * 37) % 211) for i in xs]  # pseudo-random but deterministic
    out_x, _ = lttb(xs, ys, target_points=100)
    assert out_x == sorted(out_x)
    assert len(out_x) == len(set(out_x))  # no duplicate x from bucket overlap


def test_reduces_point_count_toward_target_when_oversampled():
    xs = list(range(1000))
    ys = [float(i % 13) for i in xs]
    out_x, out_y = lttb(xs, ys, target_points=100)
    assert len(out_x) <= 105  # LTTB's target is approximate, not exact
    assert len(out_x) < len(xs)
    assert len(out_x) == len(out_y)


def test_a_real_spike_survives_downsampling_not_averaged_away():
    """The whole point of LTTB over naive decimation: a braking-style spike
    buried in flat data must show up in the output, not get smoothed out."""
    n = 300
    xs = list(range(n))
    ys = [50.0] * n
    spike_at = 150
    ys[spike_at] = 300.0  # e.g. a real braking-pressure or RPM transient

    out_x, out_y = lttb(xs, ys, target_points=30)

    assert 300.0 in out_y, "the spike value must survive, not be averaged into the flat baseline"
    # naive uniform sampling at this stride would very likely miss a single-point spike
    assert len(out_x) < n


def test_normalize_frequency_passes_through_known_values():
    for freq in FREQ_TARGETS:
        assert normalize_frequency(freq) == freq
        assert normalize_frequency(freq.lower()) == freq  # case-insensitive


def test_normalize_frequency_defaults_to_medium_for_unknown_or_missing():
    assert normalize_frequency(None) == "MEDIUM"
    assert normalize_frequency("") == "MEDIUM"
    assert normalize_frequency("ULTRA") == "MEDIUM"
