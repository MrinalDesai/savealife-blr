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

| | Traffic | Severity | Expected decision |
| --- | --- | --- | --- |
| S1 | One route jammed | P2 | Road via the open route, corridor |
| S2 | All routes jammed | P1 | Air — every road fails the 20 min window |
| S3 | All routes jammed (same crash as S2) | P3 | Road, slowest acceptable, no corridor |
| S4 | Clear | P1 | Road, nearest neuro hospital, corridor anyway |
| S5 | All jammed, clears mid-trip | P2 | Road with corridor, ETA re-evaluated live |

## Privacy and human review

All patient data in this prototype is synthetic. The dispatch agent recommends; a human dispatcher confirms before any air dispatch or corridor request. Injury photos are analysed server-side and never shown to the hospital; only the structured read is forwarded.
