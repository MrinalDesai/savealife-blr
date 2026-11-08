"""End-to-end flow through the API for every scenario, on simulated data."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services import sim

c = TestClient(app)

EXPECTED = {  # scenario -> (severity, mode, chosen route, hospital)
    "S1": ("P2", "road", "C", "fortis"),
    "S2": ("P1", "air", "AIR", "stjohns"),
    "S3": ("P3", "road", "C", "apollo"),
    "S4": ("P1", "road", "A", "nimhans"),
    "S5": ("P2", "road", "B", "manipal"),
}


@pytest.mark.parametrize("sid", list(EXPECTED))
def test_scenario_flow(sid):
    sev, mode, chosen, hosp = EXPECTED[sid]
    st = c.post("/api/incident/new", json={"scenario": sid}).json()
    assert st["status"] == "reported"
    st = c.post("/api/incident/photo", files={"file": ("x.png", b"\x89PNG", "image/png")}).json()
    assert st["photo_read"]["source"] == "simulated"
    st = c.post("/api/incident/report", json=st["report"]).json()
    assert st["status"] == "triaged"
    assert st["severity"] == sev, st["triage_reasons"]
    d = st["decision"]
    assert (d["mode"], d["chosen"], d["hospital"]) == (mode, chosen, hosp), d["trace"]
    assert d["trace"][-1].startswith("RECOMMEND")
    if mode == "road" and sev in ("P1", "P2"):
        assert d["corridor"], "corridor expected for P1/P2 road"
    if sev == "P3":
        assert not d["corridor"]
    st = c.post("/api/incident/confirm", json={}).json()
    assert st["status"] in ("confirmed", "enroute")
    st = c.post("/api/incident/checklist", json={"index": 0, "done": True}).json()
    assert st["checklist"][0]["done"]
    assert st["vitals"] and 60 < st["vitals"]["hr"] < 140
    assert st["golden_hour_left_sec"] > 3500


def test_s2_s3_same_crash_different_answer():
    a = c.post("/api/incident/new", json={"scenario": "S2"}).json()
    a = c.post("/api/incident/report", json=a["report"]).json()["decision"]
    b = c.post("/api/incident/new", json={"scenario": "S3"}).json()
    b = c.post("/api/incident/report", json=b["report"]).json()["decision"]
    assert [r["leg_min"] for r in a["routes"][:2]] == [r["leg_min"] for r in b["routes"][:2]]  # same crash, same A/B timings
    assert a["mode"] == "air" and b["mode"] == "road"


def test_override_air_to_road():
    st = c.post("/api/incident/new", json={"scenario": "S2"}).json()
    c.post("/api/incident/report", json=st["report"])
    st = c.post("/api/incident/confirm", json={"override_road": True}).json()
    assert st["decision"]["mode"] == "road"
    assert "override" in st["decision"]["trace"][-1].lower()


def test_s5_reevaluates(monkeypatch):
    st = c.post("/api/incident/new", json={"scenario": "S5"}).json()
    c.post("/api/incident/report", json=st["report"])
    st = c.post("/api/incident/confirm", json={}).json()
    before = st["decision"]["eta_min"]
    inc = sim.active()
    inc.confirmed_at -= sim.DEMO_TRIP_SECONDS * 0.6  # jump the clock into the return leg
    st = c.get("/api/incident/state").json()
    assert st["decision"]["eta_min"] < before
    assert any("Live re-check" in t for t in st["decision"]["trace"])


def test_confirm_requires_triage():
    c.post("/api/incident/new", json={"scenario": "S1"})
    assert c.post("/api/incident/confirm", json={}).status_code == 409


def test_blocked_route_rejected_with_reason():
    st = c.post("/api/incident/new", json={"scenario": "S1"}).json()
    d = c.post("/api/incident/report", json=st["report"]).json()["decision"]
    a = next(x for x in d["considered"] if x["id"] == "A")
    assert not a["passes"] and a["reason"].startswith("blocked at Madiwala")


def test_phases_progress():
    st = c.post("/api/incident/new", json={"scenario": "S4"}).json()
    c.post("/api/incident/report", json=st["report"])
    c.post("/api/incident/confirm", json={})
    inc = sim.active()
    seen = []
    for f in (0.05, 0.12, 0.2, 0.4, 0.55, 0.7, 0.88, 0.95):
        inc.confirmed_at = __import__("time").time() - sim.DEMO_TRIP_SECONDS * f
        seen.append(c.get("/api/incident/state").json()["phase"])
    assert seen == ["highlight_incident", "highlight_hospital", "highlight_route", "to_scene", "at_scene", "to_hospital", "arrived", "returning"]


def test_hospitals_vary_across_scenarios():
    seen = set()
    for sid in EXPECTED:
        st = c.post("/api/incident/new", json={"scenario": sid}).json()
        seen.add(c.post("/api/incident/report", json=st["report"]).json()["decision"]["hospital"])
    assert len(seen) >= 4
