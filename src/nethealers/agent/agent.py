"""The self-healing agent: observe, diagnose, rehearse, check, act, verify, undo or withdraw.

Call `agent.on_tick()` once after every `world.step()`. Each incident moves
through these states:

    new -> (diagnose, rehearse, safety check)
        -> verifying            a fix was applied; judge it after a few ticks
        -> waiting_human        a fix needs a person's approval
        -> escalated            nothing safe helps: a person must look
    verifying -> fixed          the real result held up
              -> new            it fell short: undo it and plan again
    fixed -> closing            the cause went away (bus left): withdraw the temporary fix
          -> resolved           the fix is a lasting correction and phones stay healthy
    closing -> resolved

Every step is logged as an Event with a plain-language sentence.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from ..sim.actions import (
    Action,
    ActionError,
    Applied,
    BeamOverride,
    Handover,
    LoadRebalance,
    PowerChange,
    TiltChange,
    apply_action,
    describe,
    undo_action,
)
from ..sim.world import StepResult, World
from .events import Event, EventLog
from .monitor import Monitor, group_phones
from .planner import Prediction, candidates, mean_gain, rehearse, tower_rise
from .policy import Policy
from .rules import APPROVED, NEEDS_APPROVAL, RuleChecker, Verdict
from .twin import TwinTrust, build_twin

ACTIVE = {"new", "verifying", "waiting_human", "fixed", "closing", "false_alarm", "escalated"}
TEMPORARY_CAUSES = {"blockage", "congestion"}
FALSE_ALARM_HOLD = 10
RETRY_AFTER = 10  # seconds after handing a problem over before trying again, if users are still affected
MAX_RETRIES = 3
TIDY_EVERY = 10  # seconds between checks for leftover changes that are no longer needed


@dataclass
class Attempt:
    prediction: Prediction | None
    applied: Applied
    tick: int
    pre_sinr: dict
    pre_sat: dict
    others_pre: dict
    kept: bool | None = None
    measured_gain: float | None = None


@dataclass
class Incident:
    id: str
    opened: int
    phones: list[int]
    first_bad_tick: int
    base_frames: list[pd.DataFrame]
    base_result: StepResult
    main_tower: int
    place: str
    status: str = "new"
    cause: str = "unknown"
    confidence: float = 0.0
    probs: dict = field(default_factory=dict)
    failed: list = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    pending: tuple | None = None  # (Prediction, Verdict) waiting for a person
    waiting_since: int | None = None
    verify_at: int | None = None
    healthy_since: int | None = None
    unhealthy_ticks: int = 0
    closed_tick: int | None = None
    outcome: str | None = None
    hold_until: int | None = None
    focus: list | None = None  # phones still being worked on after a partial fix
    partial_escalated: bool = False
    decision_seconds: list = field(default_factory=list)
    needs_diagnosis: bool = True
    handed_at: int | None = None  # last time it was handed to the operator
    retries: int = 0

    @property
    def kept(self) -> list[Attempt]:
        return [a for a in self.attempts if a.kept]


class Agent:
    def __init__(self, world: World, *, diagnoser=None, policy: Policy | None = None, mode: str = "twin",
                 operator: Callable | None = None, log: EventLog | None = None, name: str = "agent",
                 roles=None):
        """mode: "twin" rehearses every fix first; "no_twin" acts on a fixed preference order and only checks after."""
        self.world = world
        self.diagnoser = diagnoser
        self.policy = policy or Policy.load()
        self.mode = mode
        self.operator = operator
        self.log = log or EventLog()
        self.name = name
        self.roles = roles  # language-model planner and safety adviser (agent/roles.py); None = plain rules
        self.monitor = Monitor()
        self.rules = RuleChecker(self.policy, world)
        self.trust = TwinTrust()
        self.incidents: dict[str, Incident] = {}
        self.faulty_towers: set[int] = set()
        self._next = 1
        self._stale_noted = -100
        self._t_mark = time.perf_counter()
        self._settings = self._snapshot()  # tower settings at the end of the agent's last turn
        self.last_tick_ms = 0.0  # how long the agent's turn took on the latest tick

    # ------------------------------------------------------------------ main entry

    def on_tick(self) -> list[Event]:
        w = self.world
        start = len(self.log.events)
        t_start = self._t_mark = time.perf_counter()
        try:
            self._turn()
        finally:
            self.last_tick_ms = (time.perf_counter() - t_start) * 1000
        return self.log.events[start:]

    def _turn(self) -> None:
        w = self.world
        self._notice_outside_changes()
        for inc in self.incidents.values():
            inc.phones = [p for p in inc.phones if p in w.ue_index()]
        busy = {p for i in self.incidents.values() if i.status in ACTIVE for p in i.phones}
        flagged = self.monitor.observe(w, busy)
        if flagged.stale_ignored and w.tick - self._stale_noted >= 10:
            self._stale_noted = w.tick
            self._say("note", "monitor", f"Ignoring {len(flagged.stale_ignored)} phone(s) whose reports stopped "
                                         "updating: no decisions on out-of-date evidence.",
                      data={"phones": flagged.stale_ignored})
        df = self.monitor.latest()
        for group in group_phones(df, flagged.phones):
            target = self._mergeable(group, df)
            if target is not None:
                self._merge(target, group)
            else:
                self._open(group, flagged.first_tick)

        for inc in list(self.incidents.values()):
            if inc.status not in ACTIVE:
                continue
            if not inc.phones:
                self._close(inc, "cleared", "The affected phones left the area. Closing.")
            elif inc.status == "false_alarm":
                if w.tick >= inc.hold_until:
                    inc.status = "resolved"
            elif inc.status == "new":
                self._diagnose_and_plan(inc)
            elif inc.status == "verifying" and self._zone_guard(inc):
                pass
            elif inc.status == "verifying" and w.tick >= inc.verify_at:
                self._verify(inc)
            elif inc.status == "waiting_human":
                self._ask_operator(inc)
            elif inc.status == "fixed":
                self._watch(inc)
            elif inc.status == "closing" and w.tick >= inc.verify_at:
                self._finish_withdrawal(inc)
            elif inc.status == "escalated":
                self._watch_escalated(inc)
        if w.tick % TIDY_EVERY == 0:
            self._tidy_up()
        self._settings = self._snapshot()

    # ------------------------------------------------------------------ incident lifecycle

    def _open(self, phones: list[int], first_tick: int) -> None:
        window = self.monitor.baseline_window(first_tick)
        if window is None:
            return
        frames, base = window
        base_df = frames[-1].set_index("ue")
        known = [p for p in phones if p in base_df.index]
        main = int(base_df.loc[known].serving.mode().iloc[0]) if known else int(
            self.monitor.latest().set_index("ue").loc[phones].serving.mode().iloc[0])
        inc = Incident(f"INC-{self._next:03d}", self.world.tick, phones, first_tick, frames, base, main,
                       describe_place(self.world, phones))
        self._next += 1
        self.incidents[inc.id] = inc
        now = self.monitor.latest().set_index("ue").loc[phones]
        before = base_df.loc[known] if known else now
        self._say("detect", "monitor",
                  f"{len(phones)} phone(s) {inc.place} lost service: clarity {before.sinr_db.median():.0f} dB "
                  f"before, {now.sinr_db.median():.0f} dB now.", inc,
                  {"phones": phones, "sinr_before": float(before.sinr_db.median()),
                   "sinr_now": float(now.sinr_db.median())})

    def _mergeable(self, group: list[int], df: pd.DataFrame) -> Incident | None:
        """An open incident right next to these phones, on the same tower: probably the same cause spreading."""
        d = df.set_index("ue")
        g = d.loc[group]
        gx, gy, gt = g.x.mean(), g.y.mean(), int(g.serving.mode().iloc[0])
        for inc in self.incidents.values():
            if inc.status not in {"new", "verifying", "fixed", "escalated", "waiting_human"} or inc.cause == "none":
                continue
            ph = [p for p in inc.phones if p in d.index]
            if not ph:
                continue
            ix, iy = d.loc[ph].x.mean(), d.loc[ph].y.mean()
            if ((ix - gx) ** 2 + (iy - gy) ** 2) ** 0.5 < 60 and (gt == inc.main_tower or gt in d.loc[ph].serving.values):
                return inc
        return None

    def _merge(self, inc: Incident, group: list[int]) -> None:
        inc.phones = sorted(set(inc.phones) | set(group))
        self._say("detect", "monitor", f"{len(group)} more phone(s) nearby lost service; adding them to this "
                                       "incident.", inc, {"phones": group})
        if inc.status in ("fixed", "escalated"):
            inc.focus, inc.status, inc.partial_escalated = group, "new", False
            if inc.outcome == "escalated":
                inc.outcome, inc.closed_tick = None, None

    def _zone_breach(self, a: Action) -> str | None:
        """A protected zone's tower over its limit, after a change that pushed load into it."""
        w = self.world
        for z in w.zones:
            pushed = (isinstance(a, Handover) and a.target == z.tower) or \
                     (isinstance(a, LoadRebalance) and a.target == z.tower)
            if pushed and float(w.last.load[z.tower]) > z.max_load:
                self.rules.hold_zone(z.tower, w.tick)
                return f"{z.name}'s tower went over its limit ({float(w.last.load[z.tower]):.2f} > {z.max_load:.2f})"
        return None

    def _zone_guard(self, inc: Incident) -> bool:
        """Every tick after a change: if it pushed a protected zone over its limit, undo it at once."""
        att = inc.attempts[-1]
        breach = self._zone_breach(att.applied.action)
        if not breach:
            return False
        att.kept = False
        undo_action(self.world, att.applied)
        inc.failed.append(att.applied.action)
        self._say("undo", "safety", f"Undid {att.prediction.text if att.prediction else 'the change'} "
                                    f"straight away: {breach}.", inc)
        inc.status = "new"
        self._plan(inc)
        return True

    def _diagnose_and_plan(self, inc: Incident) -> None:
        t0 = time.perf_counter()
        if inc.needs_diagnosis:
            inc.needs_diagnosis = False
            self._diagnose(inc)
            if inc.status != "new":
                return
        self._plan(inc)
        inc.decision_seconds.append(time.perf_counter() - t0)

    def _diagnose(self, inc: Incident) -> None:
        w = self.world
        if self.diagnoser is None:
            inc.cause, inc.confidence = "unknown", 0.0
            self._say("diagnose", "diagnosis", "No diagnosis model loaded: treating the cause as unknown.", inc)
            return
        known = [p for p in inc.phones if p in set(inc.base_frames[-1].ue)]
        if not known:
            inc.cause, inc.confidence = "unknown", 0.0
            return
        rep = self.diagnoser.diagnose(w, inc.base_frames, inc.base_result, phones=known)
        probs = {c[2:]: float(rep[c].mean()) for c in rep.columns if c.startswith("p_")}
        inc.cause = max(probs, key=probs.get)
        inc.confidence = probs[inc.cause]
        inc.probs = probs
        if inc.cause == "none" and self._clearly_worse(known):
            # The model knows no cause for this, but the phones are plainly worse than their own normal (for example
            # stranded on the wrong tower after a configuration change). Don't dismiss it: treat the cause as unknown,
            # so only low-risk moves are tried, and a person is asked because the diagnosis is unsure.
            inc.cause, inc.confidence = "unknown", 0.0
            self._say("diagnose", "diagnosis", "No known cause fits, but these phones are clearly worse than their "
                                               "normal. Treating the cause as unknown: only low-risk moves, with your "
                                               "approval.", inc, {"probs": probs})
            return
        if inc.cause == "none":
            inc.status, inc.hold_until, inc.outcome = "false_alarm", w.tick + FALSE_ALARM_HOLD, "false_alarm"
            inc.closed_tick = w.tick
            self._say("diagnose", "diagnosis", f"Looks like normal variation ({inc.confidence:.0%} sure). "
                                               "No action.", inc, {"probs": probs})
            return
        self._say("diagnose", "diagnosis",
                  f"Likely cause: {inc.cause.replace('_', ' ')} ({inc.confidence:.0%} sure). "
                  f"{self._evidence(inc)}", inc, {"cause": inc.cause, "confidence": inc.confidence, "probs": probs})

    def _plan(self, inc: Incident) -> None:
        w, pol = self.world, self.policy
        df = self.monitor.latest().set_index("ue")
        targets = [p for p in (inc.focus or inc.phones) if p in df.index]
        planned = {t: (self.rules.planned_power[t], self.rules.planned_tilt[t]) for t in self.rules.planned_power}
        acts = [a for a in candidates(w, df, targets, inc.cause, inc.base_result, pol, planned)
                if a not in inc.failed and not (set(_towers(a)) & self.faulty_towers)]
        if not acts:
            return self._escalate(inc, "No fixes left to try for this cause.")
        stale_share = float((df.loc[targets].report_age > pol.max_report_age).mean())

        if self.mode == "twin":
            twin, notes = build_twin(w, inc.base_result, targets)
            assumed = len(notes["assumed_extra_loss"])
            extra = len(notes["assumed_interference"])
            hyp = []
            if assumed:
                hyp.append(f"extra loss on {assumed} tower-phone link(s), as a blocker would cause")
            if extra:
                hyp.append(f"unexplained interference at {extra} phone(s)")
            self._say("rehearse", "twin", "Twin calibrated from earlier phone reports"
                      + (f"; it now assumes {' and '.join(hyp)}." if hyp else "."), inc, notes_json(notes))
            tried = {a: i + 1 for i, a in enumerate(acts)}  # the order the twin tried them in
            preds = rehearse(twin, acts, targets, w.zones)
            if preds:
                b = preds[0]
                self._say("rehearse", "planner",
                          f"Rehearsed {len(preds)} fixes on the twin. Best: {b.text} "
                          f"({b.gain_db:+.1f} dB for these phones, {b.harmed} other phone(s) worse).", inc,
                          {"ranked": [_pred_dict(p, tried.get(p.action)) for p in preds[:40]], "tested": len(preds),
                           "cause": inc.cause})
        else:
            preds = [Prediction(a, describe(w, a), float("nan"), 0.0, float("nan"), 0, 0.0) for a in acts]

        viable, rejected_shown, verdicts = [], 0, []
        for p in preds:
            v = self.rules.check(p.action, w, w.tick, pred=p if self.mode == "twin" else None,
                                 confidence=inc.confidence if self.diagnoser else 1.0,
                                 twin_error_db=self.trust.get(inc.main_tower), stale_share=stale_share)
            verdicts.append({"action": p.text, "status": v.status, "reasons": list(v.reasons)})
            if v.status == "rejected":
                if rejected_shown < 2:
                    self._say("check", "safety", f"Rejected: {p.text}, because {'; '.join(v.reasons)}.", inc,
                              {"action": p.text, "reasons": v.reasons})
                    rejected_shown += 1
                continue
            viable.append((p, v))
            if len(viable) == (4 if self.roles is not None else 1):
                break
        # The safety check goes down the twin's ranking and stops once it has enough safe options;
        # record every verdict so the screen can show each option's fate in rank order.
        self._say("check", "safety", f"Safety check: {len(viable)} of the {len(verdicts)} best-ranked fixes passed.",
                  inc, {"verdicts": verdicts, "shortlist": [p.text for p, _ in viable]})
        chosen = self._choose(inc, viable) if viable else None
        if chosen == "escalated":
            return None
        if chosen is None:
            if inc.kept:
                inc.status, inc.partial_escalated = "fixed", True
                self._say("escalate", "safety", f"{len(targets)} phone(s) are still poor and no further fix passed "
                                                "the safety check. Asking the operator about them; the fixes "
                                                "already made stay in place.", inc)
                return None
            return self._escalate(inc, "No fix passed the safety check.")
        p, v = chosen
        if v.status == APPROVED:
            self._say("check", "safety", f"Approved: {p.text}.", inc, {"action": p.text})
            self._act(inc, p)
        else:
            inc.status, inc.pending, inc.waiting_since = "waiting_human", (p, v), w.tick
            self._say("escalate", "safety", f"Asking a person to approve: {p.text}, because "
                                            f"{'; '.join(v.reasons)}.", inc, {"action": p.text, "reasons": v.reasons})

    def _choose(self, inc: Incident, viable: list):
        """Planner picks among safe options; the safety adviser may object once. Plain rules: take the first."""
        if self.roles is None:
            return viable[0]
        from .roles import option_view

        w = self.world
        summary = {"where": inc.place, "phones_affected": len(inc.focus or inc.phones), "cause": inc.cause,
                   "diagnosis_confidence": round(inc.confidence, 2), "evidence": self._evidence(inc)}
        objection = None
        for _round in range(2):
            options = [option_view(i + 1, p, v, w.zones) for i, (p, v) in enumerate(viable)]
            pick = self.roles.plan(summary, options, objection)
            if not pick.ok:
                self._hand_over(inc, f"Planner: {pick.reason}")
                return "escalated"
            p, v = viable[pick.choice]
            self._say("plan", "planner", f"Planner picked: {p.text}. {pick.reason}", inc,
                      {"action": p.text, "source": pick.source, "options": options})
            hits = self.roles.evidence(summary, options[pick.choice])
            review = self.roles.review(summary, options[pick.choice], hits)
            cites = f" (see {'; '.join(review.citations)})" if review.citations else ""
            if review.ok:
                self._say("review", "safety", f"Safety adviser agrees: {review.reason}{cites}", inc,
                          {"source": review.source, "citations": review.citations})
                return p, v
            self._say("review", "safety", f"Safety adviser objects: {review.reason}{cites}", inc,
                      {"source": review.source, "citations": review.citations})
            objection = review.reason
            viable = [x for i, x in enumerate(viable) if i != pick.choice]
            if not viable:
                break
        self._hand_over(inc, "The planner and safety adviser could not agree on a change.")
        return "escalated"

    def _act(self, inc: Incident, p: Prediction) -> None:
        w = self.world
        df = self.monitor.latest().set_index("ue")
        targets = [u for u in inc.phones if u in df.index]
        sat = (df.throughput_mbps / df.demand_mbps).clip(upper=1)
        expected = _expected_settings(w, p.action)
        try:
            applied = apply_action(w, p.action)
        except ActionError as e:
            inc.failed.append(p.action)
            self._say("act", "executor", f"Could not apply {p.text}: {e}.", inc)
            return self._plan(inc)
        self.rules.record(p.action, w.tick)
        readback = _read_settings(w, p.action)
        if expected is not None and readback != expected:
            for t in _towers(p.action):
                self.faulty_towers.add(t)
            inc.failed.append(p.action)
            names = ", ".join(w.towers[t].name for t in _towers(p.action))
            return self._escalate(inc, f"{names} did not accept the change ({p.text}); its controls may be "
                                       "faulty. Nothing else will be sent to it.")
        others = [u for u in df.index if u not in set(inc.phones)]
        inc.attempts.append(Attempt(p, applied, w.tick, df.loc[targets].sinr_db.to_dict(),
                                    sat.loc[targets].to_dict(), df.loc[others].sinr_db.to_dict()))
        inc.status, inc.verify_at = "verifying", w.tick + self.policy.verify_ticks
        pred = f" (twin predicts {p.gain_db:+.1f} dB)" if np.isfinite(p.gain_db) else ""
        self._say("act", "executor", f"Applied: {p.text}{pred}.", inc, {"action": p.text, "predicted": p.gain_db})

    def _verify(self, inc: Incident) -> None:
        w, pol = self.world, self.policy
        att = inc.attempts[-1]
        df = self.monitor.latest().set_index("ue")
        sat = (df.throughput_mbps / df.demand_mbps).clip(upper=1)
        tg = [u for u in att.pre_sinr if u in df.index]
        measured = mean_gain([df.loc[u, "sinr_db"] for u in tg], [att.pre_sinr[u] for u in tg])
        sat_gain = float(np.mean([sat.loc[u] - att.pre_sat[u] for u in tg])) if tg else 0.0
        healthy = float(np.mean([self.monitor.healthy(u, df.loc[u, "sinr_db"], sat.loc[u]) for u in tg])) if tg else 1
        busy_elsewhere = {p for i in self.incidents.values() if i is not inc and i.status in ACTIVE for p in i.phones}
        # Phones that joined a blockage incident after the fix because the bus was still arriving are victims of
        # the blocker, not of the fix: their own tower's signal fell sharply, which none of the fixes can cause.
        joined = set(inc.phones) - set(att.pre_sinr)
        same_cause = self._blocked_since(inc, joined) if inc.cause == "blockage" else set()
        others = [u for u in att.others_pre if u in df.index and u not in busy_elsewhere and u not in same_cause]
        # Count only harm beyond the general drift: the problem itself may still be pulling everyone down.
        drops = np.array([df.loc[u, "sinr_db"] - att.others_pre[u] for u in others])
        drift = float(np.median(drops)) if len(drops) else 0.0
        harmed = int((drops <= min(drift, 0.0) - 4).sum())
        att.measured_gain = measured
        predicted = att.prediction.gain_db if att.prediction else float("nan")
        moved = _phones_moved(w, att.prediction.action, tg) if att.prediction else True
        need = pol.min_predicted_gain_db * 0.5
        if np.isfinite(predicted):
            need = max(need, pol.keep_if_share_of_prediction * predicted)
            err = self.trust.update(inc.main_tower, predicted, measured)
        else:
            err = None
        worked = (healthy >= 0.8 or measured >= need or sat_gain >= 0.15) and moved
        zone = self._zone_breach(att.prediction.action) if att.prediction else None
        too_harmful = harmed > pol.max_harmed_phones + 2 or zone is not None
        compare = (f"{measured:+.1f} dB measured vs {predicted:+.1f} dB predicted" if np.isfinite(predicted)
                   else f"{measured:+.1f} dB measured")
        if worked and not too_harmful:
            att.kept = True
            inc.status, inc.healthy_since = "fixed", w.tick
            remaining = [u for u in inc.phones if u in df.index
                         and not self.monitor.healthy(u, df.loc[u, "sinr_db"], sat.loc[u])]
            more = len(remaining) >= max(2, 0.2 * len(inc.phones)) and len(inc.attempts) < 2 * pol.max_attempts
            self._say("verify", "verifier", f"Result: {compare}. Kept."
                      + (f" {len(remaining)} phone(s) still poor: looking for another fix for them." if more else ""),
                      inc, {"measured": measured, "predicted": predicted, "twin_error": err, "healthy_share": healthy})
            if more:
                inc.focus, inc.status = remaining, "new"
                self._plan(inc)
            return
        att.kept = False
        undo_action(w, att.applied)
        inc.failed.append(att.prediction.action)
        if zone:
            why = zone
        elif too_harmful:
            why = f"it made {harmed} other phones worse"
        elif not moved:
            why = "the phones didn't follow the change (the tower may not have applied it)"
        else:
            why = "it fell short of the prediction" if np.isfinite(predicted) else "it didn't help enough"
        trust = f" Twin error for {w.towers[inc.main_tower].name} is now {err:.1f} dB." if err is not None else ""
        self._say("undo", "verifier", f"Result: {compare}. Undone, because {why}.{trust}", inc,
                  {"measured": measured, "predicted": predicted, "twin_error": err, "harmed": harmed})
        fails = sum(1 for a in inc.attempts if a.kept is False)
        if fails >= pol.max_attempts:
            if inc.kept:
                inc.status, inc.partial_escalated = "fixed", True
                return self._say("escalate", "safety", f"{fails} further fixes failed. Asking the operator; "
                                                       "earlier fixes stay in place.", inc)
            return self._escalate(inc, f"{fails} fixes tried without success.")
        inc.status = "new"
        self._plan(inc)

    def _clearly_worse(self, phones: list[int]) -> bool:
        """Most of these phones have no usable signal, or are at least 6 dB below their own normal."""
        df = self.monitor.latest().set_index("ue")
        tg = [u for u in phones if u in df.index]
        if not tg:
            return False
        bad = [u for u in tg if df.loc[u, "sinr_db"] < 0
               or df.loc[u, "sinr_db"] < self.monitor.base_sinr.get(u, float("inf")) - 6]
        return len(bad) >= max(1, 0.5 * len(tg))

    def _blocked_since(self, inc: Incident, phones: set) -> set:
        """Phones whose main-tower signal fell more than 8 dB since the incident began (more than any power step)."""
        w, base = self.world, inc.base_result
        now, then = w.last.rsrp_beam_dbm.max(axis=1), base.rsrp_beam_dbm.max(axis=1)
        idx, pos = w.ue_index(), {int(u): j for j, u in enumerate(base.ue_ids)}
        return {p for p in phones if p in idx and p in pos
                and now[inc.main_tower, idx[p]] - then[inc.main_tower, pos[p]] < -8.0}

    def _ask_operator(self, inc: Incident) -> None:
        # If the users recover while the request waits (the cause went away), the change is no longer needed.
        df = self.monitor.latest().set_index("ue")
        sat = (df.throughput_mbps / df.demand_mbps).clip(upper=1)
        tg = [u for u in inc.phones if u in df.index]
        healthy = float(np.mean([self.monitor.healthy(u, df.loc[u, "sinr_db"], sat.loc[u]) for u in tg])) if tg else 1
        inc.unhealthy_ticks = inc.unhealthy_ticks + 1 if healthy >= 0.8 else 0
        if inc.unhealthy_ticks >= 3:
            p, _ = inc.pending
            inc.pending, inc.unhealthy_ticks = None, 0
            self._close(inc, "recovered", f"The phones recovered on their own while waiting, so the request to "
                                          f"{p.text[0].lower() + p.text[1:]} was withdrawn.")
            return
        if self.operator is None:
            return
        p, v = inc.pending
        answer = self.operator(inc, p, v, self.world.tick)
        if answer is None:
            return
        inc.pending = None
        if answer == "approve":
            self._say("approve", "operator", f"Operator approved: {p.text}.", inc)
            # Things may have changed while the request waited (cooldowns, other fixes, zone holds):
            # the rule-checker looks again before anything is sent.
            w = self.world
            df = self.monitor.latest().set_index("ue")
            targets = [u for u in (inc.focus or inc.phones) if u in df.index]
            stale = float((df.loc[targets].report_age > self.policy.max_report_age).mean()) if targets else 0.0
            again = self.rules.check(p.action, w, w.tick, pred=p if self.mode == "twin" else None,
                                     confidence=inc.confidence if self.diagnoser else 1.0,
                                     twin_error_db=self.trust.get(inc.main_tower), stale_share=stale)
            if again.status == "rejected":
                inc.failed.append(p.action)
                self._say("check", "safety", f"Re-checked after approval and stopped it: {p.text}, because "
                                             f"{'; '.join(again.reasons)}.", inc,
                          {"action": p.text, "reasons": again.reasons})
                inc.status = "new"
                return self._plan(inc)
            self._act(inc, p)
        else:
            inc.failed.append(p.action)
            self._say("approve", "operator", f"Operator declined: {p.text}.", inc)
            inc.status = "new"
            self._plan(inc)

    def _watch(self, inc: Incident) -> None:
        """A fix is in place. Withdraw it when the cause goes away; reopen if it stops working."""
        w = self.world
        df = self.monitor.latest().set_index("ue")
        sat = (df.throughput_mbps / df.demand_mbps).clip(upper=1)
        tg = [u for u in inc.phones if u in df.index]
        healthy = float(np.mean([self.monitor.healthy(u, df.loc[u, "sinr_db"], sat.loc[u]) for u in tg])) if tg else 1
        for att in inc.kept:
            breach = self._zone_breach(att.prediction.action) if att.prediction else None
            if breach:
                undo_action(w, att.applied)
                att.kept = False
                inc.failed.append(att.prediction.action)
                self._say("undo", "safety", f"Undid {att.prediction.text}: {breach}.", inc)
                inc.status, inc.focus = "new", None
                self._plan(inc)
                return
        if inc.cause in TEMPORARY_CAUSES and self._cause_gone(inc, df):
            names = "; ".join(a.prediction.text for a in inc.kept if a.prediction)
            for att in reversed(inc.kept):
                undo_action(w, att.applied)
                att.kept = False  # withdrawn: no longer one of the agent's active changes
            reason = ("the old tower's signal is back (the blocker has gone)" if inc.cause == "blockage"
                      else "the crowd has thinned out")
            self._say("withdraw", "executor", f"Withdrew the temporary fix ({names}) because {reason}.", inc)
            inc.status, inc.verify_at = "closing", w.tick + self.policy.verify_ticks
            return
        if healthy < 0.5 and not inc.partial_escalated:
            inc.unhealthy_ticks += 1
            if inc.unhealthy_ticks >= 3:
                inc.unhealthy_ticks = 0
                self._say("note", "monitor", "The fix stopped working; planning again.", inc)
                inc.status = "new"
                self._plan(inc)
            return
        inc.unhealthy_ticks = 0
        if inc.cause not in TEMPORARY_CAUSES and w.tick - inc.healthy_since >= 5:
            self._close(inc, "fixed", f"Phones have been healthy for {w.tick - inc.healthy_since} s. "
                                      "The correction stays in place.")

    def _watch_escalated(self, inc: Incident) -> None:
        """Nothing was done; close the incident once the phones recover by themselves."""
        df = self.monitor.latest().set_index("ue")
        sat = (df.throughput_mbps / df.demand_mbps).clip(upper=1)
        tg = [u for u in inc.phones if u in df.index]
        healthy = float(np.mean([self.monitor.healthy(u, df.loc[u, "sinr_db"], sat.loc[u]) for u in tg])) if tg else 1
        inc.unhealthy_ticks = 0 if healthy < 0.8 else inc.unhealthy_ticks + 1
        if inc.unhealthy_ticks >= 3:
            inc.status = "resolved"
            self._say("resolve", "monitor", "The phones recovered without any change from the agent.", inc)
        elif healthy < 0.8 and not self._retry(inc) and inc.retries >= MAX_RETRIES \
                and w_tick_since(self.world, inc.handed_at) >= 2 * RETRY_AFTER:
            inc.status = "resolved"
            self._say("resolve", "monitor", f"Still not fixed after {MAX_RETRIES} retries: leaving it with the operator. "
                                            "The monitor raises it again if service gets worse.", inc)

    def _retry(self, inc: Incident) -> bool:
        """Handed over but users are still affected: conditions change (the cause may have gone or changed,
        cooldowns run out), so after a while diagnose and plan again instead of waiting forever."""
        w = self.world
        since = inc.handed_at if inc.handed_at is not None else inc.opened
        if inc.retries >= MAX_RETRIES or w.tick - since < RETRY_AFTER or inc.kept:
            return False
        inc.retries += 1
        df = self.monitor.latest().set_index("ue")
        sat = (df.throughput_mbps / df.demand_mbps).clip(upper=1)
        still = [u for u in inc.phones if u in df.index and not self.monitor.healthy(u, df.loc[u, "sinr_db"], sat.loc[u])]
        self._say("note", "monitor", f"{len(still)} phone(s) still affected {w.tick - since} s after handing over. "
                                     f"Things may have changed, so diagnosing and planning again (retry {inc.retries} "
                                     f"of {MAX_RETRIES}).", inc)
        # Fixes that already failed or breached a limit stay excluded: only new options are tried.
        inc.status, inc.outcome, inc.closed_tick = "new", None, None
        inc.focus = still or None
        inc.cause, inc.needs_diagnosis = "unknown", True
        return True

    def _cause_gone(self, inc: Incident, df: pd.DataFrame) -> bool:
        if inc.cause == "blockage":
            return tower_rise(self.world, inc.base_result, inc.phones)[inc.main_tower] > -4.0
        if inc.cause == "congestion":
            # Count phones around the incident, now vs before (positions are roughly known to the network).
            base = inc.base_frames[-1]
            pts = base.set_index("ue").loc[[p for p in inc.phones if p in set(base.ue)], ["x", "y"]]
            if pts.empty:
                return False
            cx, cy = pts.x.mean(), pts.y.mean()
            near = lambda f: int((((f.x - cx) ** 2 + (f.y - cy) ** 2) ** 0.5 < 60).sum())  # noqa: E731
            return near(df) <= near(base) * 1.2 + 2
        return False

    def _finish_withdrawal(self, inc: Incident) -> None:
        df = self.monitor.latest().set_index("ue")
        sat = (df.throughput_mbps / df.demand_mbps).clip(upper=1)
        tg = [u for u in inc.phones if u in df.index]
        healthy = float(np.mean([self.monitor.healthy(u, df.loc[u, "sinr_db"], sat.loc[u]) for u in tg])) if tg else 1
        self._close(inc, "withdrawn", f"Checked after withdrawing: {healthy:.0%} of the phones are healthy"
                                      f"{'' if healthy >= 0.8 else '; the monitor will reopen if needed'}.")

    def _hand_over(self, inc: Incident, why: str) -> None:
        """Ask a person, but keep looking after fixes already in place (withdraw them when the cause goes away,
        undo them if they breach a protected zone) instead of abandoning them."""
        if inc.kept:
            inc.status, inc.partial_escalated = "fixed", True
            self._say("escalate", "safety", f"{why} Asking the operator about the remaining phones; the fixes already "
                                            "made stay in place and are still watched.", inc)
        else:
            self._escalate(inc, why)

    def _escalate(self, inc: Incident, why: str) -> None:
        inc.status, inc.outcome, inc.closed_tick = "escalated", "escalated", self.world.tick
        self._say("escalate", "safety", f"{why} Asking the operator to take over.", inc)

    def _close(self, inc: Incident, outcome: str, text: str) -> None:
        inc.status, inc.outcome, inc.closed_tick = "resolved", outcome, self.world.tick
        self._say("resolve", "verifier", text, inc)

    # ------------------------------------------------------------------ helpers

    def _say(self, stage: str, agent: str, text: str, inc: Incident | None = None, data: dict | None = None):
        """Log a step. `ms` is the time spent since the previous step this tick: the work behind this one."""
        if stage == "escalate" and inc is not None:
            inc.handed_at = self.world.tick
        now = time.perf_counter()
        ms, self._t_mark = (now - self._t_mark) * 1000, now
        return self.log.add(Event(self.world.tick, stage, agent, text, inc.id if inc else None, data or {},
                                  round(ms, 1)))

    # ------------------------------------------------------------------ keeping its own changes honest

    def _snapshot(self) -> dict:
        return {"towers": {t.id: (round(t.power_dbm, 6), round(t.tilt_deg, 6)) for t in self.world.towers},
                "cio": {k: round(v, 6) for k, v in self.world.cio.items()}}

    def _active_changes(self) -> list[tuple[Incident, Attempt]]:
        return [(inc, att) for inc in self.incidents.values() for att in inc.attempts
                if att.kept and not att.applied.undo.get("frozen")]

    def _notice_outside_changes(self) -> None:
        """Tower settings that changed between the agent's turns were changed by someone else (a technician
        fixing a fault, say). The agent's own earlier adjustments to those towers no longer hold, so it stops
        counting them as its changes (and never 'undoes' them on top of the new settings)."""
        now = self._snapshot()
        changed = [t for t, v in now["towers"].items() if self._settings["towers"].get(t) != v]
        if not changed:
            return
        dropped = []
        for inc, att in self._active_changes():
            a = att.applied.action
            if isinstance(a, (PowerChange, TiltChange)) and a.tower in changed:
                att.kept = None
                dropped.append((inc, att))
        names = ", ".join(self.world.towers[t].name for t in changed)
        if dropped:
            for inc, att in dropped:
                self._say("note", "monitor", f"{names} settings were changed outside the agent; its earlier change "
                                             f"({att.prediction.text if att.prediction else 'adjustment'}) no longer "
                                             "applies and is dropped from its records.", inc)

    def _tidy_up(self) -> None:
        """When things are calm, check each change the agent left in place: if the twin predicts that removing it
        makes nobody worse, it is no longer needed, so remove it. One change per check, newest first."""
        if any(i.status in ("new", "verifying", "waiting_human", "closing") for i in self.incidents.values()):
            return
        changes = [(inc, att) for inc, att in self._active_changes() if inc.status in ("resolved", "escalated")]
        if not changes or self.diagnoser is None and self.mode != "twin":
            return
        w = self.world
        for inc, att in sorted(changes, key=lambda x: -x[1].tick):
            twin, _ = build_twin(w, w.last, [])
            ref, test = twin.copy(), twin.copy()
            try:
                undo_action(test, att.applied)
            except Exception:
                continue
            a_df, b_df = ref.run(3).set_index("ue"), test.run(3).set_index("ue")
            common = [u for u in a_df.index if u in b_df.index]
            d = b_df.loc[common, "sinr_db"] - a_df.loc[common, "sinr_db"]
            sa = (a_df.loc[common, "throughput_mbps"] / a_df.loc[common, "demand_mbps"]).clip(upper=1)
            sb = (b_df.loc[common, "throughput_mbps"] / b_df.loc[common, "demand_mbps"]).clip(upper=1)
            harmed = int(((d <= -3) | (sb - sa <= -0.1)).sum())
            if harmed or float(d.median()) < -0.5:
                continue
            undo_action(w, att.applied)
            att.kept = False
            self.rules.record(att.applied.action, w.tick)
            text = att.prediction.text if att.prediction else "an earlier change"
            self._say("withdraw", "executor", f"Tidy-up: removed {text}. It is no longer needed: the twin predicts "
                                              f"nobody gets worse without it (median {float(d.median()):+.1f} dB).",
                      inc, {"action": text})
            return

    def _evidence(self, inc: Incident) -> str:
        w = self.world
        rise = tower_rise(w, inc.base_result, inc.phones)
        main = w.towers[inc.main_tower].name
        df = self.monitor.latest().set_index("ue").loc[inc.phones]
        base = inc.base_frames[-1].set_index("ue")
        known = [p for p in inc.phones if p in base.index]
        if inc.cause == "blockage":
            return f"{main}'s signal fell {abs(rise[inc.main_tower]):.0f} dB at these phones."
        if inc.cause == "interference":
            others = {t: r for t, r in rise.items() if t != inc.main_tower}
            t = max(others, key=others.get) if others else None
            if t is not None and others[t] > 2:
                return f"{w.towers[t].name} got {others[t]:.0f} dB louder at these phones."
            return "No tower got louder, so the noise may come from outside the network."
        if inc.cause == "congestion":
            load = float(w.last.load[inc.main_tower])
            before = int((inc.base_frames[-1].serving == inc.main_tower).sum())
            now = int((self.monitor.latest().serving == inc.main_tower).sum())
            return f"{main} now serves {now} phones (was {before}) and needs {load:.1f}x its capacity."
        if inc.cause == "wrong_beam" and known:
            gap = float((df.rsrp_dbm - df.beam_rsrp_dbm).median())
            return f"Phones report a beam {gap:.0f} dB stronger than the one in use."
        return ""

    def summary(self) -> pd.DataFrame:
        rows = []
        for i in self.incidents.values():
            rows.append({"incident": i.id, "opened": i.opened, "phones": len(i.phones), "cause": i.cause,
                         "confidence": round(i.confidence, 2), "status": i.status, "outcome": i.outcome,
                         "attempts": len(i.attempts), "kept": len(i.kept), "closed": i.closed_tick})
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------- small helpers

