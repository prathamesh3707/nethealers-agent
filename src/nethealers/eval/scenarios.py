"""The six test scenarios from the proposal, on Station Road.

Each scenario builds the street for a seed and returns a script: things that
happen at given ticks, plus an optional `react` hook that the street runs
whenever a controller changes something (used to make the twin wrong on
purpose in scenario 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..sim import (
    add_blocker,
    clear_problem,
    misconfigure_tower,
    move_blocker,
    station_road,
    stick_beams,
)
from ..sim.actions import Handover
from ..sim.layouts import BUS_POSITION
from ..sim.world import World

START = 10  # problems begin here, after a calm warm-up
LENGTH = 60


@dataclass
class Script:
    world: World
    events: dict[int, list[Callable[[World], None]]] = field(default_factory=dict)
    react: Callable | None = None
    label: str = "none"  # the true cause
    measure_until: int = LENGTH  # judge recovery up to here (before a temporary cause goes away)

    def at(self, tick: int, fn: Callable[[World], None]) -> None:
        self.events.setdefault(tick, []).append(fn)


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    build: Callable[[int], Script]


def _bus_script(seed: int, *, missing: bool, zone: bool, leave: int = 40) -> Script:
    rng = np.random.default_rng(seed)
    w = station_road(seed=seed)
    if missing:
        w.missing_relations = {(0, 1), (0, 2)}
    if not zone:
        w.zones = []
    s = Script(w, label="blockage", measure_until=leave)
    x_stop, y = BUS_POSITION[0] + float(rng.uniform(-4, 4)), BUS_POSITION[1]
    state = {}

    def arrive(world):  # the bus drives in over a few seconds
        state["id"] = add_blocker(world, "bus", x_stop - 40, y).id

    s.at(START, arrive)
    for k in range(1, 5):
        s.at(START + k, lambda world, k=k: move_blocker(world, state["id"], x_stop - 40 + 10 * k, y))
    for k in range(1, 4):
        s.at(leave + k - 1, lambda world, k=k: move_blocker(world, state["id"], x_stop + 15 * k, y))
    s.at(leave + 3, lambda world: clear_problem(world, state["id"]))
    return s


def normal(seed: int) -> Script:
    return Script(station_road(seed=seed), label="none")


def moving_blocker(seed: int) -> Script:
    return _bus_script(seed, missing=seed % 2 == 0, zone=False)


def wrong_beam(seed: int) -> Script:
    w = station_road(seed=seed)
    s = Script(w, label="wrong_beam")
    rng = np.random.default_rng(seed)

    def stick(world):
        ids = [u.id for u in world.ues if u.group == "bus_stop" and u.serving == 0][:8]
        stick_beams(world, ids, int(rng.choice([-3, 3])))

    s.at(START, stick)
    return s


def twin_mismatch(seed: int) -> Script:
    """A bus blocks the stop; right after the agent's first move, a truck stops in the new path.
    The twin couldn't know, so the first fix falls short and must be undone."""
    s = _bus_script(seed, missing=True, zone=False)
    done = {"n": 0}

    def react(world, action):
        if done["n"] or not isinstance(action, Handover):
            return
        done["n"] = 1
        t = world.towers[action.target]
        idx = world.ue_index()
        pts = np.array([[world.ues[idx[u]].x, world.ues[idx[u]].y] for u in action.ues if u in idx])
        cx, cy = pts.mean(axis=0)
        f = 0.9  # close to the phones, on the line from the new tower
        p = add_blocker(world, "truck", t.x + f * (cx - t.x), t.y + f * (cy - t.y),
                        along_y=abs(cy - t.y) < abs(cx - t.x), hidden=True)
        p.detail["note"] = "appeared after the agent acted"

    s.react = react
    return s


def conflicting_objectives(seed: int) -> Script:
    """The easiest escape for the bus-stop phones is Tower B, which serves the protected hospital zone."""
    return _bus_script(seed, missing=True, zone=True)


def bad_data(seed: int) -> Script:
    """Tower C is misconfigured (interference), its controls don't respond, and some phones' reports freeze."""
    w = station_road(seed=seed)
    s = Script(w, label="interference")
    rng = np.random.default_rng(seed)

    def fault(world):
        misconfigure_tower(world, 2, 6.0, -7.0)
        world.frozen_towers.add(2)

    def freeze(world):
        df = world.snapshot()
        hurt = df.sort_values("sinr_db").ue.tolist()[:12]
        world.stale_phones.update(int(u) for u in rng.choice(hurt, size=4, replace=False))

    s.at(START, fault)
    s.at(START + 1, freeze)
    return s


SCENARIOS = [
    Scenario("1_normal", "Normal operation", normal),
    Scenario("2_moving_blocker", "Moving blocker on a street", moving_blocker),
    Scenario("3_wrong_beam", "Suboptimal serving beam", wrong_beam),
    Scenario("4_twin_mismatch", "Twin mismatch", twin_mismatch),
    Scenario("5_conflict", "Conflicting objectives (hospital zone)", conflicting_objectives),
    Scenario("6_bad_data", "Faulty and stale data", bad_data),
]
