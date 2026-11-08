# SaveAlife BLR — Agentic Emergency Dispatch for Bengaluru

IBM Bobathon: Build for Bengaluru 2026 — Theme 1, Smarter Streets Better Living

A bystander reports a road accident on a phone. SaveAlife BLR reads six traffic cameras and the live road network, decides which hospital's ambulance should go — or whether the patient is critical enough and the roads bad enough that only the helicopter will make it — explains every rejected option in one line, and puts the decision in front of a human dispatcher to confirm. The hospital is pre-alerted before the vehicle moves. The ER watches vitals and a timeline from the moment of the report.

Deployed prototype: https://savealife-blr.2gwnl9m982ir.us-south.codeengine.appdomain.cloud (IBM Cloud Code Engine; open it and click a scenario)

Demo video: <VIDEO_URL>

## The doctrine

**The rule owns the decision. Cameras and the road network own the ground. The agent owns the explanation. The dispatcher owns the button.**

Every layer follows this split:

- A **deterministic rule** decides what is rejected and what is taken: a route through a blocked junction, a hospital without the specialty, a hospital with no free ambulance, an ETA outside the patient's window. No model can send a P3 patient a helicopter or dispatch anything without a human click.
- **Ground truth is data, not opinion**: six fixed cameras with a count and a state, real road geometry and live times from the Routes API, six real hospitals with their specialties and helipads. Every number in a recommendation traces to one of those.
- **Models reason on top**: a vision model reads the bystander's scene photo for posture and traffic; Granite classifies the report text; a watsonx Orchestrate agent is given the same five tools and the same rule and asked to reach its own recommendation. Its answer is shown beside the rule's, with an *agrees / differs* chip. In all five scenarios it agrees. If it ever differed, the rule would still be what Confirm executes.

## What happens, end to end

**Report** — the bystander's phone shows a prefilled form: where, what happened, how many hurt, awake / breathing / bleeding. One tap adds a scene photo. The photo is analysed on the server and never shown to the hospital; only the structured read (lying still / sitting / standing, traffic density, vehicles) goes forward.

**Triage** — unconscious or not breathing is P1; bleeding or a limb injury is P2; otherwise P3. The photo can only raise severity. Severity sets the clock: a P1 must be at hospital in 25 minutes, a P2 in 45, a P3 in 90. The mechanism sets the need: neuro, trauma, ortho or general.

**Cameras** — six fixed junctions: Madiwala, Agara, Sarjapur Jn, Bommanahalli, Koramangala Sony World, HSR BDA. Each reports LOW (under 80 vehicles), HIGH (80–250, adds delay in proportion to the count) or BLOCKED (lane closed or stalled — any route through it is rejected outright, not slowed). The dispatch screen shows a looping clip per state so the dispatcher sees what the number means.

**Routes** — three candidates per scenario, each to a named hospital, drawn on real road geometry with a base time from the Google Routes API and the live time beside it. The ambulance leaves *from* the chosen hospital and returns *to* it with the patient, so the ETA is the round trip. For P1 and P2 a green corridor on the return leg saves 1.5 minutes per junction.

**Decide** — reject the blocked, the wrong-specialty and the no-ambulance routes; take the fastest of the rest that lands inside the window. If nothing passes and the patient is P1, propose the helicopter: HAL Airport to the scene, scene to the nearest helipad hospital with the specialty. If nothing passes and the patient is P2 or P3, take the fastest usable road and flag the delay to the hospital. In parallel, the Orchestrate agent calls the five tools and writes its own recommendation.

**Confirm** — the dispatcher sees both reasoning panels, every rejected route with its reason, the camera strip, and a Confirm button. Air can be overridden to road. Nothing moves before the click.

**Move** — an eight-step sequence the dispatcher and the ER both watch: incident pulses, chosen hospital highlights, chosen route highlights, vehicle leaves the hospital, loads at the scene, returns with corridor junctions turning green one by one, arrives, returns to base. In one scenario the cameras clear mid-trip and the agent re-checks; the trace and the ER's expected arrival both update.