def w_tick_since(world: World, tick: int | None) -> int:
    return world.tick - tick if tick is not None else 0


def _towers(a: Action) -> list[int]:
    if isinstance(a, (BeamOverride, PowerChange, TiltChange)):
        return [a.tower]
    if isinstance(a, Handover):
        return [a.target]
    return [a.source, a.target]


def _expected_settings(w: World, a: Action):
    if isinstance(a, PowerChange):
        return round(w.towers[a.tower].power_dbm + a.delta_db, 6)
    if isinstance(a, TiltChange):
        return round(w.towers[a.tower].tilt_deg + a.delta_deg, 6)
    if isinstance(a, LoadRebalance):
        return round(w.cio.get((a.source, a.target), 0.0) + a.offset_db, 6)
    return None


def _read_settings(w: World, a: Action):
    """Read the setting back from the tower, as an operator's management system would."""
    if isinstance(a, PowerChange):
        return round(w.towers[a.tower].power_dbm, 6)
    if isinstance(a, TiltChange):
        return round(w.towers[a.tower].tilt_deg, 6)
    if isinstance(a, LoadRebalance):
        return round(w.cio.get((a.source, a.target), 0.0), 6)
    return None


def _phones_moved(w: World, a: Action, phones: list[int]) -> bool:
    """For handovers and beam overrides: did the phones actually end up where we sent them?"""
    idx = w.ue_index()
    if isinstance(a, Handover):
        on = [w.ues[idx[u]].serving == a.target for u in a.ues if u in idx]
        return bool(on) and np.mean(on) >= 0.5
    if isinstance(a, BeamOverride):
        on = [w.ues[idx[u]].beam == a.beam for u in a.ues if u in idx]
        return bool(on) and np.mean(on) >= 0.5
    return True


