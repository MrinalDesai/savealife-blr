"""Google Routes API: real road geometry and live duration for a leg.

Results are cached in data/routes_cache.json so the demo runs offline after
one fetch (scripts/fetch_routes.py). Nothing here is called at request time
unless the cache is missing and a key is present.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.config import settings

CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "routes_cache.json"
_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def decode_polyline(enc: str) -> list[list[float]]:
    """Decode a Google encoded polyline into [[lat, lng], ...]."""
    pts, idx, lat, lng = [], 0, 0, 0
    while idx < len(enc):
        for is_lng in (False, True):
            shift = result = 0
            while True:
                b = ord(enc[idx]) - 63
                idx += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            d = ~(result >> 1) if result & 1 else result >> 1
            if is_lng:
                lng += d
            else:
                lat += d
        pts.append([lat / 1e5, lng / 1e5])
    return pts


def fetch_leg(origin: list[float], dest: list[float], via: list[list[float]] | None = None) -> dict:
    """One Routes API call. Returns {points, duration_s, distance_m}."""
    body = {
        "origin": {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}},
        "destination": {"location": {"latLng": {"latitude": dest[0], "longitude": dest[1]}}},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
    }
    if via:
        body["intermediates"] = [{"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}, "via": True} for p in via]
    r = httpx.post(
        _URL, json=body, timeout=30,
        headers={"X-Goog-Api-Key": settings.google_routes_api_key,
                 "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline"},
    )
    r.raise_for_status()
    route = r.json()["routes"][0]
    return {
        "points": decode_polyline(route["polyline"]["encodedPolyline"]),
        "duration_s": int(route["duration"].rstrip("s")),
        "distance_m": route["distanceMeters"],
    }


def load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
