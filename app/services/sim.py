"""Simulation engine: scenario data, triage rule, route ETAs, dispatch decision,
corridor plan, vehicle clock, synthetic vitals, and the agent trace.

Everything here is deterministic given the scenario and the clock, so the demo
plays the same way every time and the tests can assert on it.
"""
from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path
from typing import Any

DATA = json.loads((Path(__file__).resolve().parents[2] / "data" / "scenarios.json").read_text(encoding="utf-8"))
HOSPITALS: dict[str, dict] = DATA["hospitals"]
JUNCTIONS: dict[str, dict] = DATA["junctions"]
WINDOWS: dict[str, int] = DATA["windows_min"]
AIR = DATA["air"]
CORRIDOR_SAVING = DATA["corridor_saving_min_per_junction"]
SCENARIOS: dict[str, dict] = {s["id"]: s for s in DATA["scenarios"]}
STATIONS: dict[str, dict] = DATA["stations"]
AIR_BASE: dict = DATA["air_base"]
GROUND_SPEED = DATA["ground_speed_km_per_min"]

DEMO_TRIP_SECONDS = 45.0  # how long the vehicle animation takes on screen
GOLDEN_HOUR_MIN = 60

# ---------------------------------------------------------------- geometry


def haversine_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = p2 - p1
    dl = math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def route_points(sc: dict, route: dict) -> list[list[float]]:
    pts = [[sc["lat"], sc["lng"]]]
    for j in route["via"]:
        pts.append([JUNCTIONS[j]["lat"], JUNCTIONS[j]["lng"]])
    h = HOSPITALS[route["hospital"]]
    pts.append([h["lat"], h["lng"]])
    return pts


def cam_level(count: int) -> str:
    """free < 80 veh, slow 80-160, jammed > 160 (same thresholds as the penalty curve)."""
    return "free" if count < 80 else ("slow" if count <= 160 else "jammed")


def cam_penalty_min(count: int) -> float:
    """Minutes added per junction from camera vehicle count. Free flow below 80."""
    return max(0, count - 80) * 0.12


# ---------------------------------------------------------------- triage


def triage(report: dict, photo_read: dict | None) -> tuple[str, str, list[str]]:
    """Return (severity, need, reasons). Takes the more severe of form and photo."""
    reasons: list[str] = []
    sev = "P3"
    if not report.get("conscious", True) or not report.get("breathing", True):
        sev = "P1"
        reasons.append("Bystander: " + ("not breathing" if not report.get("breathing", True) else "unconscious"))
    elif report.get("bleeding"):
        sev = "P2"
        reasons.append("Bystander: bleeding, conscious")
    else:
        reasons.append("Bystander: conscious, breathing, no bleeding")
    text = (report.get("text") or "").lower()
    if any(k in text for k in ("cannot move", "can't move", "leg out", "holding his arm", "holding her arm")) and sev == "P3":
        sev = "P2"
        reasons.append("Bystander text suggests a limb injury")
    if photo_read:
        posture = photo_read.get("patient_posture")
        if posture == "lying_still":
            reasons.append("Photo: patient lying still")
            sev = "P1"
        elif posture == "sitting" and sev == "P3":
            reasons.append("Photo: patient sitting, not standing")
            sev = "P2"
        elif posture == "standing":
            reasons.append("Photo: patient standing and steady")
    need = "general"
    if sev == "P1" and any(k in text for k in ("head", "not responding", "not moving", "helmet")):
        need = "neuro"
    elif sev == "P1":
        need = "trauma"
    elif sev == "P2":
        need = "ortho"
    return sev, need, reasons


# ---------------------------------------------------------------- stations


def nearest_cam(lat: float, lng: float) -> str:
    return min(JUNCTIONS, key=lambda j: haversine_km(lat, lng, JUNCTIONS[j]["lat"], JUNCTIONS[j]["lng"]))


