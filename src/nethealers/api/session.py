"""A game session: one street, its clock, the agent, and the player as the operator.

The clock runs in the background (one tick per `1/speed` seconds). Each tick
the street moves on, then the agent takes its turn; while the agent thinks
(a language-model call can take a few seconds) the street waits, so the
side panel never falls behind what's on screen.

Everything the player does (drop a bus, approve a fix) goes through a lock,
so it never lands in the middle of a tick.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field

import numpy as np

from ..agent import Agent, EventLog, Policy, Roles
from ..sim import (
    add_blocker,
    add_external_interferer,
    clear_problem,
    crowd_surge,
    misconfigure_tower,
    station_road,
    stick_beams,
)
from ..sim.config import BLOCKER_TYPES
from ..sim.world import World

BLOCKERS = tuple(BLOCKER_TYPES)
WARMUP_TICKS = 8


def band(sinr: float) -> str:
    return "poor" if sinr < 0 else ("fair" if sinr < 13 else "good")


class PlayerOperator:
    """The player answers the agent's approval requests. Unanswered requests can time out to 'approve'."""

    def __init__(self, auto_approve_after: int | None = None):
        self.answers: dict[str, str] = {}
        self.auto_approve_after = auto_approve_after
        self.answered = 0

    def __call__(self, inc, pred, verdict, tick):
        answer = self.answers.pop(inc.id, None)
        if answer is None and self.auto_approve_after is not None and tick - inc.waiting_since >= self.auto_approve_after:
            answer = "approve"
        if answer:
            self.answered += 1
        return answer


