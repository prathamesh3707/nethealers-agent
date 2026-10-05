"""Boxes, line-of-sight tests and wall geometry.

Everything in the street is an axis-aligned box. Buildings are opaque to
28 GHz signals. Blockers such as buses or crowds let some signal through,
minus a fixed loss. Keeping boxes axis-aligned turns every test into a few
array operations, so a whole street updates in milliseconds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class Box:
    name: str
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    zmin: float
    zmax: float
    kind: str = "building"
    material: str = "concrete"
    loss_db: float = math.inf  # inf means nothing gets through
    hidden: bool = False  # exists in the real world only; the twin doesn't know it
    dynamic: bool = False  # moves or appears at runtime (bus, crowd); the twin can't see it directly

    @property
    def opaque(self) -> bool:
        return math.isinf(self.loss_db)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.xmin + self.xmax) / 2, (self.ymin + self.ymax) / 2)

    @property
    def height(self) -> float:
        return self.zmax - self.zmin

    def as_row(self) -> tuple[float, float, float, float, float, float]:
        return (self.xmin, self.xmax, self.ymin, self.ymax, self.zmin, self.zmax)

    def moved_to(self, x: float, y: float) -> None:
        hx, hy = (self.xmax - self.xmin) / 2, (self.ymax - self.ymin) / 2
        self.xmin, self.xmax, self.ymin, self.ymax = x - hx, x + hx, y - hy, y + hy

    def contains_xy(self, x: float, y: float) -> bool:
        return self.xmin <= x <= self.xmax and self.ymin <= y <= self.ymax


def box_at(name: str, x: float, y: float, size: tuple[float, float, float], *, along_y: bool = False,
           **kwargs) -> Box:
    """A box centred on (x, y), standing on the ground. `size` is length, width, height."""
    length, width, height = size
    if along_y:
        length, width = width, length
    return Box(name, x - length / 2, x + length / 2, y - width / 2, y + width / 2, 0.0, height, **kwargs)


def boxes_array(boxes: list[Box]) -> np.ndarray:
    if not boxes:
        return np.zeros((0, 6))
    return np.array([b.as_row() for b in boxes], dtype=float)


def segments_hit_boxes(p0: np.ndarray, p1: np.ndarray, boxes: np.ndarray, eps: float = 1e-4) -> np.ndarray:
    """Which segments p0 -> p1 pass through which boxes.

    p0, p1: (N, 3) segment ends. boxes: (M, 6) rows of xmin, xmax, ymin, ymax, zmin, zmax.
    Returns an (N, M) bool array. Touching a box at a segment end does not count,
    so a reflection point sitting on a wall doesn't block its own path.
    """
    n, m = len(p0), len(boxes)
    if n == 0 or m == 0:
        return np.zeros((n, m), dtype=bool)
    d = p1 - p0
    lo = boxes[:, [0, 2, 4]]
    hi = boxes[:, [1, 3, 5]]
    zero = np.abs(d) < 1e-12
    inv = np.where(zero, 0.0, 1.0 / np.where(zero, 1.0, d))
    t1 = (lo[None] - p0[:, None]) * inv[:, None]
    t2 = (hi[None] - p0[:, None]) * inv[:, None]
    tmin = np.minimum(t1, t2)
    tmax = np.maximum(t1, t2)
    inside = (p0[:, None] >= lo[None]) & (p0[:, None] <= hi[None])
    z3 = np.broadcast_to(zero[:, None], tmin.shape)
    tmin = np.where(z3, np.where(inside, -np.inf, np.inf), tmin)
    tmax = np.where(z3, np.where(inside, np.inf, -np.inf), tmax)
    t_enter = np.maximum(tmin.max(axis=2), 0.0)
    t_exit = np.minimum(tmax.min(axis=2), 1.0)
    return (t_exit - t_enter) > eps


@dataclass(frozen=True)
class Wall:
    """One vertical face of a building, used for mirror reflections."""

    building: str
    side: str  # north, south, east or west
    axis: int  # 0: the wall is the plane x = coord; 1: the plane y = coord
    coord: float
    lo: float  # extent along the other horizontal axis
    hi: float
    zmin: float
    zmax: float
    normal: int  # +1 if the wall faces the + direction of its axis
    material: str


def walls_of(box: Box) -> list[Wall]:
    z = (box.zmin, box.zmax)
    m = box.material
    return [
        Wall(box.name, "west", 0, box.xmin, box.ymin, box.ymax, *z, -1, m),
        Wall(box.name, "east", 0, box.xmax, box.ymin, box.ymax, *z, +1, m),
        Wall(box.name, "south", 1, box.ymin, box.xmin, box.xmax, *z, -1, m),
        Wall(box.name, "north", 1, box.ymax, box.xmin, box.xmax, *z, +1, m),
    ]


def angles_deg(v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Azimuth (0 = east, 90 = north) and elevation (positive = up) of vectors (N, 3)."""
    az = np.degrees(np.arctan2(v[:, 1], v[:, 0]))
    el = np.degrees(np.arctan2(v[:, 2], np.hypot(v[:, 0], v[:, 1])))
    return az, el


def wrap_deg(a):
    return (np.asarray(a) + 180.0) % 360.0 - 180.0