def evaluate_stations(sc: dict, cams: dict[str, int]) -> list[dict]:
    """Response leg for every ground station: distance, congestion near the station, availability."""
    out = []
    for k, st in STATIONS.items():
        d = haversine_km(st["lat"], st["lng"], sc["lat"], sc["lng"])
        j = nearest_cam(st["lat"], st["lng"])
        pen = round(cam_penalty_min(cams.get(j, 0)) * 0.5, 1)  # half a junction's penalty on the way out
        busy = k in sc.get("stations_busy", [])
        out.append({"id": k, "name": st["name"], "lat": st["lat"], "lng": st["lng"], "distance_km": round(d, 1),
                    "response_min": round(d / GROUND_SPEED + pen, 1), "near_cam": j, "cam_penalty": pen,
                    "busy": busy, "points": [[st["lat"], st["lng"]], [sc["lat"], sc["lng"]]]})
    return out


# ---------------------------------------------------------------- decision


def evaluate_routes(sc: dict, cams: dict[str, int]) -> list[dict]:
    out = []
    for r in sc["routes"]:
        pen = {j: round(cam_penalty_min(cams.get(j, 0)), 1) for j in r["via"]}
        eta = r["base_min"] + sum(pen.values())
        out.append({**r, "penalties": pen, "eta_min": round(eta, 1), "points": route_points(sc, r)})
    return out


def air_option(sc: dict, need: str) -> dict | None:
    cands = [(k, h) for k, h in HOSPITALS.items() if h["helipad"] and need in h["specialties"]]
    if not cands:
        return None
    k, h = min(cands, key=lambda kh: haversine_km(sc["lat"], sc["lng"], kh[1]["lat"], kh[1]["lng"]))
    d = haversine_km(sc["lat"], sc["lng"], h["lat"], h["lng"])
    d0 = haversine_km(AIR_BASE["lat"], AIR_BASE["lng"], sc["lat"], sc["lng"])
    eta = AIR["liftoff_min"] + d0 / AIR["speed_km_per_min"] + AIR["load_min"] + d / AIR["speed_km_per_min"] + AIR["landing_min"]
    return {"hospital": k, "distance_km": round(d, 1), "base_distance_km": round(d0, 1), "response_min": round(AIR["liftoff_min"] + d0 / AIR["speed_km_per_min"], 1),
            "eta_min": round(eta, 1), "points": [[sc["lat"], sc["lng"]], [h["lat"], h["lng"]]],
            "response_points": [[AIR_BASE["lat"], AIR_BASE["lng"]], [sc["lat"], sc["lng"]]]}