@dataclass
class Session:
    world: World
    agent: Agent | None
    operator: PlayerOperator
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    speed: float = 1.0  # ticks per second
    paused: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    subscribers: set = field(default_factory=set)
    task: asyncio.Task | None = None
    created: float = field(default_factory=time.time)
    baseline: dict = field(default_factory=dict)  # phone id -> its normal clarity, for the score
    rescued: set = field(default_factory=set)

    # ------------------------------------------------------------------ clock

    def tick(self) -> dict:
        """Advance one tick and let the agent act. Returns the frame to broadcast."""
        with self.lock:
            self.world.step()
            events = self.agent.on_tick() if self.agent else []
            if self.world.tick <= WARMUP_TICKS + 1:
                r = self.world.last
                for uid, s in zip(r.ue_ids, r.sinr_db):
                    self.baseline[int(uid)] = float(s)
            return self.frame(events)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            if self.paused:
                await asyncio.sleep(0.1)
                continue
            start = loop.time()
            frame = await asyncio.to_thread(self.tick)
            await self.broadcast(frame)
            await asyncio.sleep(max(0.0, 1.0 / max(self.speed, 0.05) - (loop.time() - start)))

    async def broadcast(self, frame: dict) -> None:
        dead = []
        for ws in list(self.subscribers):
            try:
                await ws.send_json(frame)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.subscribers.discard(ws)

    # ------------------------------------------------------------------ what the player sees

    def scene(self) -> dict:
        """The street's fixed parts, for building the 3D view once."""
        w = self.world
        return {
            "name": w.name, "extent": list(w.extent),
            "buildings": [{"name": b.name, "x0": b.xmin, "x1": b.xmax, "y0": b.ymin, "y1": b.ymax,
                           "height": b.zmax, "material": b.material} for b in w.boxes if b.kind == "building"],
            "zones": [{"name": z.name, "x0": z.xmin, "x1": z.xmax, "y0": z.ymin, "y1": z.ymax, "tower": z.tower,
                       "max_load": z.max_load} for z in w.zones],
            "beam_angles": w.beam_az.tolist(),
            "problem_kinds": list(BLOCKERS) + ["stuck_beam", "misconfig", "booster", "crowd_surge"],
        }

    def frame(self, events: list | None = None) -> dict:
        w, r = self.world, self.world.last
        phones = []
        if r is not None:
            for i, uid in enumerate(r.ue_ids):
                s = float(r.sinr_db[i])
                t = w.towers[int(r.serving[i])]
                phones.append({
                    "id": int(uid), "x": round(float(r.xy[i, 0]), 2), "y": round(float(r.xy[i, 1]), 2),
                    "tower": int(r.serving[i]), "beam_az": round(float(t.boresight_deg + w.beam_az[r.beam[i]]), 1),
                    "sinr": round(s, 1), "band": band(s), "group": r.groups[i],
                    "mbps": round(float(r.throughput_mbps[i]), 1), "wants_mbps": round(float(r.demand_mbps[i]), 1),
                })
        towers = [{"id": t.id, "name": t.name, "x": t.x, "y": t.y, "z": t.z, "boresight": t.boresight_deg,
                   "tilt": t.tilt_deg, "power_dbm": t.power_dbm, "load": round(float(r.load[t.id]), 2) if r else 0}
                  for t in w.towers]
        blockers = [{"id": b.name, "kind": b.kind, "x0": b.xmin, "x1": b.xmax, "y0": b.ymin, "y1": b.ymax,
                     "height": b.zmax, "hidden": b.hidden} for b in w.boxes if b.kind != "building"]
        incidents = []
        if self.agent:
            for inc in self.agent.incidents.values():
                incidents.append({
                    "id": inc.id, "status": inc.status, "cause": inc.cause, "confidence": round(inc.confidence, 2),
                    "phones": inc.phones, "place": inc.place, "outcome": inc.outcome,
                    "waiting_for_you": inc.status == "waiting_human",
                    "pending": inc.pending[0].text if inc.pending else None,
                })
        return {"tick": w.tick, "paused": self.paused, "speed": self.speed, "phones": phones, "towers": towers,
                "blockers": blockers,
                "problems": [{"id": p.id, "label": p.label, "kind": p.kind} for p in w.problems.values()],
                "incidents": incidents, "events": [e.to_dict() for e in (events or [])], "score": self.score()}

    def score(self) -> dict:
        r = self.world.last
        if r is None:
            return {}
        sinr = dict(zip(map(int, r.ue_ids), r.sinr_db))
        bands = [band(float(s)) for s in r.sinr_db]
        degraded = {u for u, s in sinr.items() if u in self.baseline and s < self.baseline[u] - 4 and s < 13}
        if self.agent:
            for inc in self.agent.incidents.values():
                if inc.kept:
                    self.rescued |= {u for u in inc.phones if u not in degraded}
        ev = self.agent.log.events if self.agent else []
        return {"good": bands.count("good"), "fair": bands.count("fair"), "poor": bands.count("poor"),
                "degraded_now": len(degraded), "phones_rescued": len(self.rescued),
                "fixes_applied": sum(e.stage == "act" for e in ev), "fixes_undone": sum(e.stage == "undo" for e in ev),
                "asked_you": sum(e.stage == "escalate" for e in ev)}

    # ------------------------------------------------------------------ what the player does

    def add_problem(self, kind: str, x: float | None = None, y: float | None = None, **kw) -> dict:
        w = self.world
        with self.lock:
            if kind in BLOCKERS:
                p = add_blocker(w, kind, float(x), float(y), along_y=bool(kw.get("along_y", False)),
                                hidden=bool(kw.get("hidden", False)))
            elif kind == "stuck_beam":
                ids = kw.get("phones") or self._phones_near(x, y, 25)[:8]
                p = stick_beams(w, [int(i) for i in ids], int(kw.get("offset", 3)))
            elif kind == "misconfig":
                p = misconfigure_tower(w, int(kw.get("tower", 2)), float(kw.get("power_db", 6)),
                                       float(kw.get("tilt_deg", -7)))
            elif kind == "booster":
                p = add_external_interferer(w, float(x), float(y), float(kw.get("power_dbm", 40)))
            elif kind == "crowd_surge":
                p = crowd_surge(w, float(x), float(y), float(kw.get("radius", 12)), int(kw.get("people", 60)),
                                float(kw.get("mbps", 20)))
            else:
                raise ValueError(f"unknown problem kind {kind!r}")
            return {"id": p.id, "label": p.label, "kind": p.kind}

    def remove_problem(self, problem_id: str) -> None:
        with self.lock:
            clear_problem(self.world, problem_id)

    def answer(self, incident_id: str, decision: str) -> None:
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be approve or reject")
        self.operator.answers[incident_id] = decision

    def _phones_near(self, x, y, radius) -> list[int]:
        r = self.world.last
        d = np.hypot(r.xy[:, 0] - float(x), r.xy[:, 1] - float(y))
        return [int(r.ue_ids[i]) for i in np.argsort(d) if d[i] < radius]


def new_session(layout: str = "station_road", seed: int = 7, agent: bool = True, language_model: bool = True,
                auto_approve_after: int | None = None, missing_links: bool = True) -> Session:
    """Build a street, warm it up, and attach the agent with the player as its operator."""
    if layout != "station_road":
        raise ValueError("only station_road is available in the game for now")
    w = station_road(seed=seed)
    if missing_links:  # without these, built-in handover hides most blockages and there's little to fix
        w.missing_relations = {(0, 1), (0, 2)}
    op = PlayerOperator(auto_approve_after)
    ag = None
    if agent:
        from ..diagnosis import Diagnoser

        roles = Roles.default() if language_model else Roles(llm=None, library=Roles.default().library)
        ag = Agent(w, diagnoser=Diagnoser.load(), policy=Policy.load(), roles=roles, operator=op, log=EventLog())
    s = Session(w, ag, op)
    for _ in range(WARMUP_TICKS):
        s.tick()
    return s
