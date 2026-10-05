"""Run one scenario with one method and score it against the hidden truth.

A phone counts as degraded at a tick if its true clarity is 4 dB below its
own pre-problem normal and below "good" (13 dB), or it gets less than 80%
of the data it wants when it used to get almost all of it. Phones that only
arrived after the problem started (a crowd) aren't counted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..agent import Policy
from ..sim.actions import Handover, LoadRebalance, PowerChange, TiltChange
from .controllers import METHODS
from .scenarios import LENGTH, SCENARIOS, START

SCENARIO_BY_KEY = {s.key: s for s in SCENARIOS}
_DIAGNOSER = None


def _diagnoser():
    global _DIAGNOSER
    if _DIAGNOSER is None:
        import torch

        from ..diagnosis import Diagnoser

        torch.set_num_threads(1)
        _DIAGNOSER = Diagnoser.load()
    return _DIAGNOSER


def _mean(xs: list) -> float:
    return float(np.mean(xs)) if xs else float("nan")


def _controller_actions(ctrl) -> list[tuple[int, object]]:
    if hasattr(ctrl, "agent"):
        return [(att.tick, att.applied.action) for inc in ctrl.agent.incidents.values() for att in inc.attempts]
    return list(ctrl.actions)


def run_one(scenario: str, method: str, seed: int) -> dict:
    sc = SCENARIO_BY_KEY[scenario]
    script = sc.build(seed)
    w = script.world
    needs_model = method.startswith("agent")
    ctrl = METHODS[method](w, _diagnoser() if needs_model else None, script.react)
    policy = Policy.load()
    planned = {t.id: (t.power_dbm, t.tilt_deg) for t in w.towers}
    frames, latency = [], []
    violations = {"limits": 0, "zone": 0}
    for _ in range(LENGTH):
        for fn in script.events.get(w.tick + 1, []):
            fn(w)
        w.step()
        t0 = time.perf_counter()
        ctrl.on_tick()
        latency.append(time.perf_counter() - t0)
        frames.append(w.snapshot()[["tick", "ue", "true_sinr_db", "throughput_mbps", "demand_mbps", "serving"]])
        # Independent safety audit of what the controller changed (faults injected by the scenario don't count).
        recent = [a for t, a in _controller_actions(ctrl) if w.tick - 3 <= t <= w.tick]
        for t, a in _controller_actions(ctrl):
            if t != w.tick:
                continue
            if isinstance(a, PowerChange):
                tw = w.towers[a.tower]
                if not tw.min_power_dbm <= tw.power_dbm <= tw.max_power_dbm or \
                        abs(tw.power_dbm - planned[tw.id][0]) > policy.power_total_db + 1e-9:
                    violations["limits"] += 1
            if isinstance(a, TiltChange):
                tw = w.towers[a.tower]
                if abs(tw.tilt_deg - planned[tw.id][1]) > policy.tilt_total_deg + 1e-9:
                    violations["limits"] += 1
            if isinstance(a, LoadRebalance) and abs(w.cio.get((a.source, a.target), 0)) > policy.rebalance_total_db:
                violations["limits"] += 1
        for z in w.zones:
            pushed = any((isinstance(a, Handover) and a.target == z.tower) or
                         (isinstance(a, LoadRebalance) and a.target == z.tower) for a in recent)
            if pushed and w.last.load[z.tower] > z.max_load:
                violations["zone"] += 1

    truth = pd.concat(frames, ignore_index=True)
    truth["sat"] = (truth.throughput_mbps / truth.demand_mbps).clip(upper=1)
    pre = truth[(truth.tick >= START - 6) & (truth.tick < START)]
    base = pre.groupby("ue").agg(base_sinr=("true_sinr_db", "mean"), base_sat=("sat", "mean"))
    truth = truth.merge(base, left_on="ue", right_index=True, how="inner")
    truth["degraded"] = (((truth.true_sinr_db < truth.base_sinr - 4) & (truth.true_sinr_db < 13))
                         | ((truth.sat < 0.8) & (truth.base_sat >= 0.95)))
    per_tick = truth.groupby("tick").degraded.sum().reindex(range(1, LENGTH + 1), fill_value=0)
    window = per_tick.loc[START:script.measure_until - 1]
    peak = int(window.max()) if len(window) else 0
    rec = None
    if peak == 0:
        rec = 0
    else:
        ok = window <= max(1, 0.2 * peak)
        ticks = list(window.index)
        for i in range(len(ticks) - 2):
            if ok.iloc[i] and ok.iloc[i + 1] and ok.iloc[i + 2] and ticks[i] > window.idxmax() - 1:
                rec = ticks[i] - START
                break
    degraded_sets = {int(t): sorted(map(int, g.ue[g.degraded])) for t, g in truth.groupby("tick")}

    out = {
        "scenario": scenario, "method": method, "seed": seed, "label": script.label,
        "degraded_phone_seconds": int(window.sum()), "peak_degraded": peak,
        # After a temporary cause (the bus) has gone: does service return to normal, or do leftover changes hurt?
        "aftermath_phone_seconds": int(per_tick.loc[script.measure_until + 4:].sum())
        if script.measure_until < LENGTH else 0,
        "recovery_s": rec, "recovered": rec is not None,
        "still_degraded_at_end": int(window.iloc[-1]) if len(window) else 0,
        "actions": len(_controller_actions(ctrl)),
        "limit_violations": violations["limits"], "zone_violations": violations["zone"],
        "mean_decision_ms": 1000 * float(np.mean(latency)), "max_decision_ms": 1000 * float(np.max(latency)),
        "per_tick": per_tick.tolist(), "degraded_sets": degraded_sets,
    }
    if hasattr(ctrl, "agent"):
        ag = ctrl.agent
        incs = list(ag.incidents.values())
        real = [i for i in incs if i.outcome != "false_alarm"]
        ev = ag.log.events
        out.update({
            "incidents": len(real), "false_alarms": sum(i.outcome == "false_alarm" for i in incs),
            "diagnosis": real[0].cause if real else "none",
            "diagnosis_correct": (real[0].cause == script.label) if real else script.label == "none",
            "undos": sum(e.stage == "undo" for e in ev), "escalations": sum(e.stage == "escalate" for e in ev),
            "withdrawals": sum(e.stage == "withdraw" for e in ev),
            "operator_answers": ag.operator.answered if ag.operator else 0,
            "twin_error_db": _mean([abs(e.data["predicted"] - e.data["measured"]) for e in ev
                                    if e.stage in ("verify", "undo") and e.data.get("predicted") is not None
                                    and np.isfinite(e.data["predicted"])]),
            "events": [e.to_dict() for e in ev],
        })
    return out
