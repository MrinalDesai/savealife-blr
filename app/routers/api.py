"""HTTP API used by the three pages. Thin: all logic lives in services."""
from __future__ import annotations

import json

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import settings
from app.services import sim

router = APIRouter(prefix="/api")


class NewIncident(BaseModel):
    scenario: str


class Report(BaseModel):
    text: str
    count: int = 1
    conscious: bool = True
    breathing: bool = True
    bleeding: bool = False


class Confirm(BaseModel):
    override_road: bool = False


class Tick(BaseModel):
    index: int
    done: bool


def _inc() -> sim.Incident:
    inc = sim.active()
    if not inc:
        raise HTTPException(404, "no active incident; POST /api/incident/new first")
    return inc


@router.get("/scenarios")
def scenarios() -> list[dict]:
    return [{k: s[k] for k in ("id", "title", "time", "location", "lat", "lng", "expected_severity")} for s in sim.SCENARIOS.values()]


@router.get("/hospitals")
def hospitals() -> dict:
    return sim.HOSPITALS


@router.post("/incident/new")
def incident_new(body: NewIncident) -> dict:
    if body.scenario not in sim.SCENARIOS:
        raise HTTPException(400, f"unknown scenario {body.scenario}")
    return sim.new_incident(body.scenario).state()


@router.get("/incident/state")
def incident_state() -> dict:
    return _inc().state()


@router.post("/incident/report")
def incident_report(body: Report) -> dict:
    inc = _inc()
    inc.report = body.model_dump()
    inc.run_triage()
    return inc.state()


@router.post("/incident/photo")
async def incident_photo(file: UploadFile = File(...)) -> dict:
    """Read the scene photo. Simulation returns the scenario's canned read;
    live mode sends the image to the vision model on watsonx.ai."""
    inc = _inc()
    data = await file.read()
    if settings.simulation:
        inc.photo_read = dict(inc.scenario["photo_read"])
        inc.photo_read["source"] = "simulated"
    else:
        from app.services.watsonx import ask_image  # local import keeps tests offline
        out = ask_image(
            "You describe accident-scene photos for a dispatch system. Reply with JSON only. Never describe faces or identity.",
            "Fields: people_count (int), patient_posture (lying_still|lying_moving|sitting|standing|unknown), "
            "someone_attending (bool), traffic_density (none|light|heavy_moving|heavy_one_lane|gridlock), vehicles (list of strings).",
            data, file.content_type or "image/png", json_only=True,
        )
        try:
            inc.photo_read = json.loads(out)
            inc.photo_read["source"] = settings.watsonx_vision_model
        except json.JSONDecodeError:
            raise HTTPException(502, f"vision model returned non-JSON: {out[:120]}")
    inc.log("Scene photo analysed", f"posture {inc.photo_read.get('patient_posture')}, traffic {inc.photo_read.get('traffic_density')}")
    if inc.status != "reported":
        inc.run_triage()
    return inc.state()


@router.post("/incident/photo_sim")
def incident_photo_sim() -> dict:
    """Demo shortcut: apply the scenario's canned photo read without uploading a file."""
    inc = _inc()
    inc.photo_read = dict(inc.scenario["photo_read"]); inc.photo_read["source"] = "simulated"
    inc.log("Scene photo analysed", f"posture {inc.photo_read.get('patient_posture')}, traffic {inc.photo_read.get('traffic_density')}")
    return inc.state()


@router.post("/incident/confirm")
def incident_confirm(body: Confirm) -> dict:
    inc = _inc()
    if inc.status != "triaged":
        raise HTTPException(409, f"cannot confirm in status {inc.status}")
    inc.confirm(override_road=body.override_road)
    return inc.state()


@router.post("/incident/checklist")
def incident_checklist(body: Tick) -> dict:
    inc = _inc()
    if not 0 <= body.index < len(inc.checklist):
        raise HTTPException(400, "bad index")
    inc.tick_checklist(body.index, body.done)
    return inc.state()


@router.post("/incident/handoff")
def incident_handoff() -> dict:
    inc = _inc()
    inc.handoff()
    return inc.state()
