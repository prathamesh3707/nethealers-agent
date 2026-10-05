"""The methods being compared. Each has `on_tick()`, called once after every `world.step()`.

- NoAction: built-in beam management and handover switched off too. The floor.
- Standard: the network on its own (built-in beam management and handover), no agent.
- RuleBased: fixed thresholds, no diagnosis model, no twin, no undo.
- AgentNoTwin: the agent acting on a fixed preference order, then checking (act, then verify).
- Agent: the full agent: diagnosis, twin rehearsal, safety rules, verify and undo.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from ..agent import Agent, EventLog, Policy, SimulatedOperator
from ..sim.actions import ActionError, BeamOverride, Handover, LoadRebalance, apply_action
from ..sim.world import World


class NoAction:
    name = "no_action"

    def __init__(self, world: World, **_):
        self.world = world
        world.builtin_handover = False
        world.builtin_beam_management = False
        self.actions = []

    def on_tick(self):
        return []


class Standard:
    name = "standard"

    def __init__(self, world: World, **_):
        self.world = world
        self.actions = []

    def on_tick(self):
        return []


class RuleBased:
    """If clarity < 0 dB: hand over to the strongest neighbour. If a tower is overloaded: push edge
    phones to the least loaded neighbour. If a better beam is reported by 3 dB: switch to it."""

    name = "rule_based"

    def __init__(self, world: World, react: Callable | None = None, **_):
        self.world = world
        self.react = react
        self.actions = []
        self.last_moved: dict[int, int] = {}
        self.last_rebalance: dict[int, int] = {}

    def _do(self, a):
        try:
            apply_action(self.world, a)
        except ActionError:
            return
        self.actions.append((self.world.tick, a))
        if self.react:
            self.react(self.world, a)

    def on_tick(self):
        w = self.world
        df = w.snapshot()
        cell = w.last.rsrp_beam_dbm.max(axis=1)
        idx = w.ue_index()
        for row in df.itertuples():
            if row.report_age > 0:
                continue
            if row.sinr_db < 0 and w.tick - self.last_moved.get(row.ue, -99) > 5:
                i = idx[row.ue]
                col = cell[:, i].copy()
                col[row.serving] = -np.inf
                best = int(np.argmax(col))
                if col[best] > cell[row.serving, i] - 3:
                    self.last_moved[row.ue] = w.tick
                    self._do(Handover((row.ue,), best))
            elif row.rsrp_dbm - row.beam_rsrp_dbm > 3 and not row.beam_locked:
                self._do(BeamOverride(int(row.serving), (row.ue,), int(row.best_beam)))
        for t in range(len(w.towers)):
            if w.last.load[t] > 1.0 and w.tick - self.last_rebalance.get(t, -99) > 10:
                others = [o for o in range(len(w.towers)) if o != t]
                target = min(others, key=lambda o: w.last.load[o])
                self.last_rebalance[t] = w.tick
                self._do(LoadRebalance(t, target, 3.0))
        return []


class AgentController:
    """Wraps the Agent so scenario hooks see every change it makes."""

    name = "agent"

    def __init__(self, world: World, diagnoser=None, mode: str = "twin", react: Callable | None = None,
                 operator_delay: int = 5, **_):
        self.world = world
        self.agent = Agent(world, diagnoser=diagnoser, policy=Policy.load(), mode=mode,
                           operator=SimulatedOperator(delay=operator_delay), log=EventLog())
        self.react = react
        self.name = "agent" if mode == "twin" else "agent_no_twin"
        self._seen_acts = 0

    @property
    def actions(self):
        return [(e.tick, e.data.get("action")) for e in self.agent.log.events if e.stage == "act"
                and "action" in e.data]

    def on_tick(self):
        events = self.agent.on_tick()
        if self.react:
            for inc in self.agent.incidents.values():
                for att in inc.attempts:
                    if att.tick == self.world.tick and not getattr(att, "_reacted", False):
                        att._reacted = True
                        self.react(self.world, att.applied.action)
        return events


METHODS = {
    "no_action": lambda w, d, react: NoAction(w),
    "standard": lambda w, d, react: Standard(w),
    "rule_based": lambda w, d, react: RuleBased(w, react=react),
    "agent_no_twin": lambda w, d, react: AgentController(w, diagnoser=d, mode="no_twin", react=react),
    "agent": lambda w, d, react: AgentController(w, diagnoser=d, mode="twin", react=react),
}
