"""Street layouts: the hand-made Station Road demo street and a random city generator."""

from __future__ import annotations

import numpy as np

from .geometry import Box
from .world import UE, Tower, World, Zone

ROAD = (88.0, 112.0)  # Station Road carriageway (y range)
NORTH_WALK = (112.5, 117.5)
SOUTH_WALK = (82.5, 87.5)
BUS_STOP = (222.0, 244.0)  # x range of the bus stop on the north pavement
BUS_POSITION = (211.0, 107.8)  # where the demo bus stops (centre)


def station_road(seed: int = 7, n_street_users: int = 38) -> World:
    """The demo street from the explainer: a busy road with a bus stop, offices and a hospital.

    Coordinates in metres: x runs east along the road, y runs north.
    """
    rng = np.random.default_rng(seed)
    buildings = [
        Box("Shop row", 20, 110, 118, 150, 0, 12, material="brick"),
        Box("Apartments", 120, 180, 120, 165, 0, 18, material="concrete"),
        Box("Glass office", 262, 295, 118, 175, 0, 32, material="glass"),
        Box("Hospital", 305, 380, 125, 200, 0, 22, material="concrete"),
        Box("Market", 20, 100, 35, 82, 0, 10, material="brick"),
        Box("Flyover", 120, 240, 72, 80, 0, 8, material="concrete"),
        Box("Mall", 260, 360, 25, 82, 0, 25, material="concrete"),
    ]
    towers = [
        Tower(0, "Tower A", 150, 85, 8, boresight_deg=25, tilt_deg=7),
        Tower(1, "Tower B", 386, 121, 10, boresight_deg=188, tilt_deg=6),
        Tower(2, "Tower C", 30, 86, 10, boresight_deg=5, tilt_deg=10),
    ]
    ues: list[UE] = []
    uid = 0
    for _ in range(12):
        ues.append(UE(uid, rng.uniform(*BUS_STOP), rng.uniform(113.0, 116.5), group="bus_stop",
                      demand_mbps=float(rng.uniform(3, 12))))
        uid += 1
    for _ in range(10):
        ues.append(UE(uid, rng.uniform(305, 380), rng.uniform(113.0, 123.5), group="hospital",
                      demand_mbps=float(rng.uniform(4, 15))))
        uid += 1
    for _ in range(n_street_users):
        walk = NORTH_WALK if rng.random() < 0.5 else SOUTH_WALK
        x = rng.uniform(20, 290)
        ues.append(UE(uid, x, rng.uniform(*walk), group="street", demand_mbps=float(rng.uniform(1, 6))))
        uid += 1
    world = World("Station Road", buildings, towers, ues, seed=seed, extent=(0, 400, 0, 220))
    world.zones.append(Zone("Hospital zone", 300, 395, 112, 205, tower=1, max_load=0.7))
    return world


MATERIALS = ("glass", "concrete", "brick", "metal")
MATERIAL_ODDS = (0.3, 0.4, 0.25, 0.05)


def random_city(seed: int, n_ues: int = 60, n_towers: int = 3, blocks: tuple[int, int] = (4, 3)) -> World:
    """A random grid city: blocks of buildings, towers on street corners, phones on the streets."""
    rng = np.random.default_rng(seed)
    road = float(rng.uniform(16, 26))
    block = float(rng.uniform(55, 85))
    nx, ny = blocks
    width = nx * (block + road) + road
    depth = ny * (block + road) + road
    buildings: list[Box] = []
    for i in range(nx):
        for j in range(ny):
            x0 = road + i * (block + road)
            y0 = road + j * (block + road)
            k = int(rng.integers(1, 4))
            cuts = np.sort(np.concatenate([[0.0, 1.0], rng.uniform(0.25, 0.75, k - 1)]))
            for a, b in zip(cuts[:-1], cuts[1:]):
                bx0, bx1 = x0 + a * block + 1.5, x0 + b * block - 1.5
                if bx1 - bx0 < 8:
                    continue
                inset = rng.uniform(0, 6, size=2)
                buildings.append(Box(
                    f"B{i}{j}{len(buildings)}", bx0, bx1, y0 + inset[0], y0 + block - inset[1], 0,
                    float(rng.uniform(8, 40)), material=str(rng.choice(MATERIALS, p=MATERIAL_ODDS)),
                ))

    def street_point() -> tuple[float, float]:
        while True:
            x, y = rng.uniform(2, width - 2), rng.uniform(2, depth - 2)
            if not any(b.xmin - 1 <= x <= b.xmax + 1 and b.ymin - 1 <= y <= b.ymax + 1 for b in buildings):
                return float(x), float(y)

    cx, cy = width / 2, depth / 2
    towers = []
    for t in range(n_towers):
        x, y = street_point()
        boresight = float(np.degrees(np.arctan2(cy - y, cx - x)) + rng.uniform(-40, 40))
        towers.append(Tower(t, f"Tower {chr(65 + t)}", x, y, float(rng.uniform(8, 15)),
                            boresight_deg=boresight, tilt_deg=float(rng.uniform(4, 9))))
    ues = []
    for u in range(n_ues):
        x, y = street_point()
        ues.append(UE(u, x, y, z=float(rng.uniform(1.2, 1.7)), demand_mbps=float(rng.uniform(2, 12))))
    return World(f"City {seed}", buildings, towers, ues, seed=seed, extent=(0, width, 0, depth))