def decide(sc: dict, severity: str, need: str, cams: dict[str, int]) -> dict:
    """The dispatch rule. Returns the decision plus the trace lines that explain it."""
    window = WINDOWS[severity]
    routes = evaluate_routes(sc, cams)
    stations = evaluate_stations(sc, cams)
    trace: list[str] = [f"Triage: {severity}, needs {need}. Arrival window {window} min from now."]
    free = [x for x in stations if not x["busy"]]
    for x in sorted(stations, key=lambda x: x["response_min"]):
        why = "busy on another call" if x["busy"] else f"{x['distance_km']} km, {x['near_cam']} cam {cams.get(x['near_cam'],0)} veh → {x['response_min']} min to scene"
        trace.append(f"Station {x['name']}: {why}.")
    station = min(free, key=lambda x: x["response_min"]) if free else None
    resp = station["response_min"] if station else 0.0
    if station:
        trace.append(f"Dispatching from {station['name']}: {resp} min to scene.")
    eligible = []
    corridor_ok = severity in ("P1", "P2")
    for r in routes:
        h = HOSPITALS[r["hospital"]]
        spec_ok = need in h["specialties"]
        pen_txt = ", ".join(f"{JUNCTIONS[j]['name']} cam {cams.get(j,0)} veh +{p} min" for j, p in r["penalties"].items())
        r["route_min"] = r["eta_min"]
        r["eta_min"] = round(r["eta_min"] + resp, 1)
        r["corridor_saving"] = round(CORRIDOR_SAVING * len(r["via"]), 1) if corridor_ok else 0.0
        r["eta_with_corridor"] = round(r["eta_min"] - r["corridor_saving"], 1)
        effective = r["eta_with_corridor"]
        if not spec_ok:
            verdict = f"no {need} at {h['short']}"
        elif effective <= window:
            verdict = "passes" + (f" with corridor ({r['eta_with_corridor']} min)" if corridor_ok and r["eta_min"] > window else "")
        else:
            verdict = "fails window" + (f" even with corridor ({r['eta_with_corridor']} min)" if corridor_ok else "")
        trace.append(f"Route {r['id']} → {h['short']}: {resp} min response + base {r['base_min']} min; {pen_txt} → {r['eta_min']} min total. {verdict[0].upper() + verdict[1:]}.")
        r["passes"] = verdict.startswith("passes")
        r["spec_ok"] = spec_ok
        if r["passes"]:
            eligible.append(r)
    default_eta = routes[0]["eta_min"]
    corridor: list[dict] = []
    if eligible:
        best = min(eligible, key=lambda r: r["eta_with_corridor"])
        mode, chosen, hospital = "road", best["id"], best["hospital"]
        if corridor_ok:
            corridor = corridor_plan(best)
            eta = best["eta_with_corridor"]
            trace.append(f"Route {best['id']} fastest inside window. {severity}: request green corridor at {len(best['via'])} junction(s), saves {best['corridor_saving']} min.")
        else:
            eta = best["eta_min"]
            trace.append(f"Route {best['id']} fastest inside window. {severity}: no corridor needed.")
        reason = f"Road via {best['id']} to {HOSPITALS[hospital]['short']}, {eta} min."
        air = None
    else:
        trace.append(f"No road route inside the {window} min window for {severity}" + (" even with a corridor." if corridor_ok else "."))
        air = air_option(sc, need) if severity == "P1" else None
        if air:
            h = HOSPITALS[air["hospital"]]
            no_pad = [HOSPITALS[k]["short"] for k in HOSPITALS if need in HOSPITALS[k]["specialties"] and not HOSPITALS[k]["helipad"]]
            trace.append(f"Air: {AIR_BASE['name']} {air['base_distance_km']} km to scene, then {air['distance_km']} km to {h['short']} helipad → {air['eta_min']} min incl. lift-off, loading and landing. Passes.")
            if no_pad:
                trace.append(f"{', '.join(no_pad)} have {need} but no helipad.")
            mode, chosen, hospital, eta = "air", "AIR", air["hospital"], air["eta_min"]
            reason = f"Air to {h['short']}, {eta} min. Every road route fails the P1 window."
        else:
            spec_routes = [r for r in routes if r["spec_ok"]] or routes
            best = min(spec_routes, key=lambda r: r["eta_with_corridor"])
            mode, chosen, hospital = "road", best["id"], best["hospital"]
            if corridor_ok:
                corridor = corridor_plan(best); eta = best["eta_with_corridor"]
            else:
                eta = best["eta_min"]
            trace.append(f"{severity} does not justify air. Taking fastest road route {best['id']}" + (" with corridor" if corridor_ok else "") + " and flagging the delay to the hospital.")
            reason = f"Road via {best['id']} to {HOSPITALS[hospital]['short']}, {eta} min (outside window, flagged)."
    saved = round(default_eta - eta, 1)
    trace.append(f"RECOMMEND {mode.upper()} → {HOSPITALS[hospital]['short']}. Saves {saved} min vs default route A. Awaiting dispatcher confirmation.")
    return {
        "mode": mode, "chosen": chosen, "hospital": hospital, "eta_min": eta, "window_min": window,
        "default_eta_min": default_eta, "minutes_saved": saved, "reason": reason,
        "routes": routes, "air": air, "corridor": corridor, "trace": trace,
        "stations": stations, "station": station["id"] if station else None,
    }


