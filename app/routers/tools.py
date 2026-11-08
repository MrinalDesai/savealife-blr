"""Stateless tool endpoints for watsonx Orchestrate.

All endpoints are GET, keyed by scenario_id (S1..S5). They are purely
read-only: they create no Incident and modify no global state. Logic is
delegated entirely to app.services.sim — nothing is duplicated here.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services import sim

router = APIRouter(prefix="/api/tools", tags=["tools"])


def _sc(scenario_id: str) -> dict:
    sc = sim.SCENARIOS.get(scenario_id)
    if sc is None:
        raise HTTPException(404, f"unknown scenario_id '{scenario_id}'; valid: {list(sim.SCENARIOS)}")
    return sc


# ---------------------------------------------------------------- incident


@router.get(
    "/{scenario_id}/incident",
    operation_id="get_incident",
    summary="Return the incident report and static scene data for a scenario.",
    description=(
        "Returns the bystander report (text, counts, vital flags), photo-read result, "
        "GPS co-ordinates, and the triage severity window for the given scenario. "
        "Call this first to understand what happened before querying cameras or routes."
    ),
)
def get_incident(scenario_id: str) -> dict:
    sc = _sc(scenario_id)
    sev, need, _ = sim.triage(sc["report"], sc.get("photo_read"))
    return {
        "scenario_id": sc["id"],
        "location": sc["location"],
        "time": sc["time"],
        "lat": sc["lat"],
        "lng": sc["lng"],
        "report": sc["report"],
        "photo_read": sc.get("photo_read"),
        "severity_windows_min": sim.WINDOWS[sev],
    }


# ---------------------------------------------------------------- cameras


@router.get(
    "/{scenario_id}/cameras",
    operation_id="get_cameras",
    summary="Return the current camera state (LOW/HIGH/BLOCKED) for every junction in a scenario.",
    description=(
        "Returns one entry per traffic camera junction with its vehicle count, "
        "congestion state, and a note when blocked. Use this to understand which "
        "roads are congested or impassable before evaluating routes."
    ),
)
def get_cameras(scenario_id: str) -> list[dict]:
    sc = _sc(scenario_id)
    cams: dict[str, int] = dict(sc["cams"])
    blocked: set[str] = set(sc.get("blocked", []))
    return sim.cameras_view(sc, cams, blocked)


# ---------------------------------------------------------------- routes


@router.get(
    "/{scenario_id}/routes",
    operation_id="get_routes",
    summary="Return all candidate routes evaluated for a scenario, severity, and specialist need.",
    description=(
        "Runs the full dispatch decision for the given scenario, severity level "
        "(P1/P2/P3), and specialist need (neuro/trauma/ortho/general). Returns every "
        "considered route with timing, camera penalties, pass/fail flag, and rejection "
        "reason. Use this to identify which route the ambulance should take and why "
        "others were rejected."
    ),
)
def get_routes(
    scenario_id: str,
    severity: str = Query(..., pattern="^P[123]$", description="P1, P2, or P3"),
    need: str = Query(..., pattern="^(neuro|trauma|ortho|general)$", description="neuro, trauma, ortho, or general"),
) -> list[dict]:
    sc = _sc(scenario_id)
    cams: dict[str, int] = dict(sc["cams"])
    blocked: set[str] = set(sc.get("blocked", []))
    decision = sim.decide(sc, severity, need, cams, blocked)
    window_min = decision["window_min"]

    # Build a rich per-route dict from decision["routes"] (full route data) merged
    # with decision["considered"] (pass/fail/reason), and add window_min.
    considered_by_id = {r["id"]: r for r in decision["considered"]}
    result = []
    for r in decision["routes"]:
        c = considered_by_id.get(r["id"], {})
        h = sim.HOSPITALS[r["hospital"]]
        result.append({
            "id": r["id"],
            "hospital": r["hospital"],
            "hospital_name": h["name"],
            "base_min": r["base_min"],
            "live_min": r.get("live_min"),
            "penalties": r["penalties"],
            "leg_min": r["leg_min"],
            "round_trip_min": r["round_trip_min"],
            "corridor_saving": r["corridor_saving"],
            "eta_min": r["eta_min"],
            "blocked_at": r["blocked_at"],
            "spec_ok": r["spec_ok"],
            "amb_ok": r["amb_ok"],
            "reason": c.get("reason", r.get("reason", "")),
            "passes": r["passes"],
            "window_min": window_min,
        })
    return result


# ---------------------------------------------------------------- hospitals


@router.get(
    "/{scenario_id}/hospitals",
    operation_id="get_hospitals",
    summary="Return all hospitals with specialty match and ambulance availability for a scenario.",
    description=(
        "Returns the full hospital list annotated with whether each hospital has the "
        "required specialty and whether an ambulance is currently free for this scenario. "
        "Use this to confirm that a chosen hospital can accept the patient."
    ),
)
def get_hospitals(
    scenario_id: str,
    need: str = Query(..., pattern="^(neuro|trauma|ortho|general)$", description="neuro, trauma, ortho, or general"),
) -> list[dict]:
    sc = _sc(scenario_id)
    no_amb: set[str] = set(sc.get("no_ambulance", []))
    result = []
    for hid, h in sim.HOSPITALS.items():
        result.append({
            "id": hid,
            "name": h["name"],
            "short": h["short"],
            "lat": h["lat"],
            "lng": h["lng"],
            "specialties": h["specialties"],
            "helipad": h["helipad"],
            "has_specialty": need in h["specialties"],
            "ambulance_free": hid not in no_amb,
        })
    return result


# ---------------------------------------------------------------- air option


@router.get(
    "/{scenario_id}/air",
    operation_id="get_air_option",
    summary="Return the helicopter air-ambulance option for a scenario and specialist need.",
    description=(
        "Computes whether a helicopter can reach the scene and deliver the patient to "
        "a helipad-equipped hospital with the required specialty within a usable time. "
        "Returns flight legs and ETA when available, or {\"available\": false} when no "
        "suitable helipad hospital exists. Use this when all road routes are rejected "
        "for a P1 patient."
    ),
)
def get_air_option(
    scenario_id: str,
    need: str = Query(..., pattern="^(neuro|trauma|ortho|general)$", description="neuro, trauma, ortho, or general"),
) -> dict:
    sc = _sc(scenario_id)
    result = sim.air_option(sc, need)
    if result is None:
        return {"available": False}
    h = sim.HOSPITALS[result["hospital"]]
    return {
        "available": True,
        **result,
        "hospital_name": h["name"],
    }
