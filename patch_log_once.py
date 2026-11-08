"""Patch: log 'Scene photo analysed' and each checklist tick once per incident.
Run from the repo root:  python patch_log_once.py
Edits app/services/sim.py, app/routers/api.py and tests/test_flow.py in place.
Safe to run twice."""
from pathlib import Path

root = Path(__file__).resolve().parent
sim, api, test = root / "app/services/sim.py", root / "app/routers/api.py", root / "tests/test_flow.py"

s = sim.read_text(encoding="utf-8")
if "def log_once" not in s:
    s = s.replace(
        "    def log(self, event: str, detail: str = \"\") -> None:",
        "    def log_once(self, key: str, event: str, detail: str = \"\") -> None:\n"
        "        \"\"\"Log an event once per incident; later calls update the detail in place.\"\"\"\n"
        "        for e in self.timeline:\n"
        "            if e.get(\"key\") == key:\n"
        "                e[\"detail\"] = detail\n"
        "                return\n"
        "        self.log(event, detail)\n"
        "        self.timeline[-1][\"key\"] = key\n\n"
        "    def log(self, event: str, detail: str = \"\") -> None:", 1)
s = s.replace(
    'self.log("Bystander ✓ " + self.checklist[index]["text"])',
    'self.log_once(f"tick-{index}", "Bystander ✓ " + self.checklist[index]["text"])')
sim.write_text(s, encoding="utf-8")

a = api.read_text(encoding="utf-8")
n = a.count('inc.log("Scene photo analysed"')
a = a.replace('inc.log("Scene photo analysed"', 'inc.log_once("photo", "Scene photo analysed"')
api.write_text(a, encoding="utf-8")

t = test.read_text(encoding="utf-8")
if "test_photo_and_ticks_log_once" not in t:
    t += '''

def test_photo_and_ticks_log_once():
    c.post("/api/incident/new", json={"scenario": "S2"})
    for _ in range(3):
        c.post("/api/incident/photo_sim")
    for d in (True, False, True):
        c.post("/api/incident/checklist", json={"index": 0, "done": d})
    tl = c.get("/api/incident/state").json()["timeline"]
    assert sum(e["event"] == "Scene photo analysed" for e in tl) == 1
    assert sum(e["event"].startswith("Bystander \\u2713 Do not move") for e in tl) == 1
'''
    test.write_text(t, encoding="utf-8")

print(f"sim.py: log_once {'present' if 'def log_once' in s else 'MISSING'}; api.py: {n} photo log calls patched; test added")
