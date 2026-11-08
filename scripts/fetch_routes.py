"""Fetch real road geometry + live duration for every route and station leg
in data/scenarios.json, and cache them in data/routes_cache.json.

Run once from the repo root with GOOGLE_ROUTES_API_KEY in .env:
    python scripts/fetch_routes.py
Only legs not yet cached are fetched; the key includes the route definition, so a changed route re-fetches on its own.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services import sim  # noqa: E402
from app.services.routes_api import fetch_leg, load_cache, save_cache  # noqa: E402


def main() -> int:
    if not settings.google_routes_api_key:
        print("GOOGLE_ROUTES_API_KEY is empty in .env"); return 1
    force = "--force" in sys.argv
    cache = load_cache()
    calls = 0
    for sid, sc in sim.SCENARIOS.items():
        inc = [sc["lat"], sc["lng"]]
        for r in sc["routes"]:
            key = sim.route_key(sc, r)
            if key in cache and not force:
                continue
            via = [[sim.JUNCTIONS[j]["lat"], sim.JUNCTIONS[j]["lng"]] for j in r["via"]]
            h = sim.HOSPITALS[r["hospital"]]
            leg = fetch_leg(inc, [h["lat"], h["lng"]], via)
            cache[key] = leg; calls += 1
            print(f"{key:14s} {leg['distance_m']/1000:.1f} km  live {leg['duration_s']//60} min  ({len(leg['points'])} pts)")
            time.sleep(0.2)
    save_cache(cache)
    print(f"\n{calls} calls made, {len(cache)} legs cached in data/routes_cache.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
