"""The five fixes the agent may use, each with an exact undo.

Only physical limits are enforced here (a tower can't exceed its approved
power). Policy limits such as cooldowns, step sizes and protected zones
belong to the rule-checker, which sits in front of this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from .world import World


class ActionError(ValueError):
    """The fix can't be applied: it breaks a physical limit or refers to something that doesn't exist."""


@dataclass(frozen=True)
class BeamOverride:
    """Point a tower's beam for these phones at a chosen beam (e.g. a bounce path)."""

    tower: int
    ues: tuple[int, ...]
    beam: int


@dataclass(frozen=True)
class Handover:
    """Move these phones to another tower and keep them there."""

    ues: tuple[int, ...]
    target: int


@dataclass(frozen=True)
class PowerChange:
    tower: int
    delta_db: float


@dataclass(frozen=True)
class TiltChange:
    """Positive delta tilts the antenna further down."""

    tower: int
    delta_deg: float


@dataclass(frozen=True)
class LoadRebalance:
    """Bias handovers from `source` to `target` by `offset_db`, so edge phones move over."""

    source: int
    target: int
    offset_db: float


Action = Union[BeamOverride, Handover, PowerChange, TiltChange, LoadRebalance]


@dataclass
class Applied:
    action: Action
    tick: int
    undo: dict = field(default_factory=dict)


def describe(world: World, a: Action) -> str:
    name = lambda t: world.towers[t].name  # noqa: E731
    if isinstance(a, BeamOverride):
        return f"Point {name(a.tower)} beam {a.beam} at {len(a.ues)} phone(s)"
    if isinstance(a, Handover):
        return f"Move {len(a.ues)} phone(s) to {name(a.target)}"
    if isinstance(a, PowerChange):
        return f"{'Raise' if a.delta_db > 0 else 'Lower'} {name(a.tower)} power by {abs(a.delta_db):g} dB"
    if isinstance(a, TiltChange):
        return f"Tilt {name(a.tower)} {'down' if a.delta_deg > 0 else 'up'} by {abs(a.delta_deg):g} degrees"
    if isinstance(a, LoadRebalance):
        return f"Shift edge phones from {name(a.source)} toward {name(a.target)} ({a.offset_db:+g} dB)"
    raise TypeError(a)


def _tower_of(world: World, a: Action) -> int:
    if isinstance(a, (BeamOverride, PowerChange, TiltChange)):
        return a.tower
    if isinstance(a, Handover):
        return a.target
    return a.source


def apply_action(world: World, a: Action) -> Applied:
    """Apply a fix. If the tower's actuator is faulty (world.frozen_towers) nothing changes,
    but the caller isn't told: only checking the result reveals it."""
    rec = Applied(a, world.tick)
    if _tower_of(world, a) in world.frozen_towers:
        rec.undo["frozen"] = True
        return rec
    if isinstance(a, BeamOverride):
        if not 0 <= a.beam < world.panel.n_beams:
            raise ActionError(f"beam {a.beam} doesn't exist")
        idx = world.ue_index()
        _require_phones(world, a.ues, idx)
        for uid in a.ues:
            u = world.ues[idx[uid]]
            if u.serving != a.tower:
                raise ActionError(f"phone {uid} isn't served by {world.towers[a.tower].name}")
        for uid in a.ues:
            u = world.ues[idx[uid]]
            rec.undo[uid] = (u.beam_lock, u.lock_reason, u.beam)
            u.beam_lock, u.lock_reason, u.beam = a.beam, "override", a.beam
    elif isinstance(a, Handover):
        if not 0 <= a.target < len(world.towers):
            raise ActionError(f"tower {a.target} doesn't exist")
        idx = world.ue_index()
        _require_phones(world, a.ues, idx)
        for uid in a.ues:
            u = world.ues[idx[uid]]
            rec.undo[uid] = (u.serving, u.beam, u.beam_lock, u.lock_reason, u.forced_tower)
            u.serving, u.beam, u.beam_lock, u.lock_reason, u.forced_tower = a.target, None, None, None, a.target
    elif isinstance(a, PowerChange):
        t = world.towers[a.tower]
        new = t.power_dbm + a.delta_db
        if not t.min_power_dbm - 1e-9 <= new <= t.max_power_dbm + 1e-9:
            raise ActionError(f"{t.name} power {new:g} dBm is outside {t.min_power_dbm:g}-{t.max_power_dbm:g} dBm")
        rec.undo["power"] = new - t.power_dbm
        t.power_dbm = new
    elif isinstance(a, TiltChange):
        t = world.towers[a.tower]
        new = t.tilt_deg + a.delta_deg
        if not t.min_tilt_deg - 1e-9 <= new <= t.max_tilt_deg + 1e-9:
            raise ActionError(f"{t.name} tilt {new:g} degrees is outside {t.min_tilt_deg:g}-{t.max_tilt_deg:g}")
        rec.undo["tilt"] = new - t.tilt_deg
        t.tilt_deg = new
    elif isinstance(a, LoadRebalance):
        if a.source == a.target:
            raise ActionError("source and target must differ")
        fwd = world.cio.get((a.source, a.target), 0.0) + a.offset_db
        if abs(fwd) > 10:
            raise ActionError("handover bias can't exceed 10 dB")
        rec.undo["cio"] = a.offset_db
        world.cio[(a.source, a.target)] = fwd
        world.cio[(a.target, a.source)] = world.cio.get((a.target, a.source), 0.0) - a.offset_db
    else:
        raise TypeError(a)
    return rec


def _require_phones(world: World, ues, idx) -> None:
    gone = [u for u in ues if u not in idx]
    if gone:
        raise ActionError(f"phone(s) {gone[:5]} are no longer on the street")


def undo_action(world: World, rec: Applied) -> None:
    """Reverse a fix. Tower settings are undone by subtracting the change that was made, not by
    restoring old values, so undoing one incident's fix never wipes another incident's later change."""
    a = rec.action
    if rec.undo.get("frozen"):
        return
    if isinstance(a, BeamOverride):
        idx = world.ue_index()
        for uid, (lock, reason, beam) in rec.undo.items():
            if uid in idx:
                u = world.ues[idx[uid]]
                u.beam_lock, u.lock_reason, u.beam = lock, reason, beam
    elif isinstance(a, Handover):
        idx = world.ue_index()
        for uid, (serving, beam, lock, reason, forced) in rec.undo.items():
            if uid in idx:
                u = world.ues[idx[uid]]
                u.serving, u.beam, u.beam_lock, u.lock_reason, u.forced_tower = serving, beam, lock, reason, forced
    elif isinstance(a, PowerChange):
        t = world.towers[a.tower]
        t.power_dbm = min(max(t.power_dbm - rec.undo["power"], t.min_power_dbm), t.max_power_dbm)
    elif isinstance(a, TiltChange):
        t = world.towers[a.tower]
        t.tilt_deg = min(max(t.tilt_deg - rec.undo["tilt"], t.min_tilt_deg), t.max_tilt_deg)
    elif isinstance(a, LoadRebalance):
        d = rec.undo["cio"]
        world.cio[(a.source, a.target)] = world.cio.get((a.source, a.target), 0.0) - d
        world.cio[(a.target, a.source)] = world.cio.get((a.target, a.source), 0.0) + d
