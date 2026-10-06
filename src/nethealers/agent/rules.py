"""The rule-checker: plain code, no AI, final say on every change.

It checks a proposed fix against the operator's policy (config/policy.yaml):
step sizes, how far a tower may drift from its planned settings, legal
power limits, cooldowns, predicted harm to other phones, protected zones,
and the twin's track record. Then it decides how much freedom the agent
has: act alone, act only with small steps, or ask a person.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..sim.actions import Action, BeamOverride, Handover, LoadRebalance, PowerChange, TiltChange
from ..sim.world import World
from .planner import Prediction
from .policy import Policy

APPROVED, NEEDS_APPROVAL, REJECTED = "approved", "needs_approval", "rejected"
ZONE_MARGIN = 0.08  # stay this far below a protected zone's limit: the twin is never exact
ZONE_HOLD_TICKS = 10  # after a zone goes over its limit, push nothing more into its tower for this long


@dataclass
class Verdict:
    status: str
    reasons: list[str] = field(default_factory=list)  # why rejected, or why a person must approve
    small: bool = True

    @property
    def ok(self) -> bool:
        return self.status == APPROVED


def kind_of(a: Action) -> str:
    return {BeamOverride: "beam", Handover: "handover", PowerChange: "power", TiltChange: "tilt",
            LoadRebalance: "rebalance"}[type(a)]


def towers_touched(a: Action) -> list[int]:
    if isinstance(a, (BeamOverride, PowerChange, TiltChange)):
        return [a.tower]
    if isinstance(a, Handover):
        return [a.target]
    return [a.source, a.target]


class RuleChecker:
    def __init__(self, policy: Policy, world: World):
        self.policy = policy
        self.planned_power = {t.id: t.power_dbm for t in world.towers}
        self.planned_tilt = {t.id: t.tilt_deg for t in world.towers}
        self.last_change: dict[tuple[int, str], int] = {}
        self.zone_hold_until: dict[int, int] = {}  # tower id -> tick

    def hold_zone(self, tower: int, tick: int) -> None:
        self.zone_hold_until[tower] = tick + ZONE_HOLD_TICKS

    def record(self, a: Action, tick: int) -> None:
        for t in towers_touched(a):
            self.last_change[(t, kind_of(a))] = tick

    def check(self, a: Action, world: World, tick: int, *, pred: Prediction | None = None,
              confidence: float = 1.0, twin_error_db: float = 0.0, stale_share: float = 0.0) -> Verdict:
        p, why = self.policy, []

        # Evidence
        if stale_share > 0.5:
            why.append(f"most of these phones' reports are out of date ({stale_share:.0%})")

        # Size of the step and total drift from the planned settings. Moving a tower back toward its
        # planned (known-good) settings may take a bigger step: it undoes drift instead of adding it.
        restoring = self.toward_plan(a, world)
        if isinstance(a, PowerChange):
            t = world.towers[a.tower]
            new = t.power_dbm + a.delta_db
            if abs(a.delta_db) > p.power_step_db and not restoring:
                why.append(f"power step {a.delta_db:+g} dB is larger than {p.power_step_db:g} dB")
            if abs(new - self.planned_power[t.id]) > p.power_total_db and not restoring:
                why.append(f"{t.name} would be {new - self.planned_power[t.id]:+g} dB from its planned power "
                           f"(limit ±{p.power_total_db:g})")
            if not t.min_power_dbm <= new <= t.max_power_dbm:
                why.append(f"{t.name} power {new:g} dBm is outside the legal range "
                           f"{t.min_power_dbm:g}-{t.max_power_dbm:g} dBm")
        if isinstance(a, TiltChange):
            t = world.towers[a.tower]
            new = t.tilt_deg + a.delta_deg
            if abs(a.delta_deg) > p.tilt_step_deg and not restoring:
                why.append(f"tilt step {a.delta_deg:+g} degrees is larger than {p.tilt_step_deg:g}")
            if abs(new - self.planned_tilt[t.id]) > p.tilt_total_deg and not restoring:
                why.append(f"{t.name} tilt would drift {new - self.planned_tilt[t.id]:+g} degrees from plan "
                           f"(limit ±{p.tilt_total_deg:g})")
            if not t.min_tilt_deg <= new <= t.max_tilt_deg:
                why.append(f"{t.name} tilt {new:g} degrees is outside {t.min_tilt_deg:g}-{t.max_tilt_deg:g}")
        if isinstance(a, LoadRebalance):
            total = world.cio.get((a.source, a.target), 0.0) + a.offset_db
            if abs(a.offset_db) > p.rebalance_step_db:
                why.append(f"load shift {a.offset_db:+g} dB is larger than {p.rebalance_step_db:g} dB")
            if abs(total) > p.rebalance_total_db:
                why.append(f"total load shift would reach {total:+g} dB (limit ±{p.rebalance_total_db:g})")
        if isinstance(a, (Handover, BeamOverride)) and len(a.ues) > p.handover_max_phones:
            why.append(f"{len(a.ues)} phones in one move is more than {p.handover_max_phones}")

        # A protected zone that recently went over its limit takes no more load for a while.
        into = a.target if isinstance(a, (Handover, LoadRebalance)) else None
        if into is not None and tick < self.zone_hold_until.get(into, -1):
            why.append(f"{world.towers[into].name} serves a protected zone that went over its limit "
                       f"{tick - (self.zone_hold_until[into] - ZONE_HOLD_TICKS)} s ago")

        # Cooldown
        k = kind_of(a)
        for t in towers_touched(a):
            last = self.last_change.get((t, k))
            if last is not None and tick - last < p.cooldown_ticks.get(k, 0):
                why.append(f"{world.towers[t].name} {k} changed {tick - last} s ago "
                           f"(wait {p.cooldown_ticks[k]} s)")

        # Predicted effect
        if pred is not None:
            need = p.min_predicted_gain_db + p.twin_error_margin * twin_error_db
            if pred.gain_db < need and pred.sat_gain < 0.15:
                why.append(f"predicted gain {pred.gain_db:+.1f} dB is below the {need:.1f} dB needed")
            if pred.harmed > p.max_harmed_phones:
                why.append(f"would hurt {pred.harmed} other phones (limit {p.max_harmed_phones})")
            if pred.other_median_db < p.min_median_change_db:
                why.append(f"other phones would lose {abs(pred.other_median_db):.1f} dB on average")
            for z in world.zones:
                load = pred.zone_loads.get(z.name)
                now = float(world.last.load[z.tower])
                pushes = isinstance(a, (Handover, LoadRebalance)) and a.target == z.tower
                if not pushes:
                    # A change that doesn't move phones onto the zone's tower is judged against the twin doing
                    # nothing (the twin may not know a crowd's exact demand), so relief isn't blocked. Moves onto
                    # the zone's tower keep the stricter test against the measured load.
                    now = pred.zone_loads_if_nothing.get(z.name, now)
                if load is not None and load > z.max_load - ZONE_MARGIN and load > now + 0.02:
                    why.append(f"{z.name} tower load would reach {load:.2f} (limit {z.max_load:.2f}, "
                               f"kept {ZONE_MARGIN:.2f} below it for safety)")
        if why:
            return Verdict(REJECTED, why, self.is_small(a))

        # Freedom to act
        small = self.is_small(a) or restoring
        if confidence >= p.act_alone and small:
            return Verdict(APPROVED, [], small)
        if p.act_small <= confidence < p.act_alone and small:
            return Verdict(APPROVED, [], small)
        reasons = []
        if not small:
            reasons.append("this change is bigger than the agent may make alone")
        if confidence < p.act_small:
            reasons.append(f"diagnosis is only {confidence:.0%} sure")
        elif confidence < p.act_alone and not small:
            reasons.append(f"diagnosis is {confidence:.0%} sure, so only small changes are automatic")
        return Verdict(NEEDS_APPROVAL, reasons, small)

    def toward_plan(self, a: Action, world: World) -> bool:
        """True if the change brings a tower closer to its planned settings without overshooting."""
        if isinstance(a, PowerChange):
            now = world.towers[a.tower].power_dbm
            gap = self.planned_power[a.tower] - now
            return gap != 0 and a.delta_db * gap > 0 and abs(a.delta_db) <= abs(gap) + 1e-9
        if isinstance(a, TiltChange):
            now = world.towers[a.tower].tilt_deg
            gap = self.planned_tilt[a.tower] - now
            return gap != 0 and a.delta_deg * gap > 0 and abs(a.delta_deg) <= abs(gap) + 1e-9
        return False

    def is_small(self, a: Action) -> bool:
        p = self.policy
        if isinstance(a, BeamOverride):
            return p.beam_override_auto
        if isinstance(a, Handover):
            return p.handover_auto
        if isinstance(a, PowerChange):
            return abs(a.delta_db) <= p.power_auto_db
        if isinstance(a, TiltChange):
            return abs(a.delta_deg) <= p.tilt_auto_deg
        return abs(a.offset_db) <= p.rebalance_auto_db
