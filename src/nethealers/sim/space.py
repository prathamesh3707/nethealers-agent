"""Keeping things on the street from occupying the same space.

Vehicles (bus, truck, car) are solid: placing one slides it along its lane
to the nearest free spot, moving one stops just short of whatever is in the
way, and nothing is placed inside a building. Other blockers (crowd, kiosk,
hoarding) are refused where they would overlap something.

Footprints are compared on the ground plan only (x, y), with a small gap
so vehicles never look glued together.
"""

from __future__ import annotations

from .config import BLOCKER_TYPES
from .world import World

VEHICLES = frozenset({"bus", "truck", "car"})
GAP_M = 1.0  # space kept between a vehicle and anything else
SEARCH_STEP_M = 0.5
SEARCH_RANGE_M = 80.0
MOVE_STEP_M = 0.25

Rect = tuple[float, float, float, float]  # x0, x1, y0, y1


def footprint(kind: str, x: float, y: float, along_y: bool = False) -> Rect:
    length, width, _ = BLOCKER_TYPES[kind]["size"]
    if along_y:
        length, width = width, length
    return (x - length / 2, x + length / 2, y - width / 2, y + width / 2)


def _touch(a: Rect, b: Rect, gap: float) -> bool:
    return a[0] < b[1] + gap and a[1] > b[0] - gap and a[2] < b[3] + gap and a[3] > b[2] - gap


def blocking(world: World, rect: Rect, *, ignore: str | None = None, gap: float = GAP_M) -> list[str]:
    """Names of what `rect` would overlap: other blockers (kept `gap` apart) and buildings (no gap)."""
    out = []
    for b in world.boxes:
        if b.name == ignore:
            continue
        other = (b.xmin, b.xmax, b.ymin, b.ymax)
        if b.kind == "building":
            if _touch(rect, other, 0.0):
                out.append(b.name)
        elif _touch(rect, other, gap):
            out.append(b.name)
    return out


def describe(world: World, names: list[str]) -> str:
    kinds = []
    for n in names:
        b = next((b for b in world.boxes if b.name == n), None)
        kinds.append(b.name if b is None or b.kind == "building" else f"the {b.kind}")
    return ", ".join(dict.fromkeys(kinds))


def free_spot(world: World, kind: str, x: float, y: float, along_y: bool = False, *, ignore: str | None = None,
              search: float = SEARCH_RANGE_M) -> float | None:
    """Nearest x (along the lane, starting at `x`) where a `kind` fits without touching anything."""
    x0, x1 = world.extent[0], world.extent[1]
    half = (footprint(kind, 0, 0, along_y)[1] - footprint(kind, 0, 0, along_y)[0]) / 2
    steps = int(search / SEARCH_STEP_M)
    for k in range(steps + 1):
        for cand in ((x,) if k == 0 else (x + k * SEARCH_STEP_M, x - k * SEARCH_STEP_M)):
            if cand - half < x0 or cand + half > x1:
                continue
            if not blocking(world, footprint(kind, cand, y, along_y), ignore=ignore):
                return cand
    return None


def reachable_x(world: World, name: str, target_x: float) -> float:
    """How far the blocker `name` can slide along x toward `target_x` before it would touch something."""
    b = next(b for b in world.boxes if b.name == name)
    cx = (b.xmin + b.xmax) / 2
    half_l, half_w = (b.xmax - b.xmin) / 2, (b.ymax - b.ymin) / 2
    cy = (b.ymin + b.ymax) / 2
    direction = 1.0 if target_x > cx else -1.0
    x = cx
    while abs(target_x - x) > 1e-9:
        nxt = x + direction * min(MOVE_STEP_M, abs(target_x - x))
        if blocking(world, (nxt - half_l, nxt + half_l, cy - half_w, cy + half_w), ignore=name):
            break
        x = nxt
    return x
