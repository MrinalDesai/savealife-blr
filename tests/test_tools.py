"""Tests for the /api/tools stateless endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)

SCENARIOS = ["S1", "S2", "S3", "S4", "S5"]

# Severity and need for each scenario (mirrors sim.triage applied to sc["report"] + sc["photo_read"])
SCENARIO_PARAMS = {
    "S1": ("P2", "ortho"),
    "S2": ("P1", "neuro"),
    "S3": ("P3", "general"),
    "S4": ("P1", "neuro"),
    "S5": ("P2", "ortho"),
}


# ---------------------------------------------------------------- /incident


@pytest.mark.parametrize("sid", SCENARIOS)
def test_incident_200(sid):
    r = c.get(f"/api/tools/{sid}/incident")
    assert r.status_code == 200
    data = r.json()
    for key in ("scenario_id", "location", "time", "lat", "lng", "report", "photo_read", "severity_windows_min"):
        assert key in data, f"missing key {key!r} in {sid} incident response"
    assert data["scenario_id"] == sid
    report = data["report"]
    for rk in ("text", "count", "conscious", "breathing", "bleeding"):
        assert rk in report, f"missing report key {rk!r}"
    assert isinstance(data["severity_windows_min"], int)


# ---------------------------------------------------------------- /cameras


@pytest.mark.parametrize("sid", SCENARIOS)
def test_cameras_200(sid):
    r = c.get(f"/api/tools/{sid}/cameras")
    assert r.status_code == 200
    cams = r.json()
    assert isinstance(cams, list)
    assert len(cams) > 0
    for cam in cams:
        for key in ("id", "name", "lat", "lng", "count", "state", "note"):
            assert key in cam, f"missing key {key!r} in camera entry"
        assert cam["state"] in ("LOW", "HIGH", "BLOCKED"), f"unexpected state {cam['state']!r}"


# ---------------------------------------------------------------- /routes


@pytest.mark.parametrize("sid", SCENARIOS)
def test_routes_200(sid):
    sev, need = SCENARIO_PARAMS[sid]
    r = c.get(f"/api/tools/{sid}/routes", params={"severity": sev, "need": need})
    assert r.status_code == 200
    routes = r.json()
    assert isinstance(routes, list)
    assert len(routes) > 0
    for rt in routes:
        for key in (
            "id", "hospital", "hospital_name", "base_min", "live_min",
            "penalties", "leg_min", "round_trip_min", "corridor_saving",
            "eta_min", "blocked_at", "spec_ok", "amb_ok", "reason", "passes", "window_min",
        ):
            assert key in rt, f"missing route key {key!r} in {sid}"


def test_s2_route_a_blocked_no_passes():
    """For S2 P1/neuro: route A must be blocked and no route passes (→ helicopter)."""
    r = c.get("/api/tools/S2/routes", params={"severity": "P1", "need": "neuro"})
    assert r.status_code == 200
    routes = r.json()

    route_a = next((rt for rt in routes if rt["id"] == "A"), None)
    assert route_a is not None, "route A not found in S2 response"
    assert not route_a["passes"], "route A should not pass in S2 P1/neuro"
    assert route_a["reason"].startswith("blocked"), (
        f"route A reason should start with 'blocked', got: {route_a['reason']!r}"
    )

    assert not any(rt["passes"] for rt in routes), (
        "no route should pass in S2 P1/neuro (helicopter scenario)"
    )


# ---------------------------------------------------------------- /hospitals


@pytest.mark.parametrize("sid", SCENARIOS)
def test_hospitals_200(sid):
    _, need = SCENARIO_PARAMS[sid]
    r = c.get(f"/api/tools/{sid}/hospitals", params={"need": need})
    assert r.status_code == 200
    hospitals = r.json()
    assert isinstance(hospitals, list)
    assert len(hospitals) > 0
    for h in hospitals:
        for key in ("id", "name", "short", "lat", "lng", "specialties", "helipad", "has_specialty", "ambulance_free"):
            assert key in h, f"missing hospital key {key!r} in {sid}"
        assert isinstance(h["has_specialty"], bool)
        assert isinstance(h["ambulance_free"], bool)
        if h["has_specialty"]:
            assert need in h["specialties"]


# ---------------------------------------------------------------- /air


@pytest.mark.parametrize("sid", SCENARIOS)
def test_air_200(sid):
    _, need = SCENARIO_PARAMS[sid]
    r = c.get(f"/api/tools/{sid}/air", params={"need": need})
    assert r.status_code == 200
    data = r.json()
    assert "available" in data


def test_s2_air_returns_hospital():
    """For S2 neuro: air option must be available and name a hospital."""
    r = c.get("/api/tools/S2/air", params={"need": "neuro"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("available") is True, f"expected available=true, got {data}"
    assert "hospital" in data, "air response should include 'hospital' key"
    assert data["hospital"], "hospital should be non-empty"
    assert "hospital_name" in data, "air response should include 'hospital_name'"
    assert "eta_min" in data


# ---------------------------------------------------------------- validation guard


def test_unknown_scenario_404():
    r = c.get("/api/tools/S99/incident")
    assert r.status_code == 404


def test_routes_missing_params_422():
    r = c.get("/api/tools/S1/routes")
    assert r.status_code == 422