def _pred_dict(p: Prediction, tried: int | None = None) -> dict:
    return {"action": p.text, "tried": tried, "gain_db": round(p.gain_db, 1), "harmed": p.harmed, "data_gain": round(p.sat_gain, 2),
            "zone_loads": {k: round(v, 2) for k, v in p.zone_loads.items()}, "score": round(p.score, 1)}


def notes_json(notes: dict) -> dict:
    return {"calibrated_links": notes["calibrated_links"],
            "assumed_extra_loss": {f"{t}:{u}": v for (t, u), v in notes["assumed_extra_loss"].items()},
            "assumed_interference": {str(u): v for u, v in notes["assumed_interference"].items()}}


def describe_place(world: World, phones: list[int]) -> str:
    """'near the Glass office', or 'around 230 m along the street'."""
    idx = world.ue_index()
    pts = np.array([[world.ues[idx[p]].x, world.ues[idx[p]].y] for p in phones if p in idx])
    if not len(pts):
        return ""
    cx, cy = pts.mean(axis=0)
    groups = [world.ues[idx[p]].group for p in phones if p in idx]
    top = max(set(groups), key=groups.count)
    if groups.count(top) >= 0.6 * len(groups):
        if top == "bus_stop":
            return "at the bus stop"
        if top == "hospital":
            return "outside the hospital"
    best, dist = None, 1e9
    for b in world.boxes:
        if b.kind != "building":
            continue
        dx = max(b.xmin - cx, 0, cx - b.xmax)
        dy = max(b.ymin - cy, 0, cy - b.ymax)
        d = (dx * dx + dy * dy) ** 0.5
        if d < dist:
            best, dist = b.name, d
    if best and dist < 40 and not best.startswith(("B", "S")):
        return f"near the {best}"
    return f"on the street ({cx:.0f} m, {cy:.0f} m)"


class SimulatedOperator:
    """Stands in for a person in tests: answers after `delay` ticks."""

    def __init__(self, delay: int = 5, approve: bool = True):
        self.delay, self.approve = delay, approve
        self.answered = 0

    def __call__(self, inc: Incident, p: Prediction, v: Verdict, tick: int):
        if tick - inc.waiting_since < self.delay:
            return None
        self.answered += 1
        return "approve" if self.approve else "reject"
