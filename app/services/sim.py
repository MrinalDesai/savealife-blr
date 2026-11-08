"""Simulation engine for SaveAlife BLR.

Story: a bystander reports a crash. The triage agent sets severity. The dispatch
agent reads six fixed traffic cameras (LOW / HIGH / BLOCKED) plus Routes API times,
evaluates every candidate hospital-and-route, and picks the fastest round trip
(hospital → scene → hospital) that arrives inside the severity window. If none can
for a P1, it proposes the helicopter (HAL → scene → helipad hospital → HAL).
A human dispatcher confirms before anything moves.

Deterministic given the scenario and the clock.
"""
from __future__ import annotations

import json
import math
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from app.config import settings

DATA = json.loads((Path(__file__).resolve().parents[2] / "data" / "scenarios.json").read_text(encoding="utf-8"))
HOSPITALS: dict[str, dict] = DATA["hospitals"]
JUNCTIONS: dict[str, dict] = DATA["junctions"]
WINDOWS: dict[str, int] = DATA["windows_min"]
AIR = DATA["air"]
AIR_BASE: dict = DATA["air_base"]
CORRIDOR_SAVING = DATA["corridor_saving_min_per_junction"]
TH = DATA["cam_thresholds"]
SCENARIOS: dict[str, dict] = {s["id"]: s for s in DATA["scenarios"]}

DEMO_TRIP_SECONDS = 60.0   # whole animation: out, scene, back, return-to-base
GOLDEN_HOUR_MIN = 60

try:
    from app.services.routes_api import load_cache as _load_cache
    ROUTE_CACHE: dict = _load_cache()
except Exception:  # noqa: BLE001
    ROUTE_CACHE = {}

# Animation phases as fractions of DEMO_TRIP_SECONDS
PHASES = [  # (end_fraction, name)
    (0.08, "highlight_incident"),
    (0.16, "highlight_hospital"),
    (0.24, "highlight_route"),
    (0.52, "to_scene"),
    (0.58, "at_scene"),
    (0.86, "to_hospital"),
    (0.90, "arrived"),
    (1.00, "returning"),
]

# ---------------------------------------------------------------- geometry


def haversine_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def route_points(sc: dict, route: dict) -> list[list[float]]:
    """Scene → hospital. Real road geometry from the Routes API cache when present."""
    cached = ROUTE_CACHE.get(route_key(sc, route))
    if cached:
        return cached["points"]
    pts = [[sc["lat"], sc["lng"]]]
    for j in route["via"]:
        pts.append([JUNCTIONS[j]["lat"], JUNCTIONS[j]["lng"]])
    h = HOSPITALS[route["hospital"]]
    pts.append([h["lat"], h["lng"]])
    return pts


def route_key(sc: dict, route: dict) -> str:
    return f"{sc['id']}:route:{route['id']}:{route['hospital']}:{'-'.join(route['via'])}"


def route_live_min(sc: dict, route_id: str) -> float | None:
    route = next(r for r in sc["routes"] if r["id"] == route_id)
    cached = ROUTE_CACHE.get(route_key(sc, route))
    return round(cached["duration_s"] / 60, 1) if cached else None


# ---------------------------------------------------------------- cameras


def cam_state(sc: dict, j: str, cams: dict[str, int], blocked: set[str]) -> str:
    if j in blocked:
        return "BLOCKED"
    c = cams.get(j, 0)
    return "LOW" if c < TH["low_max"] else "HIGH"


def cam_penalty_min(count: int) -> float:
    """Minutes added per HIGH camera on a leg. Free flow below the LOW threshold."""
    return max(0, count - TH["low_max"]) * 0.08


def cameras_view(sc: dict, cams: dict[str, int], blocked: set[str]) -> list[dict]:
    out = []
    for j, jj in JUNCTIONS.items():
        st = cam_state(sc, j, cams, blocked)
        out.append({"id": j, "name": jj["name"], "lat": jj["lat"], "lng": jj["lng"], "count": cams.get(j, 0), "state": st,
                    "note": sc.get("blocked_reason", "") if st == "BLOCKED" else ""})
    return out


# ---------------------------------------------------------------- triage


