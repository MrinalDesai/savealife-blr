"""
wxo_test_agent.py
-----------------
End-to-end smoke test for the savealife_dispatch watsonx Orchestrate native agent.

API flow (watsonx Orchestrate SaaS chat API)
--------------------------------------------
1. POST {WXO_INSTANCE_URL}/v1/orchestrate/runs
   body: {"message": {"role": "user", "content": "<text>"}, "agent_id": "<agent_id>"}
   returns JSON with run_id and thread_id.

2. Poll GET {WXO_INSTANCE_URL}/v1/orchestrate/runs/{run_id} every 1 s until
   "status" is "completed" (or "failed"), max 120 s.

3. GET {WXO_INSTANCE_URL}/v1/orchestrate/threads/{thread_id}/messages
   Take the last message whose role is "assistant"; its content may be a plain
   string or a list of {"response_type": "text", "text": "..."} parts — join them.

Usage
-----
    python scripts/wxo_test_agent.py

Required environment variables (via .env or the shell):
    IBM_CLOUD_API_KEY     — IBM Cloud API key used for IAM token exchange
    WXO_INSTANCE_URL      — base URL of the Orchestrate instance,
                            e.g. https://<guid>.orchestrate.ibm.com
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Bootstrap: load .env from repo root (two levels up from scripts/)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")

# ---------------------------------------------------------------------------
# IAM token helper — reuse the production implementation
# ---------------------------------------------------------------------------
sys.path.insert(0, str(_REPO_ROOT))
from app.services.ibm_auth import iam_token  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_IBM_CLOUD_API_KEY = os.environ["IBM_CLOUD_API_KEY"]
_WXO_BASE = os.environ["WXO_INSTANCE_URL"].rstrip("/")

_AGENT_NAME = "savealife_dispatch"

# Timeout for a single HTTP call (seconds)
_HTTP_TIMEOUT = 60
# Maximum time to wait for an async run to complete (seconds)
_POLL_TIMEOUT = 120
_POLL_INTERVAL = 1


# ---------------------------------------------------------------------------
# Scenario definitions (mirrored from data/scenarios.json)
# ---------------------------------------------------------------------------
def _load_scenarios() -> list[dict]:
    """Read scenarios from data/scenarios.json and return the five test cases."""
    data_path = _REPO_ROOT / "data" / "scenarios.json"
    raw = json.loads(data_path.read_text())
    return raw["scenarios"]


# Expected recommendation mode per scenario id
_EXPECTED_MODE: dict[str, str] = {
    "S1": "RECOMMEND ROAD",
    "S2": "RECOMMEND AIR",
    "S3": "RECOMMEND ROAD",
    "S4": "RECOMMEND ROAD",
    "S5": "RECOMMEND ROAD",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _find_agent_id(client: httpx.Client, token: str) -> str:
    """Look up the agent id for _AGENT_NAME via GET /v1/orchestrate/agents."""
    r = client.get(
        f"{_WXO_BASE}/v1/orchestrate/agents",
        headers=_headers(token),
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    body = r.json()
    # The list may be under a key like "agents" or be the root list itself
    agents: list[dict] = body if isinstance(body, list) else body.get("agents", body.get("items", []))
    for agent in agents:
        if agent.get("name") == _AGENT_NAME or agent.get("agent_name") == _AGENT_NAME:
            aid = agent.get("agent_id") or agent.get("id")
            if aid:
                return str(aid)
    raise RuntimeError(
        f"Agent '{_AGENT_NAME}' not found in GET /v1/orchestrate/agents. "
        "Run scripts/wxo_import_agent.ps1 first."
    )


def _start_run(client: httpx.Client, token: str, agent_id: str, message: str) -> tuple[str, str]:
    """
    POST /v1/orchestrate/runs to start a new run.
    Returns (run_id, thread_id).
    """
    payload = {
        "message": {"role": "user", "content": message},
        "agent_id": agent_id,
    }
    r = client.post(
        f"{_WXO_BASE}/v1/orchestrate/runs",
        json=payload,
        headers=_headers(token),
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    body = r.json()
    run_id = body["run_id"]
    thread_id = body["thread_id"]
    return str(run_id), str(thread_id)


def _poll_run(client: httpx.Client, token: str, run_id: str) -> dict:
    """
    Poll GET /v1/orchestrate/runs/{run_id} every _POLL_INTERVAL seconds until
    status is "completed" or "failed".  Returns the final run object.
    """
    url = f"{_WXO_BASE}/v1/orchestrate/runs/{run_id}"
    deadline = time.monotonic() + _POLL_TIMEOUT
    while time.monotonic() < deadline:
        r = client.get(url, headers=_headers(token), timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        body = r.json()
        status = body.get("status", "")
        if status == "completed":
            return body
        if status in ("failed", "error", "cancelled"):
            raise RuntimeError(f"Run ended with status={status!r}: {body}")
        time.sleep(_POLL_INTERVAL)
    raise TimeoutError(f"Run {run_id!r} did not complete within {_POLL_TIMEOUT}s")


def _fetch_answer(client: httpx.Client, token: str, thread_id: str) -> str:
    """
    GET /v1/orchestrate/threads/{thread_id}/messages, find the last assistant
    message, and extract its text content.
    Content may be a plain string or a list of {"response_type":"text","text":...} parts.
    """
    r = client.get(
        f"{_WXO_BASE}/v1/orchestrate/threads/{thread_id}/messages",
        headers=_headers(token),
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    body = r.json()
    messages: list[dict] = body if isinstance(body, list) else body.get("messages", [])

    # Walk backwards for the last assistant message
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, list):
                return " ".join(
                    part["text"]
                    for part in content
                    if part.get("response_type") == "text" and "text" in part
                )
            return str(content)
    return ""


def _count_tool_calls(run_body: dict, messages: list[dict] | None) -> str:
    """
    Best-effort count of tool calls from the run object or thread messages.
    Looks for keys: step_history, tool_calls, or messages with role "tool".
    Returns a string count or "n/a".
    """
    # Check run object first
    if "step_history" in run_body:
        return str(len(run_body["step_history"]))
    if "tool_calls" in run_body:
        calls = run_body["tool_calls"]
        if isinstance(calls, list):
            return str(len(calls))

    # Check thread messages
    if messages:
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if tool_msgs:
            return str(len(tool_msgs))

    return "n/a"


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------
def main() -> None:
    scenarios = _load_scenarios()

    token = iam_token(_IBM_CLOUD_API_KEY)
    client = httpx.Client()

    print(f"Looking up agent '{_AGENT_NAME}'...")
    agent_id = _find_agent_id(client, token)
    print(f"  agent_id = {agent_id}")
    print()

    results: list[tuple[str, str, str, bool, float, str]] = []
    all_passed = True

    for sc in scenarios:
        sid = sc["id"]
        sev = sc["expected_severity"]
        need = sc["need"]
        expected_mode = _EXPECTED_MODE[sid]

        message = f"Scenario {sid}. Severity {sev}, needs {need}."
        print(f"--- {sid} ({sev}, {need}) ---")
        print(f"  Sending: {message!r}")

        # Refresh token (may have expired between calls)
        token = iam_token(_IBM_CLOUD_API_KEY)

        t0 = time.monotonic()
        try:
            run_id, thread_id = _start_run(client, token, agent_id, message)
            run_body = _poll_run(client, token, run_id)

            # Fetch thread messages for answer extraction and tool-call counting
            r_msgs = client.get(
                f"{_WXO_BASE}/v1/orchestrate/threads/{thread_id}/messages",
                headers=_headers(token),
                timeout=_HTTP_TIMEOUT,
            )
            r_msgs.raise_for_status()
            msgs_body = r_msgs.json()
            thread_messages: list[dict] = (
                msgs_body if isinstance(msgs_body, list) else msgs_body.get("messages", [])
            )

            answer = _fetch_answer(client, token, thread_id)
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - t0
            print(f"  ERROR: {exc}")
            results.append((sid, expected_mode, f"ERROR: {exc}", False, elapsed, "n/a"))
            all_passed = False
            continue

        elapsed = time.monotonic() - t0
        tool_count = _count_tool_calls(run_body, thread_messages)

        # Normalise for matching
        answer_upper = answer.upper()
        if expected_mode == "RECOMMEND AIR":
            match = "RECOMMEND AIR" in answer_upper
        else:
            match = "RECOMMEND ROAD" in answer_upper

        status = "✓ PASS" if match else "✗ FAIL"
        if not match:
            all_passed = False

        # Show first 200 chars of the answer
        snippet = answer[:200].replace("\n", " ")
        print(f"  Agent said: {snippet}{'...' if len(answer) > 200 else ''}")
        print(f"  Elapsed: {elapsed:.1f}s  Tool calls: {tool_count}")
        print(f"  {status}")

        results.append((sid, expected_mode, answer, match, elapsed, tool_count))

    # Summary table
    print("\n" + "=" * 80)
    print(f"{'Scenario':<12} {'Expected mode':<18} {'Agent said':<22} {'Elapsed':>8}  {'Tools':>6}  {'Match'}")
    print("-" * 80)
    for sid, exp, ans, ok, elapsed, tool_count in results:
        if ans.startswith("ERROR:"):
            detected = "ERROR"
        elif "RECOMMEND AIR" in ans.upper():
            detected = "RECOMMEND AIR"
        elif "RECOMMEND ROAD" in ans.upper():
            detected = "RECOMMEND ROAD"
        else:
            detected = "UNKNOWN"
        print(
            f"{sid:<12} {exp:<18} {detected:<22} {elapsed:>7.1f}s  {tool_count:>6}  {'✓' if ok else '✗'}"
        )
    print("=" * 80)

    if not all_passed:
        print("\nSome scenarios did not match. See details above.")
        sys.exit(1)
    else:
        print("\nAll scenarios passed.")


if __name__ == "__main__":
    main()
