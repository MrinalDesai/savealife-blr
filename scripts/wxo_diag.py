"""Diagnose why the Orchestrate agent returns the generic fallback.
Run from repo root:  python scripts/wxo_diag.py
Prints raw JSON from the instance so nothing is guessed."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings  # noqa: E402
from app.services.ibm_auth import iam_token  # noqa: E402

BASE = settings.wxo_instance_url.rstrip("/")
H = {"Authorization": f"Bearer {iam_token(settings.ibm_cloud_api_key)}", "Content-Type": "application/json", "Accept": "application/json"}


def get(path: str, ok=(200,)) -> tuple[int, object]:
    r = httpx.get(BASE + path, headers=H, timeout=60)
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = r.text
    return r.status_code, body


def show(title: str, obj: object, limit: int = 4000) -> None:
    s = json.dumps(obj, indent=1, ensure_ascii=False) if not isinstance(obj, str) else obj
    print(f"\n===== {title} =====\n{s[:limit]}{' …[truncated]' if len(s) > limit else ''}")


# 1. agent record
code, agents = get("/v1/orchestrate/agents")
agent = next((a for a in agents if a.get("name") == "savealife_dispatch"), None) if isinstance(agents, list) else None
if not agent:
    show("agents list (agent not found!)", agents); sys.exit(1)
aid = agent.get("id") or agent.get("agent_id")
show("agent record", agent)

# 2. deployment environments
for path in (f"/v1/orchestrate/agents/{aid}/environment", f"/v1/orchestrate/agents/{aid}/environments", "/v1/orchestrate/environments"):
    code, body = get(path)
    show(f"GET {path} -> {code}", body, 2000)

# 3. tools as registered
code, tools = get("/v1/orchestrate/tools")
ours = [t for t in tools if t.get("name") in ("get_incident", "get_cameras", "get_routes", "get_hospitals", "get_air_option")] if isinstance(tools, list) else tools
show(f"our tools ({code})", ours, 6000)

# 4. one run, fully dumped
r = httpx.post(BASE + "/v1/orchestrate/runs", headers=H, timeout=60,
               json={"message": {"role": "user", "content": "Scenario S2. Severity P1, needs neuro."}, "agent_id": aid})
show(f"POST /runs -> {r.status_code}", r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)
run = r.json()
run_id, thread_id = run.get("run_id") or run.get("id"), run.get("thread_id")
for _ in range(120):
    code, cur = get(f"/v1/orchestrate/runs/{run_id}")
    if isinstance(cur, dict) and cur.get("status") in ("completed", "failed", "error", "cancelled"):
        break
    time.sleep(1)
show(f"GET /runs/{run_id} (final)", cur, 6000)
for path in (f"/v1/orchestrate/runs/{run_id}/events", f"/v1/orchestrate/runs/{run_id}/steps", f"/v1/orchestrate/threads/{thread_id}/messages", f"/v1/orchestrate/threads/{thread_id}"):
    code, body = get(path)
    show(f"GET {path} -> {code}", body, 8000)