def triage(report: dict, photo_read: dict | None) -> tuple[str, str, list[str]]:
    reasons: list[str] = []
    sev = "P3"
    if not report.get("conscious", True) or not report.get("breathing", True):
        sev = "P1"; reasons.append("Bystander: " + ("not breathing" if not report.get("breathing", True) else "unconscious"))
    elif report.get("bleeding"):
        sev = "P2"; reasons.append("Bystander: bleeding, conscious")
    else:
        reasons.append("Bystander: conscious, breathing, no bleeding")
    text = (report.get("text") or "").lower()
    if sev == "P3" and any(k in text for k in ("cannot move", "can't move", "leg out", "holding his arm", "holding her arm")):
        sev = "P2"; reasons.append("Bystander text suggests a limb injury")
    if photo_read:
        posture = photo_read.get("patient_posture")
        if posture == "lying_still":
            sev = "P1"; reasons.append("Photo: patient lying still")
        elif posture == "sitting" and sev == "P3":
            sev = "P2"; reasons.append("Photo: patient sitting, not standing")
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


# ---------------------------------------------------------------- decision


def evaluate_routes(sc: dict, cams: dict[str, int], blocked: set[str]) -> list[dict]:
    out = []
    for r in sc["routes"]:
        pen = {j: round(cam_penalty_min(cams.get(j, 0)), 1) for j in r["via"]}
        leg = r["base_min"] + sum(pen.values())
        out.append({**r, "penalties": pen, "leg_min": round(leg, 1), "blocked_at": [j for j in r["via"] if j in blocked],
                    "points": route_points(sc, r), "live_min": route_live_min(sc, r["id"])})
    return out


def air_option(sc: dict, need: str) -> dict | None:
    cands = [(k, h) for k, h in HOSPITALS.items() if h["helipad"] and need in h["specialties"]]
    if not cands:
        return None
    k, h = min(cands, key=lambda kh: haversine_km(sc["lat"], sc["lng"], kh[1]["lat"], kh[1]["lng"]))
    d = haversine_km(sc["lat"], sc["lng"], h["lat"], h["lng"])
    d0 = haversine_km(AIR_BASE["lat"], AIR_BASE["lng"], sc["lat"], sc["lng"])
    d_home = haversine_km(h["lat"], h["lng"], AIR_BASE["lat"], AIR_BASE["lng"])
    to_scene = AIR["liftoff_min"] + d0 / AIR["speed_km_per_min"]
    eta = to_scene + AIR["load_min"] + d / AIR["speed_km_per_min"] + AIR["landing_min"]
    return {"hospital": k, "distance_km": round(d, 1), "base_distance_km": round(d0, 1), "to_scene_min": round(to_scene, 1),
            "eta_min": round(eta, 1),
            "leg_out": [[AIR_BASE["lat"], AIR_BASE["lng"]], [sc["lat"], sc["lng"]]],
            "leg_in": [[sc["lat"], sc["lng"]], [h["lat"], h["lng"]]],
            "leg_home": [[h["lat"], h["lng"]], [AIR_BASE["lat"], AIR_BASE["lng"]]],
            "home_min": round(d_home / AIR["speed_km_per_min"], 1)}


