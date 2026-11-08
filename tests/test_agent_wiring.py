"""Tests for the watsonx Orchestrate agent wiring in sim.Incident."""
import time
import types
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import sim

c = TestClient(app)


def _mock_settings(simulation: bool = False, agent_live: bool = True):
    """Return a lightweight settings stand-in with the required attributes."""
    import app.config as cfg_mod
    orig = cfg_mod.settings
    mock = types.SimpleNamespace(
        **{f.name: getattr(orig, f.name) for f in orig.__dataclass_fields__.values()},
    )
    mock.simulation = simulation
    mock.agent_live = agent_live
    return mock


def test_agent_done_agrees(monkeypatch):
    """When ask_dispatch_agent returns ok=True mode='air', agent.status='done' and agrees=True for S2."""
    canned = {
        "ok": True,
        "text": "Road options all fail within the P1 window.\nRECOMMEND AIR - helicopter to St John's.",
        "mode": "air",
        "elapsed_s": 1.23,
        "model": "ibm/granite-test",
        "error": None,
    }

    def fake_ask(scenario_id, severity, need, timeout_s=60):
        return dict(canned)

    import app.services.wxo_agent as wxo_mod
    import app.services.sim as sim_mod

    monkeypatch.setattr(wxo_mod, "ask_dispatch_agent", fake_ask)
    monkeypatch.setattr(sim_mod, "settings", _mock_settings(simulation=False, agent_live=True))

    st = c.post("/api/incident/new", json={"scenario": "S2"}).json()
    st = c.post("/api/incident/report", json=st["report"]).json()
    inc = sim.active()

    assert inc.decision["mode"] == "air"

    # Background thread should finish quickly with the fake
    deadline = time.time() + 5
    while inc.agent.get("status") != "done" and time.time() < deadline:
        time.sleep(0.05)

    assert inc.agent["status"] == "done", f"agent dict: {inc.agent}"
    assert inc.agent["agrees"] is True
    assert inc.state()["agent"]["status"] == "done"
    assert inc.state()["agent"]["agrees"] is True


def test_agent_ok_false_decision_unchanged(monkeypatch):
    """When ask_dispatch_agent returns ok=False, agent.status='done' and the rule decision is unchanged."""
    def fake_ask_fail(scenario_id, severity, need, timeout_s=60):
        return {
            "ok": False,
            "text": "",
            "mode": None,
            "elapsed_s": 0.5,
            "model": None,
            "error": "Connection refused",
        }

    import app.services.wxo_agent as wxo_mod
    import app.services.sim as sim_mod

    monkeypatch.setattr(wxo_mod, "ask_dispatch_agent", fake_ask_fail)
    monkeypatch.setattr(sim_mod, "settings", _mock_settings(simulation=False, agent_live=True))

    st = c.post("/api/incident/new", json={"scenario": "S2"}).json()
    st = c.post("/api/incident/report", json=st["report"]).json()
    inc = sim.active()

    assert inc.decision["mode"] == "air"   # rule decision unchanged

    deadline = time.time() + 5
    while inc.agent.get("status") != "done" and time.time() < deadline:
        time.sleep(0.05)

    assert inc.agent["status"] == "done", f"agent dict: {inc.agent}"
    assert inc.agent["ok"] is False
    assert inc.agent["error"] == "Connection refused"
    # Rule decision must not have changed
    assert inc.decision["mode"] == "air"
