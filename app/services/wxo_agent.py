"""watsonx Orchestrate dispatch-agent client.

ask_dispatch_agent() sends a triage summary to the 'savealife_dispatch' agent,
polls until the run completes (or times out), parses the RECOMMEND line and
returns a structured dict.  Never raises.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from app.config import settings
from app.services.ibm_auth import iam_token

# Module-level agent-id cache (populated on first successful lookup)
_agent_id: str | None = None


def _headers() -> dict[str, str]:
    token = iam_token(settings.ibm_cloud_api_key)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _base() -> str:
    return settings.wxo_instance_url.rstrip("/")


def _lookup_agent_id() -> str:
    """Return the agent id for 'savealife_dispatch', caching the result."""
    global _agent_id
    if _agent_id:
        return _agent_id
    resp = httpx.get(f"{_base()}/v1/orchestrate/agents", headers=_headers(), timeout=30)
    resp.raise_for_status()
    body = resp.json()
    agents = body if isinstance(body, list) else (body.get("agents") or body.get("data") or [])
    if isinstance(agents, list):
        for a in agents:
            if a.get("name") == "savealife_dispatch":
                _agent_id = a["id"]
                return _agent_id
    raise ValueError("Agent 'savealife_dispatch' not found in WXO agent list")


def _parse_mode(text: str) -> str | None:
    for line in text.splitlines():
        upper = line.strip().upper()
        if upper.startswith("RECOMMEND AIR"):
            return "air"
        if upper.startswith("RECOMMEND ROAD"):
            return "road"
    return None


def _extract_text(run: dict) -> str:
    """Pull assistant text from a completed run dict."""
    try:
        parts = run["result"]["data"]["message"]["content"]
        if isinstance(parts, list):
            return " ".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if isinstance(parts, str):
            return parts
    except (KeyError, TypeError):
        pass
    return ""


def ask_dispatch_agent(
    scenario_id: str,
    severity: str,
    need: str,
    timeout_s: float = 60,
) -> dict[str, Any]:
    """Call the WXO savealife_dispatch agent and return a structured result.

    Returns a dict with keys:
      ok (bool), text (str), mode ("air"|"road"|None),
      elapsed_s (float), model (str|None), error (str|None)
    """
    t0 = time.monotonic()
    try:
        agent_id = _lookup_agent_id()
        payload = {
            "message": {
                "role": "user",
                "content": f"Scenario {scenario_id}. Severity {severity}, needs {need}.",
            },
            "agent_id": agent_id,
        }
        resp = httpx.post(
            f"{_base()}/v1/orchestrate/runs",
            json=payload,
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        run_data = resp.json()
        run_id = run_data.get("id") or run_data.get("run_id")
        thread_id = run_data.get("thread_id")

        # Poll until done / failed / timeout
        poll_url = f"{_base()}/v1/orchestrate/runs/{run_id}"
        while True:
            if time.monotonic() - t0 > timeout_s:
                raise TimeoutError(f"WXO run {run_id} did not complete within {timeout_s}s")
            time.sleep(1.5)
            pr = httpx.get(poll_url, headers=_headers(), timeout=30)
            pr.raise_for_status()
            run = pr.json()
            status = (run.get("status") or "").lower()
            if status in ("completed", "failed"):
                break

        text = _extract_text(run)

        # Fallback: fetch thread messages if text is empty
        if not text and thread_id:
            mr = httpx.get(
                f"{_base()}/v1/orchestrate/threads/{thread_id}/messages",
                headers=_headers(),
                timeout=30,
            )
            if mr.is_success:
                body = mr.json()
                msgs = body if isinstance(body, list) else (body.get("messages") or body.get("data") or [])
                for m in reversed(msgs):
                    if m.get("role") == "assistant":
                        content = m.get("content", "")
                        if isinstance(content, list):
                            text = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
                        elif isinstance(content, str):
                            text = content
                        if text:
                            break

        model_name: str | None = None
        try:
            model_name = run.get("usage", {}).get("model_name")
        except AttributeError:
            pass

        ok = status == "completed"
        return {
            "ok": ok,
            "text": text,
            "mode": _parse_mode(text),
            "elapsed_s": round(time.monotonic() - t0, 2),
            "model": model_name,
            "error": None if ok else f"Run status: {status}. {text}".strip(),
        }

    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "text": "",
            "mode": None,
            "elapsed_s": round(time.monotonic() - t0, 2),
            "model": None,
            "error": str(exc),
        }