def decide(sc: dict, severity: str, need: str, cams: dict[str, int], blocked: set[str]) -> dict:
    window = WINDOWS[severity]
    routes = evaluate_routes(sc, cams, blocked)
    corridor_ok = severity in ("P1", "P2")
    no_amb = set(sc.get("no_ambulance", []))
    trace: list[str] = [f"Triage: {severity}, needs {need}. Patient must reach hospital within {window} min."]
    cams_txt = ", ".join(f"{JUNCTIONS[j]['name']} {cam_state(sc, j, cams, blocked)}" + (f" ({cams.get(j,0)})" if j not in blocked else "") for j in JUNCTIONS)
    trace.append(f"Cameras: {cams_txt}." + (f" Blocked: {sc['blocked_reason']}." if blocked else ""))
    considered: list[dict] = []
    eligible: list[dict] = []
    for r in routes:
        h = HOSPITALS[r["hospital"]]
        spec_ok = need in h["specialties"]
        amb_ok = r["hospital"] not in no_amb
        r["spec_ok"], r["amb_ok"] = spec_ok, amb_ok
        r["round_trip_min"] = round(2 * r["leg_min"], 1)
        r["corridor_saving"] = round(CORRIDOR_SAVING * len(r["via"]), 1) if corridor_ok else 0.0
        r["eta_min"] = round(r["round_trip_min"] - r["corridor_saving"], 1)   # corridor applies on the return leg
        if r["blocked_at"]:
            reason = f"blocked at {', '.join(JUNCTIONS[j]['name'] for j in r['blocked_at'])}"
        elif not spec_ok:
            reason = f"{h['short']} has no {need}"
        elif not amb_ok:
            reason = f"no ambulance free at {h['short']}"
        elif r["eta_min"] > window:
            reason = f"{r['eta_min']} min, outside {window} min window" + (" even with corridor" if corridor_ok else "")
        else:
            reason = "passes"
        r["passes"] = reason == "passes"
        r["reason"] = reason
        pen_txt = ", ".join(f"{JUNCTIONS[j]['name']} +{p}" for j, p in r["penalties"].items() if p) or "no camera delay"
        live = f" (live now {r['live_min']})" if r["live_min"] is not None else ""
        trace.append(f"Route {r['id']} from {h['short']}: Routes API {r['base_min']} min{live}; {pen_txt} → {r['leg_min']} min each way, {r['round_trip_min']} round trip"
                     + (f", {r['eta_min']} with corridor" if corridor_ok else "") + f". {'Passes' if r['passes'] else 'Rejected: ' + reason}.")
        considered.append({"id": r["id"], "hospital": r["hospital"], "eta_min": r["eta_min"], "passes": r["passes"], "reason": reason})
        if r["passes"]:
            eligible.append(r)
    default = routes[0]
    corridor: list[dict] = []
    air = None
    if eligible:
        best = min(eligible, key=lambda r: r["eta_min"])
        mode, chosen, hospital, eta = "road", best["id"], best["hospital"], best["eta_min"]
        if corridor_ok:
            corridor = corridor_plan(best)
            trace.append(f"Route {best['id']} is the fastest that passes. {severity}: green corridor on the return at {len(best['via'])} junction(s), saves {best['corridor_saving']} min.")
        else:
            trace.append(f"Route {best['id']} is the fastest that passes. {severity}: no corridor needed.")
        reason = f"Ambulance from {HOSPITALS[hospital]['short']} via {best['id']}, back in {eta} min."
    else:
        trace.append(f"No road option gets a {severity} to hospital inside {window} min.")
        air = air_option(sc, need) if severity == "P1" else None
        if air:
            h = HOSPITALS[air["hospital"]]
            trace.append(f"Air: {AIR_BASE['name']} → scene {air['base_distance_km']} km → {h['short']} helipad {air['distance_km']} km: {air['eta_min']} min incl. lift-off, loading, landing. Passes.")
            no_pad = [HOSPITALS[k]["short"] for k in HOSPITALS if need in HOSPITALS[k]["specialties"] and not HOSPITALS[k]["helipad"]]
            if no_pad:
                trace.append(f"{', '.join(no_pad)} {'has' if len(no_pad) == 1 else 'have'} {need} but no helipad.")
            mode, chosen, hospital, eta = "air", "AIR", air["hospital"], air["eta_min"]
            reason = f"Helicopter to {h['short']}, {eta} min. Every road option fails for a P1."
        else:
            usable = [r for r in routes if not r["blocked_at"] and r["spec_ok"] and r["amb_ok"]] or [r for r in routes if not r["blocked_at"]] or routes
            best = min(usable, key=lambda r: r["eta_min"])
            mode, chosen, hospital, eta = "road", best["id"], best["hospital"], best["eta_min"]
            if corridor_ok:
                corridor = corridor_plan(best)
            trace.append(f"{severity} does not justify air. Fastest usable road is {best['id']}; hospital warned of the delay.")
            reason = f"Ambulance from {HOSPITALS[hospital]['short']} via {best['id']}, {eta} min (late, flagged)."
    saved = round(default["eta_min"] - eta, 1)
    trace.append(f"RECOMMEND {mode.upper()} → {HOSPITALS[hospital]['short']}. {saved} min faster than default route A. Awaiting dispatcher confirmation.")
    return {"mode": mode, "chosen": chosen, "hospital": hospital, "eta_min": eta, "window_min": window,
            "default_eta_min": default["eta_min"], "minutes_saved": saved, "reason": reason,
            "routes": routes, "considered": considered, "air": air, "corridor": corridor, "trace": trace,
            "geometry": "routes_api" if ROUTE_CACHE else "straight"}


def corridor_plan(route: dict) -> list[dict]:
    plan, t = [], 2.0
    for j in reversed(route["via"]):  # return leg: hospital-bound, junctions in reverse order
        plan.append({"junction": j, "name": JUNCTIONS[j]["name"], "hold_from_min": round(t, 1), "hold_to_min": round(t + 2.5, 1), "state": "planned"})
        t += 3.5
    return plan


# ---------------------------------------------------------------- vitals


