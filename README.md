# NetHealers: self-healing 5G network agent

Simulation project for the ITU AI for Good Build-a-thon 5.0. An agent watches a 5G street, spots phones whose signal dropped, works out why, rehearses fixes on a virtual copy of the street (the digital twin), applies the safest one, checks the result and undoes it if it fell short.

## Status

| Step | What | State |
|---|---|---|
| 1 | Signal world: 3D street, signal maths, problems, fixes, twin | Done |
| 2 | Dataset and diagnosis model (with and without LWM) | Next |
| 3 | Agent brain, safety checks, automatic tests | Planned |
| 4 | 3D game with live agent panel | Planned |

## Setup

Needs [uv](https://docs.astral.sh/uv/). Python 3.12 is installed automatically.

```bash
uv sync
uv run pytest                       # 24 tests, under a second
uv run python scripts/step1_demo.py # narrated demo, pictures in out/
```

If `import nethealers` fails on macOS, the editable-install `.pth` file may have been marked hidden (Python 3.12 skips hidden `.pth` files). Fix with `chflags nohidden .venv/lib/python3.12/site-packages/*.pth`, or prefix commands with `PYTHONPATH=src`.

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

## Simplifications to state honestly

- No diffraction around corners; the scatter floor stands in for it.
- One reflection per path, no ground bounce, paths add as power (no phase).
- Buildings are axis-aligned boxes.
- Future work: validate against Sionna RT ray tracing.