def random_street(seed: int, n_ues: int = 60, n_towers: int = 3) -> World:
    """One long street with buildings on both sides and towers along it (like Station Road, but random)."""
    rng = np.random.default_rng(seed)
    length = float(rng.uniform(300, 500))
    road = float(rng.uniform(16, 30))
    walk = 5.0
    y_road0, y_road1 = 100.0, 100.0 + road
    buildings: list[Box] = []
    for side in (-1, 1):
        x = float(rng.uniform(0, 15))
        while x < length - 15:
            width = float(rng.uniform(20, 70))
            depth = float(rng.uniform(25, 60))
            front = y_road0 - walk if side < 0 else y_road1 + walk
            if rng.random() < 0.12:  # low wall or flyover edge right by the road
                depth, height, material = float(rng.uniform(6, 12)), float(rng.uniform(6, 9)), "concrete"
            else:
                height = float(rng.uniform(8, 40))
                material = str(rng.choice(MATERIALS, p=MATERIAL_ODDS))
            setback = float(rng.uniform(0, 8))
            y0, y1 = (front - setback - depth, front - setback) if side < 0 else (front + setback, front + setback + depth)
            buildings.append(Box(f"S{side:+d}{len(buildings)}", x, min(x + width, length), y0, y1, 0, height,
                                 material=material))
            x += width + float(rng.uniform(0, 18))
    towers = []
    xs = np.sort(rng.uniform(10, length - 10, n_towers))
    for t, tx in enumerate(xs):
        side = -1 if t % 2 == 0 else 1
        ty = y_road0 - rng.uniform(1, walk) if side < 0 else y_road1 + rng.uniform(1, walk)
        boresight = (0.0 if rng.random() < 0.5 else 180.0) + float(rng.uniform(-35, 35))
        towers.append(Tower(t, f"Tower {chr(65 + t)}", float(tx), float(ty), float(rng.uniform(8, 12)),
                            boresight_deg=boresight, tilt_deg=float(rng.uniform(5, 10))))
    ues = []

    def add(x, y, group):
        ues.append(UE(len(ues), float(x), float(y), z=float(rng.uniform(1.2, 1.7)), group=group,
                      demand_mbps=float(rng.uniform(2, 12))))

    for _ in range(int(rng.integers(1, 3))):  # bus stops and other busy spots
        cx = rng.uniform(20, length - 40)
        top = rng.random() < 0.5
        for _ in range(int(rng.integers(8, 15))):
            yy = rng.uniform(y_road1 + 0.5, y_road1 + walk - 0.5) if top else rng.uniform(y_road0 - walk + 0.5,
                                                                                          y_road0 - 0.5)
            add(cx + rng.uniform(0, 22), yy, "cluster")
    while len(ues) < n_ues:
        x = rng.uniform(5, length - 5)
        r = rng.random()
        if r < 0.4:
            y = rng.uniform(y_road1 + 0.5, y_road1 + walk - 0.5)
        elif r < 0.8:
            y = rng.uniform(y_road0 - walk + 0.5, y_road0 - 0.5)
        else:
            y = rng.uniform(y_road0 + 1, y_road1 - 1)
        add(x, y, "street")
    return World(f"Street {seed}", buildings, towers, ues, seed=seed, extent=(-10, length + 10, 20, 180 + road))
