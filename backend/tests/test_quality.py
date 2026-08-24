"""Data-quality monitor: latency stats, availability, counters."""

from __future__ import annotations

from datetime import datetime, timezone

from app.ingest.quality import DataQualityMonitor


def test_latency_percentiles() -> None:
    m = DataQualityMonitor()
    base = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    # 15 samples @1s, 5 samples @2s -> p50=1.0, p95=2.0 (unambiguous)
    for i in range(20):
        delay = 1.0 if i < 15 else 2.0
        m.note_event("telemetry.car_sample", 63,
                     base, datetime.fromtimestamp(base.timestamp() + delay, tz=timezone.utc), "A")
    r = m._latency_stats(m._latency)
    assert r["samples"] == 20
    assert r["min_s"] == 1.0
    assert r["max_s"] == 2.0
    assert r["p50_s"] == 1.0
    assert r["p95_s"] == 2.0


def test_empty_stats_are_none_not_zero() -> None:
    stats = DataQualityMonitor._latency_stats([])
    assert stats == {"samples": 0, "min_s": None, "avg_s": None, "p50_s": None,
                     "p95_s": None, "max_s": None}


def test_absurd_clock_skew_ignored() -> None:
    m = DataQualityMonitor()
    base = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    far_future = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)  # +31 days
    m.note_event("weather.updated", None, base, far_future, "A")
    assert m.report()["latency_all"]["samples"] == 0


def test_negative_latency_ignored_but_counted() -> None:
    m = DataQualityMonitor()
    now = datetime.now(tz=timezone.utc)
    earlier = datetime.fromtimestamp(now.timestamp() - 5, tz=timezone.utc)
    m.note_event("lap.completed", 1, now, earlier, "A")  # ingest before source?
    assert m.report()["latency_all"]["samples"] == 0


def test_availability_matrix_per_driver() -> None:
    m = DataQualityMonitor()
    ts = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    for dn in (1, 4, 63):
        m.note_event("telemetry.car_sample", dn, ts, ts, "A")
    m.note_event("telemetry.car_sample", 63, ts, ts, "A")  # duplicate driver ok
    rep = m.report()
    assert rep["drivers_detected"] == 3
    assert rep["availability_by_driver"]["telemetry"] == [1, 4, 63]


def test_render_text_includes_key_sections() -> None:
    m = DataQualityMonitor()
    ts = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
    m.session = {"session_name": "Race", "country_code": "NED", "status": "FINISHED",
                 "date_start": ts.isoformat(), "provider_session_key": "11353"}
    for dn in range(1, 21):
        m.note_event("driver", dn, None, ts, "B")
        if dn <= 17:
            m.note_event("telemetry.car_sample", dn, ts, ts, "A")
    text = m.render_text()
    assert "DATA QUALITY" in text
    assert "Drivers: 20" in text
    assert "Telemetry (car): 17 drivers" in text
