"""Next-session probe: when is the next live F1 window?"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

BASE = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BASE))

data = json.loads(urlopen("https://api.jolpi.ca/ergast/f1/2026.json?limit=30",
                          timeout=30).read())
races = data["MRData"]["RaceTable"]["Races"]
now = datetime.now(timezone.utc)
print(f"NOW UTC: {now.isoformat()}")
print(f"2026 season rounds: {len(races)}")
upcoming = []
for r in races:
    d = r.get("date")
    t = (r.get("time") or "00:00:00Z")[:8]
    try:
        rd = datetime.fromisoformat(f"{d}T{t}+00:00")
    except ValueError:
        rd = datetime.fromisoformat(d + "T00:00:00+00:00")
    if rd > now:
        upcoming.append((rd, r))
upcoming.sort(key=lambda x: x[0])
for rd, r in upcoming[:3]:
    print(f"  NEXT: R{r['round']} {r['raceName']} -> {rd.isoformat()} "
          f"(in {round((rd-now).total_seconds()/3600,1)}h)")
if not upcoming:
    print("no remaining sessions listed after now in this dataset")
