"""End-to-end flow through the API for every scenario, on simulated data."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services import sim

c = TestClient(app)

EXPECTED = {  # scenario -> (severity, mode, chosen route, hospital)
    "S1": ("P2", "road", "B", "stjohns"),
    "S2": ("P1", "air", "AIR", "stjohns"),
    "S3": ("P3", "road", "B", "stjohns"),
    "S4": ("P1", "road", "A", "stjohns"),
    "S5": ("P2", "road", "A", "stjohns"),
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
    assert [r["eta_min"] for r in a["routes"]] == [r["eta_min"] for r in b["routes"]]
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
    inc.confirmed_at -= sim.DEMO_TRIP_SECONDS * 0.5  # jump the clock past the re-eval point
    st = c.get("/api/incident/state").json()
    assert st["decision"]["eta_min"] < before
    assert any("Live re-check" in t for t in st["decision"]["trace"])


def test_confirm_requires_triage():
    c.post("/api/incident/new", json={"scenario": "S1"})
    assert c.post("/api/incident/confirm", json={}).status_code == 409
