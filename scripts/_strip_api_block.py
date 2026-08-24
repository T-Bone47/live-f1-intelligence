"""Remove the tangled telemetry endpoints block from app/api (dev tool)."""
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "backend" / "app" / "api" / "__init__.py"
s = p.read_text(encoding="utf-8")
start = s.index('    @app.get("/api/v1/sessions/{session_id}/telemetry/{driver_number}")')
end = s.index('    @app.get("/api/v1/sessions/{session_id}/circuit")')
s = s[:start] + s[end:]
p.write_text(s, encoding="utf-8")
print("removed block", start, end)
