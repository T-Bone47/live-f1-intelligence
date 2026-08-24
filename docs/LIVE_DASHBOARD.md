# LIVE_DASHBOARD.md

Run:

1. backend gateway:
   python scripts/serve_realtime.py --mode replay recordings/openf1-11353-race --port 8000
   (or --mode live --ref latest during a real session)
2. frontend dev server:
   cd frontend && npm run dev     # http://localhost:5173 (proxies /api,/ws)

## Layout

TOP BAR   mode badge (LIVE/REPLAY/CONNECTING/DISCONNECTED), session,
          circuit, current lap, provider, last update, sequence number
TIMING    position/gap/interval/lap/last/best/tyre+age (canonical rows)
MAIN      telemetry speed trace with A/B driver compare; circuit panel shows
          honest fallback (live order strip) until verified geometry exists
SIDE      sectors (color + TEXT label), tyres incl ESTIMATED degradation,
          race pace (rolling5/trend), battles, race-control/key-event feed
FOOTER    profile emphasis + calc version

## Session-aware emphasis (single codebase)

PRACTICE -> pace/tyres/sectors emphasized
QUALIFYING -> sectors/theoretical emphasized
SPRINT/RACE -> battles + strategy-adjacent panels added

## Data-quality UX rules

Missing value renders as em-dash or explicit unavailable text - never 0.
Sector states always carry a text label alongside color. Connection status is
driven by actual frame flow; REPLAY badge appears only for replay-prefixed
sessions; DISCONNECTED shown when the socket drops.
