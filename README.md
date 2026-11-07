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

UI at http://127.0.0.1:8000/ui/ — health at /health — config at /config/check.

## Privacy and human review

All patient data in this prototype is synthetic. The dispatch agent recommends; a human dispatcher confirms before any air dispatch or corridor request. Injury photos are analysed server-side and never shown to the hospital; only the structured read is forwarded.
