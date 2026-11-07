"""IBM IAM token exchange. One function, cached for the token's lifetime."""
from __future__ import annotations

import time

import httpx

_IAM_URL = "https://iam.cloud.ibm.com/identity/token"
_cache: dict[str, tuple[str, float]] = {}


def iam_token(api_key: str) -> str:
    """Exchange an IBM Cloud API key for a bearer token. Cached until 60 s before expiry."""
    now = time.time()
    hit = _cache.get(api_key)
    if hit and hit[1] > now + 60:
        return hit[0]
    resp = httpx.post(
        _IAM_URL,
        data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": api_key},
        headers={"Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    _cache[api_key] = (body["access_token"], now + int(body.get("expires_in", 3600)))
    return body["access_token"]
