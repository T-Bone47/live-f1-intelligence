"""Append the Phase-4 telemetry API block to app/api/__init__.py (dev tool)."""
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "backend" / "app" / "api" / "__init__.py"
s = p.read_text(encoding="utf-8")
anchor = '    @app.get("/api/v1/sessions/{session_id}/circuit")'

block = '''    @app.get("/api/v1/sessions/{session_id}/telemetry/{driver_number}")
    async def get_telemetry(session_id: str, driver_number: int,
                            start: str | None = None, end: str | None = None,
                            lap: int | None = None,
                            frequency: str = "MEDIUM",
                            fields: str | None = None):
        """Canonical telemetry query with RAW/HIGH/MEDIUM/LOW LTTB
        downsampling. RAW windows are capped at 20 minutes."""
        from datetime import datetime, timedelta

        from app.storage.downsample import FREQ_TARGETS, lttb, normalize_frequency
        from app.storage.db import connect as db_connect

        freq = normalize_frequency(frequency)
        validate_session_id(session_id)
        pool = await db_connect(get_settings().database_url)
        try:
            if lap:
                win = await pool.fetchrow(
                    "SELECT started_at, duration_s FROM laps WHERE session_id=$1"
                    " AND driver_number=$2 AND lap_number=$3",
                    session_id, driver_number, lap)
                if not win or not win["started_at"]:
                    raise HTTPException(404, f"lap {lap} unknown for driver")
                start_dt = win["started_at"]
                end_dt = (start_dt + timedelta(seconds=win["duration_s"])
                          if win["duration_s"] else start_dt + timedelta(minutes=3))
            else:
                end_row = await pool.fetchrow(
                    "SELECT max(ts) AS m FROM telemetry_car WHERE session_id=$1"
                    " AND driver_number=$2", session_id, driver_number)
                if not end_row or not end_row["m"]:
                    raise HTTPException(404,
                                        "no stored telemetry for this driver/session")
                start_dt = end_row["m"] - timedelta(minutes=(20 if freq == "RAW" else 30))
                end_dt = end_row["m"]
            if start and end:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                if freq == "RAW" and (end_dt - start_dt).total_seconds() > 1200:
                    raise HTTPException(422, "RAW windows are capped at 20 minutes")

            rows = await pool.fetch(
                """SELECT ts, rpm, speed_kph, gear, throttle_pct, brake_pct, drs
                   FROM telemetry_car WHERE session_id=$1 AND driver_number=$2
                   AND ts BETWEEN $3 AND $4 ORDER BY ts""",
                session_id, driver_number, start_dt, end_dt)
            loc_rows = await pool.fetch(
                """SELECT ts, x, y, z FROM telemetry_location
                   WHERE session_id=$1 AND driver_number=$2
                   AND ts BETWEEN $3 AND $4 ORDER BY ts""",
                session_id, driver_number, start_dt, end_dt)
        finally:
            await pool.close()

        key_map = {"speed": "speed_kph", "gear": "gear", "drs": "drs",
                   "throttle": "throttle_pct", "brake": "brake_pct", "rpm": "rpm"}

        def numeric_series(k: str) -> list[dict]:
            src = loc_rows if k in ("x", "y", "z") else rows
            col = key_map.get(k, k)
            xs: list[float] = []
            ys: list[float] = []
            for r in src:
                v = r.get(col)
                if v is None:
                    continue
                xs.append(r["ts"].timestamp())
                ys.append(float(v))
            target = FREQ_TARGETS.get(freq) or len(xs)
            dxs, dys = lttb(xs, ys, target)
            return [{"ts": datetime.fromtimestamp(x, tz=_UTC).isoformat(), "value": y}
                    for x, y in zip(dxs, dys)]

        def gps_series() -> list[dict]:
            target = FREQ_TARGETS.get(freq) or len(loc_rows)
            step = max(1, len(loc_rows) // (target or 1))
            return [
                {"ts": r["ts"].isoformat(), "x": r["x"], "y": r["y"], "z": r["z"]}
                for r in loc_rows[::step]
            ]

        keys = ([f.strip() for f in fields.split(",")] if fields else
                ["speed", "throttle", "brake", "gear", "rpm", "drs", "gps"])
        series_out: dict[str, Any] = {}
        for k in keys:
            series_out[k] = gps_series() if k == "gps" else numeric_series(k)

        live = hub_active(session_id)
        return JSONResponse({
            "session_id": session_id, "driver_number": driver_number,
            "frequency": freq, "lap": lap,
            "window": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
            "provenance": {"class": "A" if live else "B",
                           "kind": "stored canonical telemetry"},
            "series": series_out,
        })

    @app.get("/api/v1/sessions/{session_id}/telemetry/compare")
    async def compare_telemetry(session_id: str, drivers: str,
                                lap: int | None = None,
                                frequency: str = "MEDIUM"):
        """Driver-vs-driver comparison. Aligned by normalized lap progress when
        ?lap= is provided; otherwise timestamp alignment only - and we say so."""
        validate_session_id(session_id)
        nums = [int(d) for d in drivers.split(",")[:3]]
        if len(nums) < 2:
            raise HTTPException(422, "provide >=2 drivers")
        series: dict[str, Any] = {}
        for dn in nums:
            resp = await get_telemetry(session_id, dn, lap=lap,
                                       frequency=frequency,
                                       fields="speed,throttle,brake,gps")
            series[str(dn)] = resp.json()["series"]
        return {
            "session_id": session_id, "drivers": nums, "lap": lap,
            "alignment": {
                "mode": "normalized_lap_progress" if lap else "timestamp",
                "valid": bool(lap),
                "note": None if lap else
                        "timestamp alignment only; pass ?lap= for per-lap comparison",
            },
            "series": series,
        }

'''
marker = '    @app.get("/api/v1/sessions/{session_id}/circuit")'
s = s.replace(anchor, block + anchor)

# helper imports used by the new endpoints
helpers = '''

def _get_settings():
    from app.config import get_settings as _gs

    return _gs()


_UTC = timezone.utc


def hub_active(session_id: str) -> bool:
    reg = get_registry()
    return reg is not None and reg.get(session_id) is not None


get_settings = _get_settings
'''
if "_UTC = timezone.utc" not in s:
    s += helpers

p.write_text(s, encoding="utf-8")
print("appended telemetry API block")
