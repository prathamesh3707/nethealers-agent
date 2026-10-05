"""Generate labelled examples by breaking simulated streets on purpose.

One episode:
1. Build a street (a random grid city or a random long street; Station Road
   only for the separate test set).
   Sometimes remove neighbour links so problems can't heal on their own.
2. Run a few normal ticks: the "before" picture.
3. Add one random problem (or none), with random size and position.
4. Run 1-3 more ticks, and run a copy of the world *without* the problem
   for the same ticks.
5. A phone is labelled with the problem's cause only if the problem really
   hurt it compared with the copy: clarity at least 3 dB worse, or it lost
   its data rate. Everyone else is "none". A crowd hurts two ways: phones on
   the overloaded tower are labelled congestion, phones on other towers
   (hurt by the busy tower's extra transmissions) are labelled interference.

Features come only from what the network can observe (see features.py).
"""

from __future__ import annotations

import math
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from ..sim import (
    add_blocker,
    add_external_interferer,
    crowd_surge,
    misconfigure_tower,
    random_city,
    random_street,
    station_road,
    stick_beams,
    without,
)
from ..sim.world import World
from .features import phone_features

KIND_ODDS = {"none": 0.1, "blockage": 0.36, "wrong_beam": 0.24, "interference": 0.15, "congestion": 0.15}
BLOCKER_ODDS = {"bus": 0.3, "truck": 0.15, "car": 0.12, "crowd": 0.2, "kiosk": 0.1, "hoarding": 0.13}
SINR_DROP_DB = 3.0


def _inside_building(world: World, x: float, y: float) -> bool:
    return any(b.kind == "building" and b.xmin - 0.5 <= x <= b.xmax + 0.5 and b.ymin - 0.5 <= y <= b.ymax + 0.5
               for b in world.boxes)


def _place_blocker(world: World, u, rng: np.random.Generator):
    """Put a random blocker on the line from the phone's tower, close enough to actually cut it.

    The line of sight drops from the tower's height to the phone's 1.5 m, so a
    low object (car, crowd) only blocks within a few metres of the phone while
    a bus or hoarding can block further out.
    """
    from ..sim.config import BLOCKER_TYPES

    t = world.towers[u.serving]
    kind = str(rng.choice(list(BLOCKER_ODDS), p=list(BLOCKER_ODDS.values())))
    h_block = BLOCKER_TYPES[kind]["size"][2]
    dist = math.hypot(u.x - t.x, u.y - t.y)
    reach = (h_block - u.z) * dist / max(t.z - u.z, 0.5)  # how far from the phone the line is still low enough
    for _ in range(20):
        s = rng.uniform(0.5, max(1.0, min(0.9 * reach, 0.45 * dist)))
        f = 1 - s / max(dist, 1e-6)
        x, y = t.x + f * (u.x - t.x), t.y + f * (u.y - t.y)
        if not _inside_building(world, x, y):
            along_y = abs(u.y - t.y) > abs(u.x - t.x)
            if rng.random() < 0.7:  # usually the long side lies across the line of sight
                along_y = not along_y
            return add_blocker(world, kind, x, y, along_y=along_y)
    return None


def inject_random_problem(world: World, kind: str, rng: np.random.Generator):
    """Add one problem of `kind` somewhere it is likely to matter. Returns the Problem or None."""
    if kind == "none":
        return None
    u = world.ues[int(rng.integers(len(world.ues)))]
    if kind == "blockage":
        placed = None
        for _ in range(int(rng.integers(1, 4))):  # one to three blockers
            p = _place_blocker(world, u if placed is None else world.ues[int(rng.integers(len(world.ues)))], rng)
            placed = placed or p
        return placed
    if kind == "wrong_beam":
        group = [v.id for v in world.ues
                 if v.serving == u.serving and math.hypot(v.x - u.x, v.y - u.y) < 25][: int(rng.integers(2, 11))]
        offset = int(rng.choice([-4, -3, -2, -1, 1, 2, 3, 4], p=[.15, .15, .15, .05, .05, .15, .15, .15]))
        return stick_beams(world, group, offset)
    if kind == "interference":
        if rng.random() < 0.65:
            tower = int(rng.integers(len(world.towers)))
            return misconfigure_tower(world, tower, float(rng.uniform(3, 7)), float(-rng.uniform(3, 8)))
        for _ in range(20):
            a, d = rng.uniform(0, 2 * math.pi), rng.uniform(5, 40)
            x, y = u.x + d * math.cos(a), u.y + d * math.sin(a)
            if not _inside_building(world, x, y):
                return add_external_interferer(world, x, y, float(rng.uniform(33, 46)))
        return None
    if kind == "congestion":
        return crowd_surge(world, u.x, u.y, float(rng.uniform(8, 22)), int(rng.integers(20, 95)),
                           demand_mbps=float(rng.uniform(10, 30)), seed=int(rng.integers(1 << 30)))
    raise ValueError(kind)


