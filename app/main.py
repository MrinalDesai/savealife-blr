"""SaveAlife BLR — FastAPI entry point."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="SaveAlife BLR", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "savealife-blr"}


@app.get("/config/check")
def config_check() -> dict:
    """Which settings are present. Never returns values, only names."""
    missing = settings.missing()
    return {
        "ok": not missing,
        "missing": missing,
        "simulation": settings.simulation,
        "text_model": settings.watsonx_text_model,
        "vision_model": settings.watsonx_vision_model,
        "google_routes": bool(settings.google_routes_api_key),
    }


app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
