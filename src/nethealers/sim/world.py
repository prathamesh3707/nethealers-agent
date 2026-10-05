"""The simulated street: towers, phones, buildings, and one tick of network behaviour.

A World can play two parts:

- the "real" world, which has things the agent can't see: hidden objects,
  random shadowing, and noisy measurements;
- the agent's twin (`world.twin()`), a copy built only from what the
  network operator knows: the building map and the network settings.

Each `step()` advances one tick (one second): phones report what they
measure, built-in beam management and handover react, and every phone gets
a signal clarity (SINR) and a data rate.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .channel import Paths, path_loss_los_db, path_loss_nlos_db, received_power_mw, trace_paths
from .config import (
    MATERIAL_REFLECTION_LOSS_DB,
    MobilityConfig,
    PanelConfig,
    RadioConfig,
    RealismConfig,
)
from .geometry import Box, boxes_array, segments_hit_boxes, walls_of


@dataclass
class Tower:
    id: int
    name: str
    x: float
    y: float
    z: float
    boresight_deg: float  # direction the panel faces: 0 = east, 90 = north
    tilt_deg: float = 6.0  # electrical downtilt
    power_dbm: float = 33.0
    min_power_dbm: float = 24.0
    max_power_dbm: float = 38.0  # approved and legal maximum
    min_tilt_deg: float = 0.0
    max_tilt_deg: float = 15.0

    @property
    def pos(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z])


@dataclass
class UE:
    """A phone."""

    id: int
    x: float
    y: float
    z: float = 1.5
    demand_mbps: float = 15.0
    group: str = "street"
    serving: int | None = None  # tower id
    beam: int | None = None
    beam_lock: int | None = None  # beam fixed by the agent or stuck by a fault
    lock_reason: str | None = None  # "override" or "stuck"
    forced_tower: int | None = None  # set by the agent's handover fix
    a3_target: int | None = None
    a3_count: int = 0
    added_by: str | None = None  # problem id that created this phone (crowd surge)

    @property
    def pos(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z])


@dataclass
class Interferer:
    """Something outside the network transmitting on our frequency (e.g. an illegal booster)."""

    name: str
    x: float
    y: float
    z: float
    power_dbm: float
    hidden: bool = True


@dataclass
class SurfaceMod:
    """A change to how a wall reflects, e.g. scaffolding netting over a glass facade."""

    building: str
    side: str
    extra_loss_db: float
    hidden: bool = True
    note: str = ""


@dataclass
class Zone:
    """A protected area, e.g. a hospital. Its tower must not be pushed past `max_load`."""

    name: str
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    tower: int
    max_load: float = 0.7

    def contains(self, x: float, y: float) -> bool:
        return self.xmin <= x <= self.xmax and self.ymin <= y <= self.ymax


class ShadowField:
    """Smooth random extra loss over the map (one per tower). Real world only."""

    def __init__(self, seed: int, extent: tuple[float, float, float, float], spacing: float, std_db: float):
        x0, x1, y0, y1 = extent
        self.x0, self.y0, self.spacing = x0, y0, spacing
        nx = int(math.ceil((x1 - x0) / spacing)) + 3
        ny = int(math.ceil((y1 - y0) / spacing)) + 3
        rng = np.random.default_rng(seed)
        g = rng.normal(size=(ny, nx))
        g = (g + np.roll(g, 1, 0) + np.roll(g, -1, 0) + np.roll(g, 1, 1) + np.roll(g, -1, 1)) / 5
        self.grid = g / (g.std() + 1e-12) * std_db

    def at(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        fx = np.clip((np.asarray(x) - self.x0) / self.spacing, 0, self.grid.shape[1] - 1.001)
        fy = np.clip((np.asarray(y) - self.y0) / self.spacing, 0, self.grid.shape[0] - 1.001)
        ix, iy = fx.astype(int), fy.astype(int)
        ax, ay = fx - ix, fy - iy
        g = self.grid
        return ((1 - ax) * (1 - ay) * g[iy, ix] + ax * (1 - ay) * g[iy, ix + 1]
                + (1 - ax) * ay * g[iy + 1, ix] + ax * ay * g[iy + 1, ix + 1])


@dataclass
class StepResult:
    """Everything computed in one tick, as arrays. Phone order matches `World.ues`."""

    tick: int
    paths: Paths
    rx_mw: np.ndarray  # (T, B, U) true received power per resource element
    rsrp_beam_dbm: np.ndarray  # (T, B, U) as reported (noisy, rounded in the real world)
    sinr_db: np.ndarray  # (U,) true
    sinr_reported_db: np.ndarray  # (U,)
    rsrq_db: np.ndarray  # (U,)
    throughput_mbps: np.ndarray  # (U,)
    airtime: np.ndarray  # (U,) share of its tower's time each phone gets
    load: np.ndarray  # (T,) airtime the tower's phones need; above 1 means overloaded
    interference_mw: np.ndarray  # (U,) interference per resource element


def spectral_efficiency(sinr_db: np.ndarray, radio: RadioConfig) -> np.ndarray:
    se = radio.shannon_efficiency * np.log2(1 + 10 ** (np.asarray(sinr_db) / 10))
    se = np.minimum(se, radio.max_spectral_efficiency)
    return np.where(np.asarray(sinr_db) < radio.min_sinr_db, 0.0, se)


def schedule(demand_mbps: np.ndarray, rate_full_mbps: np.ndarray, serving: np.ndarray, n_towers: int):
    """Share each tower's airtime between its phones (fair water-filling, capped by demand)."""
    need = np.where(rate_full_mbps > 1e-9, demand_mbps / np.maximum(rate_full_mbps, 1e-9), np.inf)
    airtime = np.zeros(len(demand_mbps))
    load = np.zeros(n_towers)
    for t in range(n_towers):
        idx = np.nonzero(serving == t)[0]
        if len(idx) == 0:
            continue
        finite = np.isfinite(need[idx])
        load[t] = need[idx][finite].sum() + (~finite).sum()  # a phone with no usable link wants it all
        remaining, left = 1.0, len(idx)
        for i in idx[np.argsort(need[idx])]:
            give = min(need[i], remaining / left)
            airtime[i] = give
            remaining -= give
            left -= 1
    return airtime, airtime * rate_full_mbps, load