def vitals(severity: str, t_sec: float, phase: str) -> dict:
    base = {"P1": (118, 96, 58, 91, 24), "P2": (98, 118, 76, 96, 18), "P3": (84, 124, 80, 98, 16)}[severity]
    w = math.sin(t_sec / 3.0)
    gain = {"at_scene": 0.1, "to_hospital": 0.3, "arrived": 0.4, "returning": 0.4}.get(phase, 0.0)
    return {"hr": round(base[0] + 3 * w - 14 * gain), "sbp": round(base[1] + 2 * math.cos(t_sec / 4) + 12 * gain),
            "dbp": round(base[2] + w + 6 * gain), "spo2": round(min(99, base[3] + math.cos(t_sec / 5) + 6 * gain)),
            "rr": round(base[4] + w - 4 * gain)}


# ---------------------------------------------------------------- incident


class Incident:
    def __init__(self, scenario_id: str):
        sc = SCENARIOS[scenario_id]
        self.id = uuid.uuid4().hex[:8]
        self.scenario = sc
        self.created_at = time.time()
        self.status = "reported"   # reported → triaged → confirmed → ... → handed_over
        self.report: dict = dict(sc["report"])
        self.photo_read: dict | None = None
        self.photo_file: str | None = None
        self.severity = self.need = None
        self.triage_reasons: list[str] = []
        self.decision: dict | None = None
        self.confirmed_at: float | None = None
        self.cams: dict[str, int] = dict(sc["cams"])
        self.blocked: set[str] = set(sc.get("blocked", []))
        self.reevaluated = False
        self._logged_phases: set[str] = set()
        self.checklist = [{"text": t, "done": False} for t in sc["checklist"]]
        self.timeline: list[dict] = []
        self.agent: dict = {}
        self.log("Bystander report received", sc["location"])

    def log_once(self, key: str, event: str, detail: str = "") -> None:
        """Log an event once per incident; later calls update the detail in place."""
        for e in self.timeline:
            if e.get("key") == key:
                e["detail"] = detail
                return
        self.log(event, detail)
        self.timeline[-1]["key"] = key

    def log(self, event: str, detail: str = "") -> None:
        self.timeline.append({"t": round(time.time() - self.created_at, 1), "event": event, "detail": detail})

    def run_triage(self) -> None:
        self.severity, self.need, self.triage_reasons = triage(self.report, self.photo_read)
        self.decision = decide(self.scenario, self.severity, self.need, self.cams, self.blocked)
        self.status = "triaged"
        self.log(f"Triage agent: {self.severity}, needs {self.need}", "; ".join(self.triage_reasons))
        self.log("Dispatch agent recommendation", self.decision["reason"])

        if not settings.simulation or settings.agent_live:
            self.agent = {"status": "pending"}
            _sid = self.scenario["id"]
            _sev = self.severity
            _need = self.need
            _decision_mode = self.decision["mode"]

            def _run_agent() -> None:
                import app.services.wxo_agent as _wxo  # local import avoids circular deps at startup; call via module so monkeypatching works
                result = _wxo.ask_dispatch_agent(_sid, _sev, _need)
                result["status"] = "done"
                result["agrees"] = result["mode"] == _decision_mode
                self.agent = result

            t = threading.Thread(target=_run_agent, daemon=True)
            t.start()

    def confirm(self, override_road: bool = False) -> None:
        if not self.decision:
            raise ValueError("no decision yet")
        if override_road and self.decision["mode"] == "air":
            usable = [r for r in self.decision["routes"] if not r["blocked_at"] and r["spec_ok"] and r["amb_ok"]] or self.decision["routes"]
            best = min(usable, key=lambda r: r["eta_min"])
            self.decision.update(mode="road", chosen=best["id"], hospital=best["hospital"], eta_min=best["eta_min"],
                                 minutes_saved=round(self.decision["default_eta_min"] - best["eta_min"], 1), corridor=corridor_plan(best))
            self.decision["trace"].append(f"Dispatcher override: road via {best['id']} instead of air.")
        self.confirmed_at = time.time()
        self.status = "confirmed"
        h = HOSPITALS[self.decision["hospital"]]["short"]
        self.log(f"Dispatcher confirmed {self.decision['mode']}", h)
        self.log("Handoff agent: hospital pre-alert sent", f"{h} notified, bay reserved")

    def tick_checklist(self, index: int, done: bool) -> None:
        self.checklist[index]["done"] = done
        if done:
            self.log_once(f"tick-{index}", "Bystander ✓ " + self.checklist[index]["text"])

    def handoff(self) -> None:
        self.status = "handed_over"
        self.log("ER accepted handoff")

    # -- clock
    def progress(self) -> float:
        if not self.confirmed_at:
            return 0.0
        return min(1.0, (time.time() - self.confirmed_at) / DEMO_TRIP_SECONDS)

    def phase(self) -> tuple[str, float]:
        """(phase name, fraction within phase)."""
        p = self.progress()
        if not self.confirmed_at:
            return "awaiting", 0.0
        start = 0.0
        for end, name in PHASES:
            if p <= end:
                return name, (p - start) / (end - start) if end > start else 1.0
            start = end
        return "done", 1.0

    def maybe_reevaluate(self) -> None:
        sc = self.scenario
        if self.reevaluated or "cams_after" not in sc or not self.decision or self.decision["mode"] != "road":
            return
        if self.progress() >= sc.get("reeval_at_progress", 0.35):
            self.cams.update(sc["cams_after"])
            chosen = next(r for r in self.decision["routes"] if r["id"] == self.decision["chosen"])
            fresh = next(r for r in evaluate_routes(sc, self.cams, self.blocked) if r["id"] == chosen["id"])
            old = self.decision["eta_min"]
            new_eta = round(chosen["leg_min"] + fresh["leg_min"] - chosen.get("corridor_saving", 0.0), 1)  # out leg done, return leg re-timed
            self.decision["eta_min"] = new_eta
            self.decision["minutes_saved"] = round(self.decision["default_eta_min"] - new_eta, 1)
            changed = ", ".join(f"{JUNCTIONS[j]['name']} now {c} ({cam_state(sc, j, self.cams, self.blocked)})" for j, c in sc["cams_after"].items())
            self.decision["trace"].append(f"Live re-check on the return leg: {changed}. ETA {old} → {new_eta} min.")
            self.log("Dispatch agent re-evaluated", f"ETA {old} → {new_eta} min as the jam clears")
            self.reevaluated = True

    def state(self) -> dict[str, Any]:
        self.maybe_reevaluate()
        p = self.progress()
        phase, within = self.phase()
        now = time.time()
        if self.confirmed_at and self.status in ("confirmed", "enroute", "arrived") and phase not in self._logged_phases:
            msgs = {"to_scene": ("Vehicle dispatched", ""), "at_scene": ("At scene, patient loaded", ""),
                    "to_hospital": ("Transporting to hospital", ""), "arrived": ("Arrived at hospital", ""), "returning": ("Vehicle returning to base", "")}
            if phase in msgs:
                self.log(*msgs[phase]); self._logged_phases.add(phase)
            if phase in ("to_scene", "at_scene", "to_hospital"):
                self.status = "enroute"
            elif phase in ("arrived", "returning", "done"):
                self.status = "arrived"
        corridor = self.decision["corridor"] if self.decision else []
        for i, c in enumerate(corridor):
            if phase == "to_hospital":
                c["state"] = "green" if within > (i + 0.5) / (len(corridor) + 1) else "holding"
            elif phase in ("arrived", "returning", "done"):
                c["state"] = "released"
            else:
                c["state"] = "planned"
        eta_left = None
        if self.decision and self.confirmed_at:
            trip_frac = {"to_scene": 0.0 + within * 0.45, "at_scene": 0.45 + within * 0.05, "to_hospital": 0.5 + within * 0.5}.get(phase, 1.0 if phase in ("arrived", "returning", "done") else 0.0)
            eta_left = round(self.decision["eta_min"] * (1 - trip_frac), 1)
        return {
            "id": self.id, "scenario": {k: self.scenario[k] for k in ("id", "title", "time", "location", "lat", "lng")},
            "status": self.status, "phase": phase, "phase_within": round(within, 3), "created_at": self.created_at,
            "golden_hour_left_sec": max(0, int(GOLDEN_HOUR_MIN * 60 - (now - self.created_at))),
            "report": self.report, "photo_read": self.photo_read, "photo_file": self.photo_file,
            "severity": self.severity, "need": self.need, "triage_reasons": self.triage_reasons,
            "decision": self.decision, "cams": self.cams,
            "cameras": cameras_view(self.scenario, self.cams, self.blocked),
            "progress": round(p, 3), "eta_left_min": eta_left,
            "vitals": vitals(self.severity, now - self.created_at, phase) if self.severity else None,
            "checklist": self.checklist, "timeline": self.timeline,
            "patient": {"id": "SAL-DEMO-0001", "name": "Ravi Demo", "sex": "M", "age": 34, "blood": "O+"},
            "hospitals": HOSPITALS, "junctions": JUNCTIONS, "air_base": AIR_BASE,
            "candidate_routes": [{"id": r["id"], "hospital": r["hospital"], "base_min": r["base_min"], "points": route_points(self.scenario, r)} for r in self.scenario["routes"]],
            "agent": self.agent,
        }


_active: Incident | None = None


def new_incident(scenario_id: str) -> Incident:
    global _active
    _active = Incident(scenario_id)
    return _active


def active() -> Incident | None:
    return _active