def make_world(seed: int, layout: str, rng: np.random.Generator) -> World:
    if layout == "station_road":
        w = station_road(seed=seed, n_street_users=int(rng.integers(25, 50)))
    elif rng.random() < 0.5:
        w = random_city(seed, n_ues=int(rng.integers(40, 90)), n_towers=int(rng.integers(3, 5)))
    else:
        w = random_street(seed, n_ues=int(rng.integers(40, 90)), n_towers=int(rng.integers(3, 5)))
    if rng.random() < 0.4:  # missing neighbour links: problems can't heal on their own
        n = len(w.towers)
        for a in range(n):
            for b in range(n):
                if a != b and rng.random() < 0.5:
                    w.missing_relations.add((a, b))
    return w


def run_episode(seed: int, layout: str = "city", with_lwm: bool = True, keep_none_ratio: float = 1.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    world = make_world(seed, layout, rng)
    world.run(4)
    base_frames = world.history[-3:]
    base_result = world.last
    kind = str(rng.choice(list(KIND_ODDS), p=list(KIND_ODDS.values())))
    problem = inject_random_problem(world, kind, rng)
    if problem is None:
        kind = "none"
    counterfactual = without(world)
    ticks = int(rng.integers(1, 4))
    for _ in range(ticks):
        world.step()
        counterfactual.step()

    feats = phone_features(world, base_frames, base_result)
    real = world.snapshot().set_index("ue").loc[feats.index]
    cf = counterfactual.snapshot().set_index("ue").loc[feats.index]
    lost_data = (real.throughput_mbps < 0.8 * real.demand_mbps) & (cf.throughput_mbps >= 0.95 * cf.demand_mbps)
    affected = ((cf.true_sinr_db - real.true_sinr_db) >= SINR_DROP_DB) | lost_data
    label = np.where(affected & (problem is not None), problem.label if problem else "none", "none")
    if problem is not None and problem.label == "congestion":
        # Label by what each phone suffers: phones on the overloaded tower lose airtime (congestion);
        # phones on other towers are hurt by that tower's extra transmissions (interference).
        on_busy = (real.tower_load >= 1.0).values
        label = np.where(affected & on_busy, "congestion", np.where(affected, "interference", "none"))

    feats["label"] = label
    feats["affected"] = affected.values & (problem is not None)
    feats["kind"] = problem.kind if problem else "none"
    feats["fixable"] = problem.fixable if problem else True
    feats["episode"] = seed
    feats["world"] = world.name
    feats["ticks_after"] = ticks
    feats = feats.reset_index().rename(columns={"index": "ue"})

    # Keep every hurt phone and a matching number of unaffected ones.
    hurt = feats[feats.label != "none"]
    fine = feats[feats.label == "none"]
    n_keep = min(len(fine), max(4, int(round(keep_none_ratio * len(hurt)))))
    fine = fine.sample(n=n_keep, random_state=int(rng.integers(1 << 30)))
    out = pd.concat([hurt, fine]).reset_index(drop=True)

    if with_lwm and len(out):
        out = _add_lwm(out, world, base_result)
    return out


_LWM = None


def _lwm_model():
    global _LWM
    if _LWM is None:
        import torch

        from .lwm import load_model

        torch.set_num_threads(1)
        _LWM = load_model()
    return _LWM


def _add_lwm(out: pd.DataFrame, world: World, base_result) -> pd.DataFrame:
    from .lwm import lwm_features

    return pd.concat([out.reset_index(drop=True), lwm_features(_lwm_model(), world, base_result, list(out.ue))],
                     axis=1)


def generate(n_episodes: int, start_seed: int = 0, layout: str = "city", workers: int | None = None,
             with_lwm: bool = True) -> pd.DataFrame:
    seeds = list(range(start_seed, start_seed + n_episodes))
    workers = workers or max(1, (os.cpu_count() or 2) // 2)  # half the cores: slower, but the laptop stays cool
    if workers == 1:
        parts = [run_episode(s, layout, with_lwm) for s in seeds]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            parts = list(ex.map(run_episode, seeds, [layout] * len(seeds), [with_lwm] * len(seeds),
                                chunksize=max(1, len(seeds) // (workers * 8))))
    return pd.concat(parts, ignore_index=True)
