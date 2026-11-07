from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "savealife-blr"}


def test_config_check_shape():
    r = client.get("/config/check")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"ok", "missing", "simulation", "text_model", "vision_model", "google_routes"}


def test_ui_served():
    r = client.get("/ui/")
    assert r.status_code == 200
    assert "SaveAlife" in r.text