def corridor_plan(route: dict) -> list[dict]:
    plan, t = [], 2.0
    for j in route["via"]:
        plan.append({"junction": j, "name": JUNCTIONS[j]["name"], "hold_from_min": round(t, 1), "hold_to_min": round(t + 2.5, 1), "state": "planned"})
        t += 3.5
    return plan


# ---------------------------------------------------------------- vitals


def vitals(severity: str, t_sec: float, mode: str, progress: float) -> dict:
    base = {"P1": (118, 96, 58, 91, 24), "P2": (98, 118, 76, 96, 18), "P3": (84, 124, 80, 98, 16)}[severity]
    w = math.sin(t_sec / 3.0)
    # once care starts (en route) P1 improves slowly
    gain = progress * 0.35 if mode in ("road", "air") else 0.0
    hr = round(base[0] + 3 * w - 14 * gain)
    sbp = round(base[1] + 2 * math.cos(t_sec / 4.0) + 12 * gain)
    dbp = round(base[2] + 1 * w + 6 * gain)
    spo2 = round(min(99, base[3] + 1 * math.cos(t_sec / 5.0) + 6 * gain))
    rr = round(base[4] + 1 * w - 4 * gain)
    return {"hr": hr, "sbp": sbp, "dbp": dbp, "spo2": spo2, "rr": rr}


# ---------------------------------------------------------------- incident state


