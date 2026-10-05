# NetHealers: self-healing 5G network agent

Simulation project for the ITU AI for Good Build-a-thon 5.0. An agent watches a 5G street, spots phones whose signal dropped, works out why, rehearses fixes on a virtual copy of the street (the digital twin), applies the safest one, checks the result and undoes it if it fell short.

## Status

| Step | What | State |
|---|---|---|
| 1 | Signal world: 3D street, signal maths, problems, fixes, twin | Done |
| 2 | Dataset and diagnosis model (with LWM) | Done |
| 3a | Agent core: monitor, twin rehearsal, rule-checker, act, verify, undo, withdraw | Done |
| 3b | Six test scenarios, five methods, evaluation report | Done |
| 3c | Language-model roles, document library, decision log in Postgres | Done (live model test needs a key) |
| 3d | Backend API for the game (sessions, controls, live WebSocket) | Done |
| 4 | 3D game with live agent panel | Planned |

## Setup

Needs [uv](https://docs.astral.sh/uv/). Python 3.12 is installed automatically.

```bash
uv sync
uv run pytest                       # 24 tests, under a second
uv run python scripts/step1_demo.py # narrated demo, pictures in out/
uv run python scripts/make_dataset.py    # ~12 min on half the cores: data/train.parquet, data/station_road.parquet
uv run python scripts/train_diagnosis.py # ~1.5 min: models/diagnosis.joblib, out/diagnosis_report.md
uv run python scripts/run_scenarios.py   # ~2 min: docs/evaluation_report.md, docs/eval_timeline.png
docker compose up -d                     # Postgres + pgvector on port 5435 (decision log, library)
uv run python scripts/build_library.py   # download the rule documents, build the searchable library
uv run python scripts/demo_agent.py      # watch the agent handle the bus, step by step
uv run python scripts/serve.py           # game backend on http://localhost:8010 (docs at /docs)
```

To switch on the language-model roles, copy `.env.example` to `.env` and add an OpenRouter key (free models). Without a key everything still runs on plain rules.

The LWM weights (2.5 MB, MIT licence) download automatically into `models/lwm/` on first use.

If `import nethealers` fails on macOS, the editable-install `.pth` file has been marked hidden (Python 3.12 skips hidden `.pth` files, and it can happen again after `uv sync`). Fix with `chflags nohidden .venv/lib/python3.12/site-packages/*.pth`. The scripts and tests add `src` to the path themselves, so they work either way.

## How the signal maths works (`src/nethealers/sim`)

The street is a set of axis-aligned 3D boxes. For every tower and phone the simulator finds:

- **Direct path**: the straight line, if no building is in the way. A bus, crowd or kiosk on the line subtracts its loss (bus 25 dB, crowd 20 dB, and so on).
- **Reflected paths**: one mirror bounce off any building wall, if both legs are clear. Glass loses 4 dB, concrete 7 dB, brick 9 dB.
- **Scatter path**: a weak floor based on the 3GPP NLOS formula, so values stay finite where no clean path exists.

Path loss follows 3GPP TR 38.901 (UMi street canyon, 28 GHz). Tower antennas use the TR 38.901 element pattern in an 8 x 8 panel with 16 beams and electrical tilt, so tilt changes really move coverage. Each one-second tick then runs:

1. Phones report signal strength per beam (noisy and rounded in the real world).
2. Built-in handover (A3 event, 3 dB offset, 2-tick trigger) and built-in beam management react.
3. Clarity (SINR) counts interference from other towers, weighted by how busy they are and where their beams point, plus any outside interferer.
4. Each tower shares its airtime between its phones, giving data rates and tower load (above 1 means overloaded).

| File | Contents |
|---|---|
| `config.py` | All radio numbers in one place, with sources |
| `geometry.py` | Boxes, line-of-sight tests, walls |
| `channel.py` | Path finding, path loss, antenna gain, received power |
| `world.py` | Towers, phones, the tick loop, the twin |
| `problems.py` | Buttons that break things, each tagged with its true cause |
| `actions.py` | The five fixes, with physical limits and exact undo |
| `layouts.py` | Station Road demo street and a random city generator |
| `viz.py` | Top-down and 3D pictures for checking |

### Problems (true causes)

| Label | Ways to cause it |
|---|---|
| blockage | `add_blocker(world, "bus" / "truck" / "crowd" / "kiosk" / "hoarding", x, y)` |
| wrong_beam | `stick_beams(world, phone_ids, offset)` |
| interference | `misconfigure_tower(world, tower, +dB, tilt)`, `add_external_interferer(world, x, y)` (not fixable by settings) |
| congestion | `crowd_surge(world, x, y, radius, n_people)` |

`world.missing_relations = {(a, b)}` removes a neighbour link, so built-in handover can't rescue phones. That's how coverage holes persist.

### Fixes

`BeamOverride`, `Handover`, `PowerChange`, `TiltChange`, `LoadRebalance`, applied with `apply_action` and reversed exactly with `undo_action`. Only physical limits live here; policy limits (cooldowns, step sizes, protected zones) belong to the rule-checker in Step 3.

### Real world vs twin

`world.twin()` returns the agent's copy: same building map and network settings, but without hidden objects, hidden wall changes, outside interferers, moving blockers, shadowing or measurement noise. `world.twin(include_dynamic=True)` adds the blockers, standing in for a twin that has been told where the bus is.

## Diagnosis model (`src/nethealers/diagnosis`)

Names the cause of each phone's trouble (none, blockage, wrong beam, interference, congestion) with a calibrated confidence.

**Dataset** (`dataset.py`). Each episode builds a random grid city or a random long street, sometimes removes neighbour links, runs normal ticks, adds one random problem, then runs 1-3 more ticks next to a copy of the world without the problem. A phone gets the problem's label only if the problem really hurt it compared with that copy (clarity 3 dB worse, or lost data). A crowd hurts two ways: phones on the overloaded tower are labelled congestion, phones on neighbouring towers (hurt by its extra transmissions) are labelled interference. Station Road is never used for training; it's a separate test.

**Inputs** (`features.py`). Only what a network can observe: per-beam and per-tower strength reports, clarity, quality, data rate vs demand, tower load and phone counts, handovers, and neighbourhood context (how many nearby phones and same-tower phones also dropped). Every input compares now with just before.

**LWM** (`lwm.py`). The simulator's paths become the 32-antenna x 32-subcarrier channel LWM expects (DeepMIMO formula), LWM returns a 64-number fingerprint, and the model gets the fingerprint now and how it changed.

**Model** (`train.py`). scikit-learn gradient-boosted trees, class-balanced, then isotonic calibration so "90% sure" means right about 90% of the time. The agent uses the plain + LWM version.

| Version | Unseen cities and streets | Station Road (never trained on) |
|---|---|---|
| Plain inputs | 94.5% accuracy, macro F1 0.927 | 89.6%, F1 0.873 |
| **Plain + LWM (used)** | **95.1%, F1 0.936** | **90.2%, F1 0.882** |
| LWM fingerprint only | 60.3%, F1 0.316 | 54.6%, F1 0.289 |

When the model is at least 90% sure (about 81% of unseen-city cases), it is right 99.3% of the time. LWM alone can't tell interference or congestion apart, because neither changes the shape of a phone's own channel; combined with the plain inputs it adds a small, consistent gain. Full report: [docs/diagnosis_report.md](docs/diagnosis_report.md).

```python
from nethealers.diagnosis import Diagnoser
d = Diagnoser.load()
report = d.diagnose(world, base_frames, base_result)  # cause, confidence and probabilities per phone
```

## The agent (`src/nethealers/agent`)

Call `agent.on_tick()` after every `world.step()`. Each incident moves through: detect, diagnose, rehearse on the twin, safety check, act, verify after 3 s, then keep, undo and try the next fix, ask a person, or withdraw the temporary fix once the cause has gone. Every step is an `Event` with a plain-language sentence (this is what the game's side panel will show).

| File | Job |
|---|---|
| `monitor.py` | Flags phones whose reported clarity drops 4 dB below their own normal (and below 13 dB) or that lose data, for 2 ticks in a row. Ignores phones with stale reports. Groups them into incidents; nearby newcomers join an open incident. |
| `twin.py` | Builds the twin from the map and settings, calibrates it against pre-incident phone reports, then adds a hypothesis: extra loss on links that got much weaker (a blocker), extra interference where clarity is worse than the twin can explain. Keeps a running error per tower. |
| `planner.py` | Lists fixes worth trying for the diagnosed cause (including smaller partial moves and "go back to planned settings"), rehearses each on the twin for 3 ticks, and ranks them by gain minus harm. Exact numbers come from this search, not from a language model. |
| `rules.py` | Plain-code rule-checker with the final say: step sizes, drift from planned settings, legal power limits, cooldowns, predicted harm, protected zones (with a safety margin and a hold after any breach), and autonomy (act alone, small steps only, or ask a person). |
| `agent.py` | The loop. Reads settings back after every change, so a tower that silently ignores commands is caught and escalated. Checks protected zones every tick after a move and undoes at once if one goes over. |
| `config/policy.yaml` | The operator's policy. The agent can never loosen it. |

## Language-model roles, library and decision log

- **Planner and safety adviser** (`agent/roles.py`). After the twin and the rule-checker have narrowed things down to safe options, the planner picks one and explains why in plain words, following the operator's intents (`config/intents.yaml`). The safety adviser reviews it with passages from the document library and may object once; the planner then picks again, and a second objection goes to a person. Neither can invent a fix, change a number or loosen a rule: an answer that isn't one of the listed options is ignored.
- **Fallback chain** (`llm/client.py`). Any OpenAI-compatible API: OpenRouter free models (with OpenRouter's own model fallback), then Groq, Gemini, a local Ollama model, then plain rules. Answers are cached on disk, so replaying a demo is free.
- **Document library** (`kb/library.py`, `config/kb_sources.yaml`). The Telecommunications Act 2023, the DPDP Act 2023, TRAI's 2023 AI and big data recommendations, NITI Aayog's Responsible AI principles and the operator's own policy: 797 passages with page numbers, embedded locally (all-MiniLM-L6-v2) and stored in Postgres with pgvector (or a local file without Postgres). Passages are evidence to cite; they can't change permissions. This stands in for the ITU AI for Good Sandbox knowledge base until access is granted.
- **Decision log** (`agent/events.py`). Every event goes to Postgres (`runs`, `events` tables) when the database is running.

## Game backend (`src/nethealers/api`)

A session is one street with its clock running in the background (1 tick per second by default, up to 10), the agent, and the player as the operator who answers approval requests. Player actions go through a lock so they never land mid-tick; while the agent thinks, the street waits.

| Endpoint | Does |
|---|---|
| `POST /sessions` | Start a game on Station Road (agent on, language model on if a key is set) |
| `GET /sessions/{id}/scene` | Buildings, protected zones, beam angles: build the 3D view once |
| `GET /sessions/{id}/state` | Phones (position, tower, beam direction, clarity band, data rate), towers, blockers, incidents, score |
| `POST /sessions/{id}/problems` | Drop a bus, truck, car, crowd, kiosk, hoarding, stuck beam, misconfigured tower, booster or crowd surge |
| `DELETE /sessions/{id}/problems/{pid}` | Remove it |
| `POST /sessions/{id}/control` | Pause, resume, step one tick, set speed |
| `POST /sessions/{id}/answer` | Approve or reject a fix the agent asked about |
| `GET /sessions/{id}/events` | The agent's full log |
| `WS /sessions/{id}/live` | One frame per tick with that tick's events: what the side panel shows |

## Evaluation (`src/nethealers/eval`, `docs/evaluation_report.md`)

Six scenarios on Station Road (normal day, moving bus, wrong beam, twin mismatch, hospital-zone conflict, faulty and stale data), five methods (no action, network alone, simple rule fixer, agent without twin, full agent), 8 seeds each, scored against the simulator's hidden truth. Degraded phone-seconds, during the problem + after it ends (lower is better):

| Scenario | Network alone | Rule fixer | Full agent |
|---|---|---|---|
| Normal day | 0 | 0 | 0 (no false alarms, no changes) |
| Moving bus | 221 + 19 | 76 + 91 | **98 + 22** |
| Wrong beam | 418 | 131 | **34** |
| Twin mismatch | 326 | 121 + 78 | **98 + 16** |
| Hospital-zone conflict | 326 | 82 + 87, **24 zone breaches** | 237 + 0, **0 breaches** |
| Faulty and stale data | 754 | 734 | **568** |

The agent made 1-4 changes per run where the rule fixer made about 26, broke no limits in any run, and named the right cause in 88-100% of incidents. The rule fixer is faster during a blockage but never withdraws its moves and breaks the hospital limit; the agent is slower and more careful.

![timeline](docs/eval_timeline.png)

## Simplifications to state honestly

- No diffraction around corners; the scatter floor stands in for it.
- One reflection per path, no ground bounce, paths add as power (no phase).
- Buildings are axis-aligned boxes.
- Diagnosis labels come from the simulator, so accuracy here says how well the model reads *this* simulator, not a real network.
- Future work: validate against Sionna RT ray tracing.
