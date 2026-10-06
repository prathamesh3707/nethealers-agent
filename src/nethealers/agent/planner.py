"""Planning: list the fixes worth trying for a cause, and rehearse each on the twin.

The candidate list depends on the diagnosed cause. Exact numbers (which
beam, how many dB, which tower) come from a plain search over the twin's
predictions, never from a language model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..sim.actions import (
    Action,
    ActionError,
    BeamOverride,
    Handover,
    LoadRebalance,
    PowerChange,
    TiltChange,
    apply_action,
    describe,
)
from ..sim.world import StepResult, World
from .policy import Policy

REHEARSE_TICKS = 3
GAIN_CLIP = (-10.0, 25.0)  # per-phone change is clipped, so one extreme phone can't dominate the average


def mean_gain(after, before) -> float:
    """Average clarity change per phone (dB), clipped per phone."""
    d = np.clip(np.asarray(after, dtype=float) - np.asarray(before, dtype=float), *GAIN_CLIP)
    return float(d.mean()) if len(d) else 0.0


@dataclass
class Prediction:
    action: Action
    text: str
    gain_db: float  # average clarity change per target phone (clipped), vs doing nothing
    sat_gain: float  # mean change in the share of wanted data the targets get
    after_db: float  # predicted median clarity of the targets afterwards
    harmed: int  # other phones predicted to lose 3 dB or more, or 10% of their data
    other_median_db: float
    zone_loads: dict = field(default_factory=dict)  # protected zone -> predicted load of its tower
    tower_loads: list = field(default_factory=list)
    score: float = 0.0
    zone_loads_if_nothing: dict = field(default_factory=dict)  # protected zone -> its tower's load with no change


def _main_tower(df: pd.DataFrame, phones: list[int]) -> int:
    return int(df.loc[phones].serving.mode().iloc[0])


def candidates(world: World, df: pd.DataFrame, phones: list[int], cause: str, base: StepResult,
               policy: Policy, planned: dict | None = None) -> list[Action]:
    """Fixes worth rehearsing. df: latest snapshot indexed by phone; base: the last tick before the incident."""
    phones = [p for p in phones if p in df.index]
    if not phones:
        return []
    n_t = len(world.towers)
    main = _main_tower(df, phones)
    others = [t for t in range(n_t) if t != main]
    worst_first = df.loc[phones].sort_values("sinr_db").index.tolist()
    movers = tuple(worst_first[: policy.handover_max_phones])
    acts: list[Action] = []

    def handovers(to=others, who=movers):
        # All of them, or only the worst half or third: a smaller move can keep the target tower within limits.
        sizes = sorted({len(who), max(1, len(who) // 2), max(1, len(who) // 3)}, reverse=True)
        acts.extend(Handover(tuple(who[:n]), t) for t in to for n in sizes)

    def beams():
        on_main = df.loc[phones]
        on_main = on_main[(on_main.serving == main) & (on_main.best_beam != on_main.beam)]
        for b, grp in on_main.groupby("best_beam"):
            acts.append(BeamOverride(main, tuple(int(u) for u in grp.index), int(b)))

    def power(t, sign):
        acts.extend(PowerChange(t, sign * s) for s in (1.0, 2.0, 3.0))

    def tilt(t, signs=(-1, 1)):
        acts.extend(TiltChange(t, s * d) for s in signs for d in (1.0, 2.0))

    def restore(t):
        """Put a tower back to its planned settings (whole way, and halfway)."""
        if planned is None:
            return
        p_pow, p_tilt = planned[t]
        tw = world.towers[t]
        dp, dt = p_pow - tw.power_dbm, p_tilt - tw.tilt_deg
        if abs(dp) > 0.5:
            acts.extend([PowerChange(t, round(dp, 1)), PowerChange(t, round(dp / 2, 1))])
        if abs(dt) > 0.5:
            acts.extend([TiltChange(t, round(dt, 1)), TiltChange(t, round(dt / 2, 1))])

    def rebalance(src):
        acts.extend(LoadRebalance(src, t, o) for t in range(n_t) if t != src for o in (3.0, 6.0))

    if cause == "blockage":
        handovers()
        beams()
        power(main, +1)
        tilt(main)
        rebalance(main)
    elif cause == "wrong_beam":
        beams()
        handovers()
    elif cause == "interference":
        # Which other tower got louder at these phones? That's the likely source.
        rise = tower_rise(world, base, phones)
        loud = sorted(others, key=lambda t: -rise[t])[:2]
        for t in loud:
            restore(t)
            power(t, -1)
            tilt(t, signs=(1,))  # tilt the noisy tower down
        handovers(to=loud)
        power(main, +1)
        beams()
    elif cause == "congestion":
        busy = sorted({int(df.loc[p, "serving"]) for p in phones}, key=lambda t: -float(world.last.load[t]))
        for src in busy[:2]:
            rebalance(src)
            on_src = [p for p in movers if int(df.loc[p, "serving"]) == src]
            for t in range(n_t):
                if t != src and on_src:
                    acts.append(Handover(tuple(on_src[: max(1, len(on_src) // 2)]), t))
            for t in range(n_t):
                if t != src:
                    acts.append(PowerChange(t, 2.0))
    else:  # unsure: only low-risk moves
        beams()
        handovers()

    seen, unique = set(), []
    for a in acts:
        if a not in seen:
            seen.add(a)
            unique.append(a)
    return unique


def tower_rise(world: World, base: StepResult, phones: list[int]) -> dict[int, float]:
    """Median change (dB) in each tower's reported strength at these phones since `base`."""
    now = world.last.rsrp_beam_dbm.max(axis=1)
    then = base.rsrp_beam_dbm.max(axis=1)
    idx = world.ue_index()
    base_pos = {int(u): j for j, u in enumerate(base.ue_ids)}
    pairs = [(idx[p], base_pos[p]) for p in phones if p in idx and p in base_pos]
    if not pairs:
        return {t: 0.0 for t in range(len(world.towers))}
    i, j = map(np.array, zip(*pairs))
    return {t: float(np.median(now[t, i] - then[t, j])) for t in range(len(world.towers))}