class World:
    def __init__(
        self,
        name: str,
        buildings: list[Box],
        towers: list[Tower],
        ues: list[UE],
        *,
        seed: int = 0,
        radio: RadioConfig | None = None,
        panel: PanelConfig | None = None,
        mobility: MobilityConfig | None = None,
        realism: RealismConfig | None = None,
        extent: tuple[float, float, float, float] | None = None,
    ):
        self.name = name
        self.boxes: list[Box] = list(buildings)
        self.towers = towers
        self.ues = ues
        self.interferers: list[Interferer] = []
        self.surface_mods: list[SurfaceMod] = []
        self.zones: list[Zone] = []
        self.problems: dict = {}  # id -> Problem (see problems.py)
        self.cio: dict[tuple[int, int], float] = {}  # handover bias from tower a to tower b (dB)
        # Neighbour relations the network is missing: phones on tower a can't hand over to tower b.
        self.missing_relations: set[tuple[int, int]] = set()
        self.radio = radio or RadioConfig()
        self.panel = panel or PanelConfig()
        self.mobility = mobility or MobilityConfig()
        self.realism = realism or RealismConfig()
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.is_twin = False
        self.tick = 0
        self.history: list[pd.DataFrame] = []
        self.last: StepResult | None = None
        span = self.panel.beam_span_deg
        self.beam_az = np.linspace(-span / 2, span / 2, self.panel.n_beams)
        self.extent = extent or self._bounds()
        self._shadow = [
            ShadowField(seed * 1000 + 17 * t.id + 1, self.extent, self.realism.shadowing_grid_m,
                        self.realism.shadowing_std_db)
            for t in towers
        ]
        n_t, n_b = len(towers), self.panel.n_beams
        self._activity = np.full(n_t, 0.5)
        self._beam_weights = np.full((n_t, n_b), 1.0 / n_b)
        self._next_id = max((u.id for u in ues), default=-1) + 1

    # ------------------------------------------------------------------ setup helpers

    def _bounds(self) -> tuple[float, float, float, float]:
        xs = [b.xmin for b in self.boxes] + [b.xmax for b in self.boxes] + [t.x for t in self.towers]
        ys = [b.ymin for b in self.boxes] + [b.ymax for b in self.boxes] + [t.y for t in self.towers]
        xs += [u.x for u in self.ues]
        ys += [u.y for u in self.ues]
        return (min(xs) - 20, max(xs) + 20, min(ys) - 20, max(ys) + 20)

    def next_ue_id(self) -> int:
        self._next_id += 1
        return self._next_id - 1

    def tower(self, tower_id: int) -> Tower:
        return self.towers[tower_id]

    def ue(self, ue_id: int) -> UE:
        for u in self.ues:
            if u.id == ue_id:
                return u
        raise KeyError(f"no phone {ue_id}")

    def ue_index(self) -> dict[int, int]:
        return {u.id: i for i, u in enumerate(self.ues)}

    def box(self, name: str) -> Box:
        for b in self.boxes:
            if b.name == name:
                return b
        raise KeyError(f"no box {name}")

    def visible_boxes(self) -> list[Box]:
        return [b for b in self.boxes if not (self.is_twin and b.hidden)]

    # ------------------------------------------------------------------ twin and copies

    def copy(self) -> "World":
        return copy.deepcopy(self)

    def twin(self, include_dynamic: bool = False) -> "World":
        """The agent's copy: building map and network settings only.

        Hidden objects, hidden wall changes and outside interferers are left
        out, along with shadowing and measurement noise. Moving blockers are
        left out too unless `include_dynamic` (the twin learns about a bus
        only by guessing where it is).
        """
        tw = copy.deepcopy(self)
        tw.is_twin = True
        tw.boxes = [b for b in tw.boxes if not b.hidden and (include_dynamic or not b.dynamic)]
        tw.surface_mods = [m for m in tw.surface_mods if not m.hidden]
        tw.interferers = [i for i in tw.interferers if not i.hidden]
        tw.history = []
        return tw

    # ------------------------------------------------------------------ physics

    def trace(self) -> Paths:
        boxes = self.visible_boxes()
        opaque = [b for b in boxes if b.opaque]
        blockers = [b for b in boxes if not b.opaque]
        walls = [w for b in opaque if b.kind == "building" for w in walls_of(b)]
        mods = {}
        for m in self.surface_mods:
            if not (self.is_twin and m.hidden):
                mods[(m.building, m.side)] = mods.get((m.building, m.side), 0.0) + m.extra_loss_db
        wall_loss = np.array(
            [MATERIAL_REFLECTION_LOSS_DB.get(w.material, 7.0) + mods.get((w.building, w.side), 0.0) for w in walls]
        )
        tower_pos = np.array([t.pos for t in self.towers])
        ue_pos = np.array([u.pos for u in self.ues]) if self.ues else np.zeros((0, 3))
        paths = trace_paths(
            tower_pos, ue_pos, boxes_array(opaque), boxes_array(blockers),
            np.array([b.loss_db for b in blockers]), walls, wall_loss,
            self.radio.carrier_ghz, self.radio.scatter_extra_db,
        )
        if not self.is_twin and len(paths):
            shadow = np.zeros(len(paths))
            for t in range(len(self.towers)):
                m = paths.tower == t
                if m.any():
                    shadow[m] = self._shadow[t].at(ue_pos[paths.ue[m], 0], ue_pos[paths.ue[m], 1])
            paths.loss_db = paths.loss_db + shadow
        return paths

    def received_power(self, paths: Paths) -> np.ndarray:
        return received_power_mw(
            paths, len(self.towers), len(self.ues),
            np.array([self.radio.per_re_dbm(t.power_dbm) for t in self.towers]),
            np.array([t.boresight_deg for t in self.towers]),
            np.array([t.tilt_deg for t in self.towers]),
            self.beam_az, self.panel, self.radio.ue_gain_dbi,
        )

    def _external_interference_mw(self) -> np.ndarray:
        out = np.zeros(len(self.ues))
        sources = [i for i in self.interferers if not (self.is_twin and i.hidden)]
        if not sources or not self.ues:
            return out
        ue_pos = np.array([u.pos for u in self.ues])
        opaque = boxes_array([b for b in self.visible_boxes() if b.opaque])
        for src in sources:
            p0 = np.tile([src.x, src.y, src.z], (len(self.ues), 1))
            d = np.linalg.norm(ue_pos - p0, axis=1)
            blocked = segments_hit_boxes(p0, ue_pos, opaque).any(axis=1) if len(opaque) else np.zeros(len(d), bool)
            pl = np.where(blocked, path_loss_nlos_db(d, self.radio.carrier_ghz), path_loss_los_db(d, self.radio.carrier_ghz))
            out += 10 ** ((self.radio.per_re_dbm(src.power_dbm) - pl) / 10)
        return out

    # ------------------------------------------------------------------ one tick

    def step(self) -> pd.DataFrame:
        """Advance one tick and return what every phone experiences."""
        self.tick += 1
        n_t, n_b, n_u = len(self.towers), self.panel.n_beams, len(self.ues)
        paths = self.trace()
        rx = self.received_power(paths)
        rx_db = 10 * np.log10(np.maximum(rx, 1e-30))
        if self.is_twin:
            rep = rx_db
        else:
            rep = np.round(rx_db + self.rng.normal(0, self.realism.rsrp_noise_db, rx_db.shape))
        cell_rsrp = rep.max(axis=1)  # (T, U) best beam per tower

        self._attach_and_handover(cell_rsrp)
        self._beam_management(rep)

        serving = np.array([u.serving for u in self.ues], dtype=int) if n_u else np.zeros(0, int)
        beam = np.array([u.beam for u in self.ues], dtype=int) if n_u else np.zeros(0, int)
        u_idx = np.arange(n_u)
        signal = rx[serving, beam, u_idx]
        # Interference: every other tower, weighted by how busy it is and where its beams point.
        per_tower = np.einsum("tb,tbu->tu", self._beam_weights, rx) * self._activity[:, None]
        interference = per_tower.sum(axis=0) - per_tower[serving, u_idx] + self._external_interference_mw()
        noise = 10 ** (self.radio.noise_dbm_per_re / 10)
        sinr = 10 * np.log10(np.maximum(signal, 1e-30) / (interference + noise))
        if self.is_twin:
            sinr_rep = sinr.copy()
        else:
            sinr_rep = np.round(2 * (sinr + self.rng.normal(0, self.realism.sinr_noise_db, n_u))) / 2

        rate_full = self.radio.data_bandwidth_hz * spectral_efficiency(sinr, self.radio) / 1e6
        demand = np.array([u.demand_mbps for u in self.ues]) if n_u else np.zeros(0)
        airtime, tput, load = schedule(demand, rate_full, serving, n_t)

        # RSRQ = RSRP / RSSI per resource block; RSSI counts own-cell traffic, interference and noise.
        own = per_tower[serving, u_idx]
        rssi_re = own + interference + noise
        rsrp_cell = 10 ** (cell_rsrp[serving, u_idx] / 10)
        rsrq = np.clip(10 * np.log10(rsrp_cell / (12 * rssi_re)), -43, 20)

        # Remember how busy each tower is and where its beams point, for next tick's interference.
        weights = np.zeros((n_t, n_b))
        np.add.at(weights, (serving, beam), np.maximum(airtime, 1e-6))
        totals = weights.sum(axis=1, keepdims=True)
        self._beam_weights = np.where(totals > 0, weights / np.maximum(totals, 1e-12), 1.0 / n_b)
        self._activity = np.clip(np.minimum(load, 1.0), self.radio.idle_activity, 1.0)

        self.last = StepResult(self.tick, paths, rx, rep, sinr, sinr_rep, rsrq, tput, airtime, load, interference)
        df = self.snapshot()
        self.history.append(df)
        return df

    def _attach_and_handover(self, cell_rsrp: np.ndarray) -> None:
        mob = self.mobility
        for i, u in enumerate(self.ues):
            if u.forced_tower is not None:
                if u.serving != u.forced_tower:
                    u.serving, u.beam = u.forced_tower, None
                continue
            if u.serving is None:
                u.serving = int(np.argmax(cell_rsrp[:, i]))
                u.beam = None
                continue
            s = u.serving
            biased = cell_rsrp[:, i] + np.array([self.cio.get((s, t), 0.0) for t in range(len(self.towers))])
            biased[s] = -np.inf
            for a, b in self.missing_relations:
                if a == s:
                    biased[b] = -np.inf
            best = int(np.argmax(biased))
            if biased[best] > cell_rsrp[s, i] + mob.a3_offset_db:
                u.a3_count = u.a3_count + 1 if u.a3_target == best else 1
                u.a3_target = best
                if u.a3_count >= mob.time_to_trigger:
                    u.serving, u.beam = best, None
                    u.beam_lock, u.lock_reason = None, None
                    u.a3_target, u.a3_count = None, 0
            else:
                u.a3_target, u.a3_count = None, 0

    def _beam_management(self, rep: np.ndarray) -> None:
        margin = self.mobility.beam_switch_margin_db
        for i, u in enumerate(self.ues):
            if u.beam_lock is not None:
                u.beam = u.beam_lock
                continue
            beams = rep[u.serving, :, i]
            best = int(np.argmax(beams))
            if u.beam is None or beams[best] > beams[u.beam] + margin:
                u.beam = best

    # ------------------------------------------------------------------ reporting

    def snapshot(self) -> pd.DataFrame:
        """One row per phone for the last tick. `true_*` columns are hidden from the agent."""
        r = self.last
        if r is None or not self.ues:
            return pd.DataFrame()
        n_u = len(self.ues)
        u_idx = np.arange(n_u)
        serving = np.array([u.serving for u in self.ues])
        beam = np.array([u.beam for u in self.ues])
        cell = r.rsrp_beam_dbm.max(axis=1)  # (T, U)
        nbr = cell.copy()
        nbr[serving, u_idx] = -np.inf
        best_nbr = nbr.argmax(axis=0)
        true_cell = 10 * np.log10(np.maximum(r.rx_mw.max(axis=1), 1e-30))
        return pd.DataFrame({
            "tick": self.tick,
            "ue": [u.id for u in self.ues],
            "group": [u.group for u in self.ues],
            "x": [u.x for u in self.ues],
            "y": [u.y for u in self.ues],
            "serving": serving,
            "beam": beam,
            "beam_locked": [u.beam_lock is not None for u in self.ues],
            "best_beam": r.rsrp_beam_dbm[serving, :, u_idx].argmax(axis=1),
            "rsrp_dbm": cell[serving, u_idx],
            "beam_rsrp_dbm": r.rsrp_beam_dbm[serving, beam, u_idx],
            "nbr_tower": best_nbr,
            "nbr_rsrp_dbm": nbr[best_nbr, u_idx],
            "sinr_db": r.sinr_reported_db,
            "rsrq_db": np.round(r.rsrq_db, 1),
            "throughput_mbps": np.round(r.throughput_mbps, 2),
            "demand_mbps": [u.demand_mbps for u in self.ues],
            "tower_load": r.load[serving],
            "true_sinr_db": r.sinr_db,
            "true_rsrp_dbm": true_cell[serving, u_idx],
        })

    def run(self, ticks: int) -> pd.DataFrame:
        df = None
        for _ in range(ticks):
            df = self.step()
        return df

    def tower_summary(self) -> pd.DataFrame:
        r = self.last
        rows = []
        for t in self.towers:
            mask = np.array([u.serving == t.id for u in self.ues])
            rows.append({
                "tower": t.name, "phones": int(mask.sum()), "load": round(float(r.load[t.id]), 2),
                "power_dbm": t.power_dbm, "tilt_deg": t.tilt_deg,
                "median_sinr_db": round(float(np.median(r.sinr_db[mask])), 1) if mask.any() else None,
            })
        return pd.DataFrame(rows)
