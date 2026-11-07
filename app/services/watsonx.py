"""Thin watsonx.ai client: text chat (Granite) and image chat (vision model).

Uses the REST API directly so there is no SDK version drift. Every call goes
through `chat()`; the two public helpers only shape the message list.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any

import httpx

from app.config import settings
from app.services.ibm_auth import iam_token

_API_VERSION = "2024-10-10"


def _chat_url() -> str:
    return f"{settings.watsonx_url}/ml/v1/text/chat?version={_API_VERSION}"


def chat(messages: list[dict[str, Any]], model_id: str, *, max_tokens: int = 400, temperature: float = 0.1) -> str:
    """Send a chat request and return the assistant text."""
    payload = {
        "model_id": model_id,
        "project_id": settings.watsonx_project_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {iam_token(settings.watsonx_api_key)}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resp = httpx.post(_chat_url(), json=payload, headers=headers, timeout=90)
    resp.raise_for_status()
    body = resp.json()
    return body["choices"][0]["message"]["content"]


def ask_text(system: str, user: str, *, json_only: bool = False) -> str:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    out = chat(msgs, settings.watsonx_text_model)
    return extract_json(out) if json_only else out


def ask_image(system: str, user: str, image_bytes: bytes, mime: str = "image/jpeg", *, json_only: bool = False) -> str:
    b64 = base64.b64encode(image_bytes).decode()
    msgs = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        },
    ]
    out = chat(msgs, settings.watsonx_vision_model, max_tokens=300)
    return extract_json(out) if json_only else out


def extract_json(text: str) -> str:
    """Return the first JSON object in `text` as a compact string, or the text unchanged."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return text
    try:
        return json.dumps(json.loads(m.group(0)))
    except json.JSONDecodeError:
        return text