class Incident:
    def __init__(self, scenario_id: str):
        sc = SCENARIOS[scenario_id]
        self.id = uuid.uuid4().hex[:8]
        self.scenario = sc
        self.created_at = time.time()
        self.status = "reported"            # reported → triaged → confirmed → enroute → arrived → handed_over
        self.report: dict = dict(sc["report"])
        self.photo_read: dict | None = None
        self.severity: str | None = None
        self.need: str | None = None
        self.triage_reasons: list[str] = []
        self.decision: dict | None = None
        self.confirmed_at: float | None = None
        self.cams: dict[str, int] = dict(sc["cams"])
        self.reevaluated = False
        self.checklist = [{"text": t, "done": False} for t in sc["checklist"]]
        self.timeline: list[dict] = []
        self.log("Bystander report received", sc["location"])

    def log(self, event: str, detail: str = "") -> None:
        self.timeline.append({"t": round(time.time() - self.created_at, 1), "event": event, "detail": detail})

    # -- steps
    def run_triage(self) -> None:
        self.severity, self.need, self.triage_reasons = triage(self.report, self.photo_read)
        self.decision = decide(self.scenario, self.severity, self.need, self.cams)
        self.status = "triaged"
        self.log(f"Triage agent: {self.severity}, needs {self.need}", "; ".join(self.triage_reasons))
        self.log("Dispatch agent recommendation", self.decision["reason"])

    def confirm(self, override_road: bool = False) -> None:
        if not self.decision:
            raise ValueError("no decision yet")
        if override_road and self.decision["mode"] == "air":
            routes = [r for r in self.decision["routes"] if r["spec_ok"]] or self.decision["routes"]
            best = min(routes, key=lambda r: r["eta_min"])
            eta = best.get("eta_with_corridor", best["eta_min"])
            self.decision.update(mode="road", chosen=best["id"], hospital=best["hospital"], eta_min=eta,
                                 minutes_saved=round(self.decision["default_eta_min"] - eta, 1),
                                 corridor=corridor_plan(best))
            self.decision["trace"].append(f"Dispatcher override: road via {best['id']} instead of air.")
        self.confirmed_at = time.time()
        self.status = "confirmed"
        self.log(f"Dispatcher confirmed {self.decision['mode']}", HOSPITALS[self.decision["hospital"]]["short"])
        self.log("Handoff agent: hospital pre-alert sent", f"{HOSPITALS[self.decision['hospital']]['short']} notified, bay reserved")

    def tick_checklist(self, index: int, done: bool) -> None:
        self.checklist[index]["done"] = done
        if done:
            self.log("Bystander ✓ " + self.checklist[index]["text"])

    def handoff(self) -> None:
        self.status = "handed_over"
        self.log("ER accepted handoff")

    # -- derived
    def progress(self) -> float:
        if not self.confirmed_at:
            return 0.0
        return min(1.0, (time.time() - self.confirmed_at) / DEMO_TRIP_SECONDS)

    def maybe_reevaluate(self) -> None:
        sc = self.scenario
        if self.reevaluated or "cams_after" not in sc or not self.decision or self.decision["mode"] != "road":
            return
        if self.progress() >= sc.get("reeval_at_progress", 0.35):
            self.cams.update(sc["cams_after"])
            chosen = next(r for r in self.decision["routes"] if r["id"] == self.decision["chosen"])
            new_eval = next(r for r in evaluate_routes(sc, self.cams) if r["id"] == chosen["id"])
            old = self.decision["eta_min"]
            resp = next((x["response_min"] for x in self.decision["stations"] if x["id"] == self.decision["station"]), 0.0)
            new_eta = round(new_eval["eta_min"] + resp - chosen.get("corridor_saving", 0.0), 1)
            self.decision["eta_min"] = new_eta
            self.decision["minutes_saved"] = round(self.decision["default_eta_min"] - new_eta, 1)
            changed = ", ".join(f"{JUNCTIONS[j]['name']} now {c} veh" for j, c in sc["cams_after"].items())
            self.decision["trace"].append(f"Live re-check: cameras {changed}. Route {chosen['id']} ETA {old} → {new_eta} min.")
            self.log("Dispatch agent re-evaluated", f"ETA {old} → {new_eta} min as jam clears")
            self.reevaluated = True

    def state(self) -> dict[str, Any]:
        self.maybe_reevaluate()
        p = self.progress()
        now = time.time()
        if self.status == "confirmed" and p > 0:
            self.status = "enroute"
        if self.status == "enroute" and p >= 1.0:
            self.status = "arrived"
            self.log("Arrived at hospital")
        corridor = self.decision["corridor"] if self.decision else []
        for i, c in enumerate(corridor):
            c["state"] = "green" if p > (i + 0.5) / (len(corridor) + 1) else ("planned" if p == 0 else "holding")
        elapsed_min = (now - self.created_at) / 60
        return {
            "id": self.id, "scenario": {k: self.scenario[k] for k in ("id", "title", "time", "location", "lat", "lng")},
            "status": self.status, "created_at": self.created_at, "elapsed_min": round(elapsed_min, 2),
            "golden_hour_left_sec": max(0, int(GOLDEN_HOUR_MIN * 60 - (now - self.created_at))),
            "report": self.report, "photo_read": self.photo_read,
            "severity": self.severity, "need": self.need, "triage_reasons": self.triage_reasons,
            "decision": self.decision, "cams": self.cams,
            "cameras": [{"id": j, "name": JUNCTIONS[j]["name"], "lat": JUNCTIONS[j]["lat"], "lng": JUNCTIONS[j]["lng"], "count": self.cams.get(j, 0), "level": cam_level(self.cams.get(j, 0))} for j in JUNCTIONS],
            "progress": round(p, 3),
            "eta_left_min": round(self.decision["eta_min"] * (1 - p), 1) if self.decision and self.confirmed_at else None,
            "vitals": vitals(self.severity, now - self.created_at, self.decision["mode"] if self.decision and self.confirmed_at else "", p) if self.severity else None,
            "checklist": self.checklist, "timeline": self.timeline,
            "patient": {"id": "SAL-DEMO-0001", "name": "Ravi Demo", "sex": "M", "age": 34, "blood": "O+"},
            "hospitals": HOSPITALS, "junctions": JUNCTIONS, "stations": STATIONS, "air_base": AIR_BASE,
            "candidate_routes": [{"id": r["id"], "hospital": r["hospital"], "base_min": r["base_min"], "points": route_points(self.scenario, r)} for r in self.scenario["routes"]],
        }


# single active incident for the demo
_active: Incident | None = None


def new_incident(scenario_id: str) -> Incident:
    global _active
    _active = Incident(scenario_id)
    return _active


def active() -> Incident | None:
    return _active
