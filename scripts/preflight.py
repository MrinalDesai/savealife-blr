"""Preflight: verify every external service SaveAlife BLR depends on.

Run from the repo root with the venv active:   python scripts/preflight.py

Prints one line per check. Exit code 1 if any required check fails.
Never prints secret values.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services.ibm_auth import iam_token  # noqa: E402
from app.services import watsonx  # noqa: E402

OK, FAIL, WARN = "OK  ", "FAIL", "WARN"
results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"[{status}] {name}{' — ' + detail if detail else ''}")


def check_env() -> None:
    missing = settings.missing()
    if missing:
        record(FAIL, ".env required keys", f"missing: {', '.join(missing)}")
    else:
        record(OK, ".env required keys")
    if not settings.google_routes_api_key:
        record(WARN, "GOOGLE_ROUTES_API_KEY", "empty — route times will be simulated")


def check_iam() -> str | None:
    try:
        tok = iam_token(settings.ibm_cloud_api_key)
        record(OK, "IBM IAM token", "API key accepted")
        return tok
    except Exception as e:  # noqa: BLE001
        record(FAIL, "IBM IAM token", str(e)[:160])
        return None


def check_watsonx_models(tok: str) -> None:
    url = f"{settings.watsonx_url}/ml/v1/foundation_model_specs?version=2024-10-10&limit=200"
    try:
        r = httpx.get(url, headers={"Authorization": f"Bearer {tok}"}, timeout=60)
        r.raise_for_status()
        ids = {m["model_id"] for m in r.json().get("resources", [])}
        for label, mid in (("text model", settings.watsonx_text_model), ("vision model", settings.watsonx_vision_model)):
            record(OK if mid in ids else FAIL, f"watsonx.ai {label} listed", mid)
        granite = sorted(i for i in ids if "granite" in i)
        record(OK, "watsonx.ai Granite models available", ", ".join(granite) or "none")
    except Exception as e:  # noqa: BLE001
        record(FAIL, "watsonx.ai model list", str(e)[:160])


def check_watsonx_text() -> None:
    t0 = time.time()
    try:
        out = watsonx.ask_text(
            "You are a triage classifier for a simulation. Reply with JSON only.",
            'Classify this fictional incident: "cyclist fell, bleeding cut on arm, conscious". '
            'Fields: severity (P1|P2|P3), reason.',
            json_only=True,
        )
        js = json.loads(out)
        record(OK, "watsonx.ai Granite text call", f'{time.time()-t0:.1f}s, severity={js.get("severity")}')
    except Exception as e:  # noqa: BLE001
        record(FAIL, "watsonx.ai Granite text call", str(e)[:160])


def check_watsonx_vision() -> None:
    # 1x1 red PNG, so no real image is needed for the connectivity check.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
        "53de0000000c4944415408d763f8cfc00000030101005a4d8f1e0000000049454e44ae426082"
    )
    t0 = time.time()
    try:
        out = watsonx.ask_image(
            "Reply with JSON only.", 'Describe this image. Fields: dominant_color.', png, "image/png", json_only=True
        )
        record(OK, "watsonx.ai vision call", f"{time.time()-t0:.1f}s, reply={out[:60]}")
    except Exception as e:  # noqa: BLE001
        record(FAIL, "watsonx.ai vision call", str(e)[:160])


def check_orchestrate(tok: str) -> None:
    url = settings.wxo_instance_url.rstrip("/") + "/v1/orchestrate/agents"
    try:
        r = httpx.get(url, headers={"Authorization": f"Bearer {tok}"}, timeout=60)
        if r.status_code == 200:
            n = len(r.json()) if isinstance(r.json(), list) else "?"
            record(OK, "watsonx Orchestrate API", f"{n} agents visible")
        else:
            record(WARN, "watsonx Orchestrate API", f"HTTP {r.status_code} on {url.split('/instances/')[0]}/… (CLI auth still fine)")
    except Exception as e:  # noqa: BLE001
        record(WARN, "watsonx Orchestrate API", str(e)[:160])


def check_google_routes() -> None:
    if not settings.google_routes_api_key:
        return
    body = {
        "origin": {"location": {"latLng": {"latitude": 12.9172, "longitude": 77.6228}}},  # Silk Board
        "destination": {"location": {"latLng": {"latitude": 12.9308, "longitude": 77.6186}}},  # St John's
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
    }
    try:
        r = httpx.post(
            "https://routes.googleapis.com/directions/v2:computeRoutes",
            json=body,
            headers={
                "X-Goog-Api-Key": settings.google_routes_api_key,
                "X-Goog-FieldMask": "routes.duration,routes.distanceMeters",
            },
            timeout=30,
        )
        r.raise_for_status()
        route = r.json()["routes"][0]
        record(OK, "Google Routes API", f'{route["distanceMeters"]/1000:.1f} km, {route["duration"]}')
    except Exception as e:  # noqa: BLE001
        record(FAIL, "Google Routes API", str(e)[:160])


def check_usage(tok: str) -> None:
    """Account credit usage for the current month, via IBM Cloud Usage Reports."""
    acct = os.environ.get("IBM_ACCOUNT_ID", "").strip()
    if not acct:
        record(WARN, "IBM Cloud usage", "set IBM_ACCOUNT_ID in .env to see credit burn (Manage > Account > Account settings)")
        return
    month = time.strftime("%Y-%m")
    url = f"https://billing.cloud.ibm.com/v4/accounts/{acct}/summary/{month}"
    try:
        r = httpx.get(url, headers={"Authorization": f"Bearer {tok}"}, timeout=60)
        r.raise_for_status()
        js = r.json()
        billable = js.get("resources", {}).get("billable_cost", "?")
        offers = js.get("offers", [])
        credit_left = sum(o.get("credits", {}).get("balance", 0) for o in offers) if offers else "?"
        record(OK, "IBM Cloud usage this month", f"billable {billable} USD, promo credit remaining {credit_left}")
    except Exception as e:  # noqa: BLE001
        record(WARN, "IBM Cloud usage", str(e)[:160])


def main() -> int:
    print("SaveAlife BLR preflight\n")
    check_env()
    tok = check_iam()
    if tok:
        check_watsonx_models(tok)
        check_watsonx_text()
        check_watsonx_vision()
        check_orchestrate(tok)
        check_usage(tok)
    check_google_routes()
    fails = [r for r in results if r[0] == FAIL]
    print(f"\n{len(results)-len(fails)}/{len(results)} checks passed" + (f", {len(fails)} FAILED" if fails else ""))
    print("Bob coins: bob.ibm.com/admin/subscription (no public API).")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
