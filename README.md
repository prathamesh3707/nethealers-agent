# NetHealers: self-healing 5G network agent

Simulation project for the ITU AI for Good Build-a-thon 5.0. An agent watches a 5G street, spots phones whose signal dropped, works out why, rehearses fixes on a virtual copy of the street (the digital twin), applies the safest one, checks the result and undoes it if it fell short.

## Setup

Needs [uv](https://docs.astral.sh/uv/). Python 3.12 is installed automatically.

```bash
uv sync
uv run pytest                       # 91 tests, about 30 s once the model is trained
uv run python scripts/step1_demo.py # narrated demo, pictures in out/
uv run python scripts/make_dataset.py    # ~12 min on half the cores: data/train.parquet, data/station_road.parquet
uv run python scripts/train_diagnosis.py # ~1.5 min: models/diagnosis.joblib, out/diagnosis_report.md
uv run python scripts/run_scenarios.py   # ~2 min: docs/evaluation_report.md, docs/eval_timeline.png
docker compose up -d                     # Postgres + pgvector on port 5435 (decision log, library)
uv run python scripts/build_library.py   # download the rule documents, build the searchable library
uv run python scripts/demo_agent.py      # watch the agent handle the bus, step by step
uv run python scripts/serve.py           # game backend on http://localhost:8010 (docs at /docs)
```

### Play the game

Needs Node.js 20+ once, for the browser part. One command starts everything and checks it is healthy:

```bash
scripts/start.sh          # one server: http://localhost:8010
scripts/start.sh --dev    # backend :8010 + game dev server http://localhost:5173
```

Or by hand:

```bash
uv run python scripts/serve.py      # terminal 1: backend on :8010
cd web && npm install && npm run dev # terminal 2: game on http://localhost:5173
```

For a demo with one server: `cd web && npm run build`, then `scripts/serve.py` also serves the game at http://localhost:8010.

To switch on the language-model roles and the policy adviser, copy `.env.example` to `.env` and add an OpenRouter key (free models) or an OpenAI key (`LLM_PROVIDERS=openai`). Without a key everything still runs on plain rules.

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
- **Document library** (`kb/library.py`, `config/kb_sources.yaml`). The Telecommunications Act 2023, the DPDP Act 2023, TRAI's 2023 AI and big data recommendations, NITI Aayog's Responsible AI principles and the operator's own policy, plus ITU-T standards and global and regional examples (14 documents, 2,960 passages; see below) with page numbers, embedded locally (all-MiniLM-L6-v2) and stored in Postgres with pgvector (or a local file without Postgres). Passages are evidence to cite; they can't change permissions. This stands in for the ITU AI for Good Sandbox knowledge base until access is granted.
- **Decision log** (`agent/events.py`). Every event goes to Postgres (`runs`, `events` tables) when the database is running.

## Knowledge base and gap analysis (`src/nethealers/kb`, `docs/gap_analysis.md`)

**Knowledge base** (`config/kb_sources.yaml`): 14 documents, about 2,960 passages with page numbers, each tagged with a scope.

| Scope | Documents | Used by |
|---|---|---|
| national (India) | Telecommunications Act 2023, Digital Personal Data Protection Act 2023, TRAI AI and big data recommendations 2023, NITI Aayog Responsible AI 2021 | agent, gap analysis |
| operator | `config/policy.yaml`, `config/intents.yaml` | agent, gap analysis |
| standard | ITU-T Y.3172, Y.3181, Y.3090 | agent, gap analysis |
| global | EU AI Act (Parliament text, March 2024), NIST AI RMF 1.0, Singapore Model AI Governance Framework | gap analysis only |
| regional | Sri Lanka PDPA 2022, Bangladesh Telecommunication Act 2001, Nepal Telecommunications Act 1997 | gap analysis only |

The network agent's safety adviser only cites national, operator and standard passages. `docs/kb_report.md` lists every document with its link and the SHA-256 of the downloaded file, and the retrieval test (`config/kb_eval.yaml`, 26 questions with known answers): right document in the top 3 for 92% of questions over all documents, 100% within the document's scope (how the agents search), mean reciprocal rank 0.86.

**Gap analysis** (`config/gap_topics.yaml`, `scripts/gap_analysis.py`): ten questions an autonomous network agent runs into (accountability, human oversight, emergency priority, personal data in telemetry, sandbox testing, audit logging, standards adoption, cross-border coordination, AI security, energy), each linked to where our agent meets it in the simulation. For each, the analyst searches with the question and with phrasings in the documents' own legal language, gathers what India's documents, the standards, each global example and each neighbouring country say, and a language model names the gaps in ten categories (responsibility, legal coverage, standards, implementation, coordination, conflicting objectives, data, evaluation, auditability, cross-border) using only those passages. Citations to passages it was not given are removed, and the country of each example comes from the document records. Without a model it falls back to retrieval only. Results: `docs/gap_analysis.md` and the **⚖ Policy** screen in the game, where every citation opens its source passage.

```bash
uv run python scripts/build_library.py   # download and index the documents (a few minutes)
uv run python scripts/eval_library.py    # retrieval test -> docs/kb_report.md
uv run python scripts/gap_analysis.py    # gap analysis -> docs/gap_analysis.md (uses the model in .env)
```

API: `GET /kb` (documents and retrieval scores), `GET /kb/search?q=&scope=`, `GET /gaps`, `POST /adviser`, `GET /alignment`.

**Policy adviser** (`kb/adviser.py`, `POST /adviser`): anyone can ask a question, optionally about the incident on screen ("Can the agent move users onto the hospital tower?"). It answers only from the knowledge base and labels every passage by its weight: binding Indian law, a regulator's recommendation, guidance, a technical standard, the operator's policy, or a foreign example that does not apply in India. The verdict is allowed, conditional, not allowed or *not established*. Invented citations are removed; an answer that rests only on foreign examples becomes "not established". It only advises: it has no way to change the network. Every question and answer goes into the incident's audit log.

**ITU alignment** (`config/itu_alignment.yaml`, `GET /alignment`): the agent mapped node by node to the ITU-T Y.3172 ML pipeline (source, collector, preprocessor, model, policy, distributor, sink, orchestrator, intent, sandbox), the five Y.3173 dimensions (who does each: human, human and system, or system; no overall level is claimed), the six dimensions of ITU's AI Ready framework, and a policy-to-control trace: from a pinned passage of the law or a standard, to who is responsible, the control in our code, the test and the evidence. A mapping for discussion, not a claim of conformance.

**Sandbox day** (`docs/sandbox_day.md`): `scripts/export_passages.py` writes the knowledge base to JSONL with stable ids and a manifest, ready for ITU's reference code; `KB_BACKEND=remote` with `KB_REMOTE_URL` sends searches to the Sandbox and falls back to the local index if it fails.

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
| `GET /sessions/{id}/incidents/{iid}/report` | Download one incident for audit: version stamps (commit, model and policy SHA-256, seed), diagnosis, every fix with predicted vs measured result, approvals, adviser questions, who knew what, full timeline |
| `GET /sessions/{id}/incidents/{iid}/roles` | Who knew what, when: the incident by institutional role |
| `POST /adviser` | Ask the policy adviser (optionally about an incident) |
| `WS /sessions/{id}/live` | One frame per tick with that tick's events: what the side panel shows |

## The game (`web/`)

Vite + React + TypeScript, Three.js through React Three Fiber, Zustand, Tailwind. It talks to the backend only through the API above; in development Vite forwards `/sessions` (HTTP and WebSocket), `/kb`, `/gaps`, `/adviser` and `/alignment` to port 8010.

- **3D street** (`src/scene/Street.tsx`): buildings by material (the Glass office is see-through), the protected hospital zone (turns red when its tower goes over the limit), towers with their coverage sector and live power, tilt and load (amber when the agent has changed them), phones coloured by clarity with a line to their tower, and blockers that glide between ticks. Phones the agent is working on get a pulsing ring. Drag to orbit, scroll to zoom, hover a phone for its numbers.
- **Toolbar** (`src/ui/Toolbar.tsx`): pick a problem, click the street. Buses and trucks drive in, wait 30 s and leave (or "drive off" now). Four quick scenarios: bus at the bus stop, stuck beams, Tower C misconfigured, crowd surge.
- **Vehicles** (`src/scene/Vehicles.tsx`): buses, trucks and cars are low-poly models built from simple shapes, drawn at exactly the size the simulator uses for their signal blockage, facing the way traffic flows in their lane (left-hand driving), with wheels that turn as they move. While a vehicle tool is picked, a see-through preview follows the mouse, already slid to where it will park.
- **Buildings and hoardings** (`src/scene/Buildings.tsx`, `Hoarding.tsx`, `facades.ts`): facades painted on canvases sized to each wall (windows, some lit; shopfronts with awnings and signboards on the shop row and market; a curtain wall on the glass office; a red cross and helipad on the hospital; a lit sign band on the mall), rooftop parapets, water tanks and AC units, billboards on steel legs with an advert on both sides, and crowds drawn as people (`src/scene/People.tsx`) in plain greys, since on this street a colour always means a phone's signal and a crowd is only an obstacle. Every solid shape keeps the simulator's exact box, so signal paths still match what you see.
- **No overlaps** (`src/nethealers/sim/space.py`, enforced by the server): a vehicle dropped on another slides along the lane to the nearest free spot (1 m apart), a moved vehicle stops short of the one in front, a driving vehicle queues behind a parked one (and turns off the street after 20 s stuck), and crowds, kiosks and hoardings are refused on top of vehicles or inside buildings.
- **Agent panel** (`src/ui/AgentPanel.tsx`): approval cards (Approve / Reject; the rule-checker looks again after you approve), incidents handed to you, the eight-step loop with the current step lit and the time spent in each step, the diagnosis with every cause's probability, the twin's ranked fixes with the safety reasons for the ones it rejected and the reality check (predicted vs measured), a replay slider per incident, and the live decision log.
- **Under each incident** (`src/ui/IncidentActions.tsx`): download its report, open **who knew what, when** (`src/ui/Coordination.tsx`: the NOC engineer, radio planner, regulator adviser and the person approving, each with its mandate, what it sees and what it cannot do, and the hand-overs in time order), or ask the policy adviser about it.
- **⚖ Policy screen** (`src/ui/PolicyPanel.tsx`, `src/ui/ItuAlignment.tsx`): ask the adviser, the gap analysis, the knowledge base with search and retrieval scores, and the ITU alignment.
- **Stats bar** (`src/ui/StatsBar.tsx`): phones by band, phones hurt over time, rescued, fixes applied and undone, times you were asked, the agent's turn and whole-tick time, language-model tokens.

## Evaluation (`src/nethealers/eval`, `docs/evaluation_report.md`)

Six scenarios on Station Road (normal day, moving bus, wrong beam, twin mismatch, hospital-zone conflict, faulty and stale data), five methods (no action, network alone, simple rule fixer, agent without twin, full agent), 8 seeds each, scored against the simulator's hidden truth. Degraded phone-seconds, during the problem + after it ends (lower is better):

| Scenario | Network alone | Rule fixer | Full agent |
|---|---|---|---|
| Normal day | 0 | 0 | 0 (no false alarms, no changes) |
| Moving bus | 221 + 19 | 76 + 91 | **106 + 19** |
| Wrong beam | 418 | 131 | **30** |
| Twin mismatch | 326 | 121 + 78 | **112 + 11** |
| Hospital-zone conflict | 326 | 82 + 87, **24 zone breaches** | 221 + 0, **0 breaches** |
| Faulty and stale data | 754 | 734 | **559** |

The agent made 1-4 changes per run where the rule fixer made about 26, broke no limits in any run, and named the right cause in 88-100% of incidents. The rule fixer is faster during a blockage but never withdraws its moves and breaks the hospital limit; the agent is slower and more careful.

![timeline](docs/eval_timeline.png)

## Simplifications to state honestly

- No diffraction around corners; the scatter floor stands in for it.
- One reflection per path, no ground bounce, paths add as power (no phase).
- Buildings are axis-aligned boxes.
- Diagnosis labels come from the simulator, so accuracy here says how well the model reads *this* simulator, not a real network.
- Future work: validate against Sionna RT ray tracing.

## Licence

MIT (see `LICENSE`). The LWM weights are MIT-licensed by their authors. The documents in the knowledge base are downloaded from their official sources and are not redistributed here; only short excerpts appear in the generated reports.