**Hand off** — the ER screen has had the patient since the report: severity, vitals and ECG, every bystander checklist tick on the timeline, an intake form prefilled by the handoff step. Accept Handoff closes the loop.

## The five scenarios

Each changes one or two things and holds the rest fixed, so a judge can see exactly what moved the decision. Five scenarios end at four different hospitals.

**S1 — one route blocked.** Silk Board, 18:30, a man sitting on the kerb holding his arm. P2, ortho. The shortest route to St John's runs through Madiwala, where a stalled truck sits across the lanes: rejected outright. The other St John's route is fine but St John's has no ambulance free. Fortis via Bommanahalli passes. Road from Fortis, corridor on the return. A distance-only dispatcher sends the ambulance into the blockage.

**S2 — all roads fail, critical.** Outer Ring Road near Agara Lake, 18:45, a man lying on the road, not moving, head injury. P1, neuro. Agara is blocked by the crash itself; the other two routes are 60 and 67 minutes round trip against a 25-minute window, even with a corridor. Every road option fails and the patient is critical, so: helicopter, HAL to the scene in six minutes, then to St John's helipad, 14.7 minutes in all. NIMHANS has neuro but no helipad, and the trace says so.

**S3 — same crash, minor.** Identical cameras, identical blocked junction, identical route timings for A and B. The man is standing, talking, holding one hand. P3, general, 90-minute window. Road from Apollo, no corridor, no helicopter. This pair is the whole argument: the agent is reasoning about the patient, not the traffic. A P3 does not get a helicopter however bad the jam is.

**S4 — clear roads, critical.** Hosur Road at 06:10, every camera LOW, a rider on his side not responding. P1, neuro. Fortis is rejected (no neuro), St John's is rejected (no ambulance free), NIMHANS — the neuro hospital — sends its ambulance with a green corridor on the return, because a P1 gets every minute the city can give even when the roads are empty.

**S5 — the jam clears mid-trip.** Sarjapur Road at 17:50, four cameras HIGH, a rider against the divider who cannot move his leg. P2, ortho. Both St John's routes are out (no ambulance free), leaving Manipal via Sarjapur Jn at 43.8 minutes against a 45-minute window — it passes only because of the corridor. On the return leg two cameras drop from HIGH to LOW; the agent re-evaluates, the trace shows the ETA falling, the timeline logs it. The decision is live, not one-shot.

## The agent — an honest story

The dispatch agent runs in watsonx Orchestrate as a native agent, `savealife_dispatch`, with five OpenAPI tools served by this application from Code Engine: `get_incident`, `get_cameras`, `get_routes`, `get_hospitals`, `get_air_option`. Its instructions are the rule above, written out. `scripts/wxo_test_agent.py` drives all five scenarios through the live instance and asserts the recommendation; it reports 5/5, about ten seconds each.

It was supposed to run on Granite. Granite 4 H Small, Orchestrate's `react` style: every run returned Orchestrate's generic "I did not understand" in six seconds, 39 completion tokens, empty step history — the model never emitted a parseable tool call. `react_core`: same. `default` style (native function calling): "LLM has responded with empty message." `orchestrate models list` then showed that the instance's recommended agent models are gpt-oss-120b, Claude Sonnet and Gemma, and Granite is hidden as not recommended for agents. The agent was switched to gpt-oss-120b — Orchestrate's own default, and what IBM's stock agents in the same instance use — and passed 5/5 on the first run. The diagnostic that found this (`scripts/wxo_diag.py`) is in the repo. Granite still does the triage text and, with Llama 4 Maverick, the scene photo, on watsonx.ai.

## IBM services used

watsonx Orchestrate (native agent, OpenAPI tools, runs API) · watsonx.ai (Granite 4 H Small, Llama 4 Maverick vision, Essentials plan) · IBM Cloud Code Engine (build from source, public endpoint) · IBM Cloud IAM · IBM Bob 2.0 (four build tasks, sessions exported)

