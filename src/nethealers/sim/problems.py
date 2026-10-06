"""Ways to break the network, each tagged with its true cause.

These are the buttons the game and the dataset generator press. Every
problem records how to remove it, so we can always ask "what would this
phone see without the problem?" That comparison is how the dataset labels
which phones a problem actually hurt.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np

from .config import BLOCKER_TYPES
from .geometry import box_at
from .world import UE, Interferer, World

_ids = itertools.count(1)


@dataclass
class Problem:
    id: str
    label: str  # blockage | wrong_beam | interference | congestion
    kind: str  # finer detail, e.g. "bus", "neighbour_misconfig", "external_interferer"
    detail: dict = field(default_factory=dict)
    fixable: bool = True  # False when no network setting can remove the cause (e.g. an illegal booster)


def _register(world: World, label: str, kind: str, detail: dict, fixable: bool = True) -> Problem:
    p = Problem(f"{kind}-{next(_ids)}", label, kind, detail, fixable)
    world.problems[p.id] = p
    return p


def add_blocker(world: World, kind: str, x: float, y: float, *, along_y: bool = False,
                size: tuple[float, float, float] | None = None, hidden: bool = False) -> Problem:
    """Put a bus, truck, crowd, kiosk or hoarding at (x, y)."""
    spec = BLOCKER_TYPES[kind]
    p = _register(world, "blockage", kind, {"x": x, "y": y})
    world.boxes.append(box_at(p.id, x, y, size or spec["size"], along_y=along_y, kind=kind,
                              loss_db=spec["loss_db"], dynamic=True, hidden=hidden))
    p.detail["box"] = p.id
    return p


def move_blocker(world: World, problem_id: str, x: float, y: float) -> None:
    world.box(world.problems[problem_id].detail["box"]).moved_to(x, y)
    world.problems[problem_id].detail.update(x=x, y=y)


def stick_beams(world: World, ue_ids: list[int], offset: int = 3) -> Problem:
    """Built-in beam management gets stuck on a wrong beam for these phones."""
    if world.last is None:
        world.step()
    idx = world.ue_index()
    before = {}
    for uid in ue_ids:
        u = world.ues[idx[uid]]
        before[uid] = (u.beam_lock, u.lock_reason)
        current = u.beam if u.beam is not None else 0
        u.beam_lock = int(np.clip(current + offset, 0, world.panel.n_beams - 1))
        if u.beam_lock == current:
            u.beam_lock = int(np.clip(current - offset, 0, world.panel.n_beams - 1))
        u.lock_reason = "stuck"
    return _register(world, "wrong_beam", "stuck_beam", {"ues": list(ue_ids), "offset": offset, "before": before})


def misconfigure_tower(world: World, tower_id: int, power_delta_db: float = 5.0,
                       tilt_delta_deg: float = -5.0) -> Problem:
    """A neighbour tower is set too loud and tilted up, so it spills into other cells.

    A fault, so it ignores the normal power and tilt limits.
    """
    t = world.towers[tower_id]
    old_power, old_tilt = t.power_dbm, t.tilt_deg
    t.power_dbm += power_delta_db
    t.tilt_deg = max(-5.0, t.tilt_deg + tilt_delta_deg)
    return _register(world, "interference", "neighbour_misconfig",
                     {"tower": tower_id, "power_delta_db": power_delta_db,
                      "tilt_delta_deg": t.tilt_deg - old_tilt, "power_before": old_power, "tilt_before": old_tilt})


def add_external_interferer(world: World, x: float, y: float, power_dbm: float = 40.0, z: float = 4.0) -> Problem:
    """Something outside the network (e.g. an illegal signal booster) transmits on our band.

    `power_dbm` is radiated power including the device antenna gain (EIRP).
    """
    p = _register(world, "interference", "external_interferer", {"x": x, "y": y, "power_dbm": power_dbm},
                  fixable=False)
    world.interferers.append(Interferer(p.id, x, y, z, power_dbm, hidden=True))
    return p


def crowd_surge(world: World, x: float, y: float, radius: float, n_users: int, demand_mbps: float = 25.0,
                seed: int | None = None) -> Problem:
    """Many people arrive in one place and all want data (a match ends, a train arrives)."""
    rng = np.random.default_rng(seed if seed is not None else world.seed + world.tick + 99)
    p = _register(world, "congestion", "crowd_surge", {"x": x, "y": y, "radius": radius, "n": n_users})
    ids = []
    for _ in range(n_users):
        r = radius * math.sqrt(rng.random())
        a = rng.random() * 2 * math.pi
        uid = world.next_ue_id()
        ids.append(uid)
        world.ues.append(UE(uid, x + r * math.cos(a), y + r * math.sin(a), demand_mbps=demand_mbps,
                            group="crowd", added_by=p.id))
    p.detail["ues"] = ids
    return p


def clear_problem(world: World, problem_id: str) -> None:
    """Remove a problem and everything it changed."""
    p = world.problems.pop(problem_id)
    if p.kind in ("bus", "truck", "car", "crowd", "kiosk", "hoarding"):
        world.boxes = [b for b in world.boxes if b.name != p.detail["box"]]
    elif p.kind == "stuck_beam":
        idx = world.ue_index()
        for uid, (lock, reason) in p.detail["before"].items():
            if uid in idx:
                u = world.ues[idx[uid]]
                if u.lock_reason == "stuck":
                    u.beam_lock, u.lock_reason = lock, reason
    elif p.kind == "neighbour_misconfig":
        # A technician puts the tower back to its settings from before the fault (overwriting any compensation
        # made in the meantime), rather than subtracting the fault from whatever the settings are now.
        t = world.towers[p.detail["tower"]]
        t.power_dbm = p.detail.get("power_before", t.power_dbm - p.detail["power_delta_db"])
        t.tilt_deg = p.detail.get("tilt_before", t.tilt_deg - p.detail["tilt_delta_deg"])
    elif p.kind == "external_interferer":
        world.interferers = [i for i in world.interferers if i.name != p.id]
    elif p.kind == "crowd_surge":
        gone = set(p.detail["ues"])
        world.ues = [u for u in world.ues if u.id not in gone]


def without(world: World, problem_ids: list[str] | None = None) -> World:
    """A copy of the world with some (default: all) problems removed. Used to label who a problem hurt."""
    w = world.copy()
    for pid in list(problem_ids if problem_ids is not None else w.problems):
        clear_problem(w, pid)
    return w