def rehearse(twin: World, actions: list[Action], targets: list[int], zones=(), ticks: int = REHEARSE_TICKS
             ) -> list[Prediction]:
    """Try each fix on a copy of the twin and compare with doing nothing."""
    ref = twin.copy()
    ref_df = ref.run(ticks).set_index("ue")
    ref_sat = (ref_df.throughput_mbps / ref_df.demand_mbps).clip(upper=1)
    out = []
    for a in actions:
        c = twin.copy()
        try:
            apply_action(c, a)
        except ActionError:
            continue
        df = c.run(ticks).set_index("ue")
        sat = (df.throughput_mbps / df.demand_mbps).clip(upper=1)
        tg = [u for u in targets if u in df.index and u in ref_df.index]
        if not tg:
            continue
        gain = mean_gain(df.loc[tg, "sinr_db"], ref_df.loc[tg, "sinr_db"])
        sat_gain = float((sat.loc[tg] - ref_sat.loc[tg]).mean())
        others = [u for u in df.index if u not in set(tg) and u in ref_df.index]
        d_other = df.loc[others, "sinr_db"] - ref_df.loc[others, "sinr_db"]
        d_other_sat = sat.loc[others] - ref_sat.loc[others]
        harmed = int(((d_other <= -3) | (d_other_sat <= -0.1)).sum())
        zone_loads = {z.name: float(c.last.load[z.tower]) for z in zones}
        p = Prediction(a, describe(twin, a), gain, sat_gain, float(np.median(df.loc[tg, "sinr_db"])), harmed,
                       float(np.median(d_other)) if len(others) else 0.0, zone_loads, c.last.load.round(2).tolist(),
                       zone_loads_if_nothing={z.name: float(ref.last.load[z.tower]) for z in zones})
        p.score = p.gain_db + 15 * p.sat_gain - 3 * p.harmed + min(0.0, 2 * p.other_median_db)
        out.append(p)
    return sorted(out, key=lambda p: -p.score)