Outside IBM: Google Routes API for road geometry and live times (fetched once, cached), OpenStreetMap tiles, Leaflet.

## Bob as the builder

The screens and the simulation engine were hand-built and tested first so that Bob had a stable codebase to extend. Bob then built the entire IBM-platform layer in four tasks, each a single written spec pasted once, each ending with the full test suite green. Receipts are in `bob_sessions/`, one export per task.

1. **Deploy** — Dockerfile, `.dockerignore`, Code Engine deploy script, README section. 19 tests.
2. **Tools** — five stateless endpoints keyed by scenario, with LLM-facing descriptions that the agent used correctly first time; the OpenAPI exporter and import script; 29 new tests. 48 tests.
3. **Agent** — the agent YAML with the rule as instructions, the import script, the five-scenario harness against the Orchestrate REST API; a follow-up corrected the chat endpoint to runs → poll → thread messages. 48 tests, agent 5/5.
4. **Wiring** — the agent called in a background thread on every report, the rule kept as ground truth, both shown on the dispatch screen with the agrees/differs chip. Bob noticed that its own local import inside the thread would defeat the test's monkeypatch and fixed it before reporting. 50 tests.

Debugging and design happened outside Bob so each session is a clean record of what Bob did. Bobcoins used: <N> of 50.

## What is simulated, what is real

Real: road geometry and live times for every route; hospitals, specialties, helipads and junction locations; the agent, the tools, the deployment and the human-confirm gate; the token and compute costs.

Simulated, and labelled so on screen: camera counts and states and the six camera clips; the patient, vitals, ECG and the twenty-five scene photos (illustrations — no faces, number plates or wounds); which hospitals have an ambulance free in each scenario; vehicle movement on a sixty-second clock. No real person appears anywhere; no government ID, health record or children's data is used.

## Impact

Minutes saved from report to hospital arrival, against dispatching on the default shortest route, computed per incident and shown on the dispatch screen as the sequence runs. S1 13.6, S2 57.5, S3 5.2, S4 0, S5 3.0. These are scenario-modelled comparisons on synthetic traffic, not measured savings; in S1–S3 the default route is blocked, so the baseline is the time a distance-only dispatcher would have committed to before discovering it. Read it as: in three of five scenarios the default dispatch would not have arrived at all, and in S2 no road option could get a P1 patient to a neuro hospital inside the window.

One decision costs about 1,600 tokens on the agent and under 1,000 on watsonx.ai — a fifth of a US cent. A day of testing used 0.2 GB-hours on Code Engine. The IBM Cloud credit shows $0.00 consumed.

## Repository map

```
app/            FastAPI: incident flow, tool endpoints (Bob 2), simulation engine,
                watsonx.ai client, Orchestrate client (Bob 4), the three screens
data/           scenarios.json (hospitals, junctions, five scenarios), routes_cache.json
orchestrate/    tools_openapi.json (Bob 2), dispatch_agent.yaml (Bob 3)
scripts/        preflight, fetch_routes, Orchestrate import/test/diag, deploy (Bob 1)
tests/          50-test pytest suite: every scenario's decision, S2/S3 contrast,
                override, S5 re-evaluation, phases, tools, agent wiring
bob_sessions/   exported Bob sessions, one per task
docs/           submission document
```

## Run it

```
python -m venv .venv ; .venv\Scripts\activate ; pip install -r requirements.txt
copy .env.example .env           # SIMULATION=true needs no keys
uvicorn app.main:app --reload    # http://127.0.0.1:8000/
pytest -q                        # 50 tests
```

With keys: `python scripts\preflight.py` checks every service; `python scripts\fetch_routes.py` pulls real road geometry; `AGENT_LIVE=true` turns on the Orchestrate panel. Full redeploy: `ibmcloud ce app update --name savealife-blr --build-source .` from a logged-in CLI, five to eight minutes.

Built solo by Mrinal Desai, 7–8 November 2026, for the IBM Bobathon: Build for Bengaluru. Everything in this repository was written during the hackathon window; the commit history shows the timeline.
