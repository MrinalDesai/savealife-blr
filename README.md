# SaveAlife BLR

Agentic emergency dispatch for Bengaluru: a bystander reports a road accident, agents on watsonx Orchestrate triage it, pick road or air transport from live traffic and camera counts, clear a green corridor, and pre-alert the hospital. Built with IBM Bob for the IBM Bobathon: Build for Bengaluru (Theme 1, Smarter Streets).

## Run locally

```
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # then fill in the keys
python scripts/preflight.py     # checks every service
uvicorn app.main:app --reload
pytest -q
```

UI at http://127.0.0.1:8000/ui/ — open the three screens in separate windows:

- `/ui/bystander.html` — report the accident, add a scene photo, follow the checklist
- `/ui/dispatch.html` — map, agent trace, confirm or override, watch the vehicle move
- `/ui/er.html` — vitals, ECG, timeline, prefilled intake, accept handoff

Pick a scenario (S1–S5) on any screen; all three follow the same active incident.
`SIMULATION=true` (default) uses canned camera counts, route times and photo reads so the demo runs offline.
Health at `/health`, config at `/config/check`, API under `/api/`.

## Scenarios

Six fixed traffic cameras report LOW / HIGH / BLOCKED. Ambulances come from the chosen hospital and return to it; the helicopter flies HAL → scene → helipad hospital → HAL. A human dispatcher confirms before anything moves.

| | Cameras | Severity | Expected decision |
| --- | --- | --- | --- |
| S1 Silk Board | Madiwala BLOCKED (stalled truck), Koramangala HIGH | P2 | A rejected (blocked) → road B from St John's, corridor |
| S2 ORR Agara | Agara BLOCKED (the crash), all others HIGH | P1 | A blocked, B/C outside 25 min → air, HAL → St John's |
| S3 ORR Agara | identical to S2 | P3 | road B from St John's, no corridor |
| S4 Hosur Rd | all LOW | P1 | road A from St John's, corridor anyway |
| S5 Sarjapur Rd | HIGH, clears mid-trip | P2 | road A with corridor, passes by 1 min, ETA revised live |

Real road geometry and live times come from the Google Routes API (`python scripts/fetch_routes.py`, cached in `data/routes_cache.json`).
