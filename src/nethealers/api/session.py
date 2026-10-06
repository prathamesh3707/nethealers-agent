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
import logging
import os
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
    move_blocker,
    station_road,
    stick_beams,
)
from ..sim.config import BLOCKER_TYPES
from ..sim.world import World

BLOCKERS = tuple(BLOCKER_TYPES)
VEHICLES = {"bus", "truck", "car"}
WARMUP_TICKS = 8
DRIVE_IN_M = 40.0  # a driven vehicle appears this far up the road and arrives over a few seconds
DRIVE_STEP_M = 10.0
LEAVE_STEP_M = 15.0
log = logging.getLogger("nethealers.session")


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
    routes: dict = field(default_factory=dict)  # problem id -> remaining (x, y) positions, one per tick; None = remove
    error: str | None = None  # the last tick that failed; the game pauses so nothing runs on a broken state
    tick_ms: float = 0.0  # wall time of the latest tick (street + agent)
    # The same street with the same problems but no agent: what would have happened without it.
    shadow: World | None = None
    shadow_ids: dict = field(default_factory=dict)  # problem id on the street -> same problem on the shadow

    # ------------------------------------------------------------------ clock

    def tick(self) -> dict:
        """Advance one tick and let the agent act. Returns the frame to broadcast."""
        with self.lock:
            t0 = time.perf_counter()
            self._drive()
            self.world.step()
            if self.shadow is not None:
                self.shadow.step()
            events = self.agent.on_tick() if self.agent else []
            self.tick_ms = (time.perf_counter() - t0) * 1000
            if self.world.tick <= WARMUP_TICKS:
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
            try:
                frame = await asyncio.to_thread(self.tick)
            except Exception as e:  # never let one bad tick kill the game silently: pause and tell the player
                log.exception("tick failed in session %s", self.id)
                self.error, self.paused = f"{type(e).__name__}: {e}", True
                frame = await asyncio.to_thread(self.locked_frame)
            await self.broadcast(frame)
            await asyncio.sleep(max(0.0, 1.0 / max(self.speed, 0.05) - (loop.time() - start)))

    async def broadcast(self, frame: dict) -> None:
        """Send to every viewer at once; a slow or broken viewer is dropped instead of holding up the street."""
        subs = list(self.subscribers)

        async def send(ws):
            try:
                await asyncio.wait_for(ws.send_json(frame), timeout=2.0)
                return None
            except Exception:
                return ws

        for ws in await asyncio.gather(*(send(ws) for ws in subs)):
            if ws is not None:
                self.subscribers.discard(ws)

    async def close_viewers(self, reason: str) -> None:
        for ws in list(self.subscribers):
            try:
                await ws.close(code=4410, reason=reason[:120])
            except Exception:
                pass
        self.subscribers.clear()

    def locked_frame(self) -> dict:
        with self.lock:
            return self.frame()

    def _drive(self) -> None:
        """Move driven vehicles one step along their route; remove them when the route ends."""
        for pid in list(self.routes):
            if pid not in self.world.problems:
                self.routes.pop(pid)
                continue
            route = self.routes[pid]
            if not route:
                self.routes.pop(pid)
                continue
            nxt = route.pop(0)
            if nxt is None:
                self.routes.pop(pid)
                self._clear(pid)
            else:
                self._move(pid, *nxt)

    def _move(self, pid: str, x: float, y: float) -> None:
        move_blocker(self.world, pid, x, y)
        if self.shadow is not None and pid in self.shadow_ids:
            move_blocker(self.shadow, self.shadow_ids[pid], x, y)

    def _clear(self, pid: str) -> None:
        clear_problem(self.world, pid)
        sid = self.shadow_ids.pop(pid, None)
        if self.shadow is not None and sid in self.shadow.problems:
            clear_problem(self.shadow, sid)

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
            last_stage: dict[str, tuple[str, int]] = {}
            for e in self.agent.log.events:
                if e.incident:
                    last_stage[e.incident] = (e.stage, e.tick)
            for inc in self.agent.incidents.values():
                stage, at = last_stage.get(inc.id, ("detect", inc.opened))
                incidents.append({
                    "id": inc.id, "status": inc.status, "cause": inc.cause, "confidence": round(inc.confidence, 2),
                    "probs": {k: round(v, 3) for k, v in inc.probs.items()},
                    "phones": inc.phones, "place": inc.place, "outcome": inc.outcome,
                    "opened": inc.opened, "closed": inc.closed_tick, "stage": stage, "stage_tick": at,
                    "attempts": len(inc.attempts), "kept": len(inc.kept),
                    "decision_ms": round(1000 * sum(inc.decision_seconds), 1),
                    "waiting_for_you": inc.status == "waiting_human",
                    "pending": inc.pending[0].text if inc.pending else None,
                    "pending_reasons": list(inc.pending[1].reasons) if inc.pending else [],
                })
        return {"tick": w.tick, "paused": self.paused, "speed": self.speed, "phones": phones, "towers": towers,
                "blockers": blockers,
                "problems": [{"id": p.id, "label": p.label, "kind": p.kind, "x": p.detail.get("x"),
                              "y": p.detail.get("y"), "moving": p.id in self.routes} for p in w.problems.values()],
                "incidents": incidents, "events": [e.to_dict() for e in (events or [])], "score": self.score(),
                "timing": {"tick_ms": round(self.tick_ms, 1),
                           "agent_ms": round(self.agent.last_tick_ms, 1) if self.agent else 0.0},
                "llm": self._llm_stats(), "error": self.error,
                "without_agent": self.counts(self.shadow) if self.shadow is not None else None}

    def _llm_stats(self) -> dict:
        roles = self.agent.roles if self.agent else None
        llm = roles.llm if roles is not None else None
        if llm is None:
            return {"live": False}
        return {"live": bool(roles.live), "providers": llm.ready, "calls": llm.calls,
                "tokens_in": llm.tokens_in, "tokens_out": llm.tokens_out}

    def counts(self, world: World) -> dict:
        r = world.last
        if r is None:
            return {}
        bands = [band(float(s)) for s in r.sinr_db]
        degraded = sum(1 for u, s in zip(map(int, r.ue_ids), r.sinr_db)
                       if u in self.baseline and s < self.baseline[u] - 4 and s < 13)
        return {"good": bands.count("good"), "fair": bands.count("fair"), "poor": bands.count("poor"),
                "degraded_now": degraded}

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
        needs_xy = kind in BLOCKERS or kind in ("booster", "crowd_surge") or (kind == "stuck_beam" and not kw.get("phones"))
        if needs_xy:
            if x is None or y is None:
                raise ValueError(f"{kind} needs x and y")
            x0, x1, y0, y1 = w.extent
            if not (x0 <= float(x) <= x1 and y0 <= float(y) <= y1):
                raise ValueError(f"({x}, {y}) is outside the street ({x0}-{x1}, {y0}-{y1})")
        if kind == "misconfig" and not 0 <= int(kw.get("tower", 2)) < len(w.towers):
            raise ValueError(f"no tower {kw.get('tower')}")
        with self.lock:
            drive = bool(kw.get("drive", False)) and kind in BLOCKERS and kind in VEHICLES
            start_x = max(w.extent[0], float(x) - DRIVE_IN_M) if drive else (float(x) if x is not None else None)
            if kind == "stuck_beam":
                ids = kw.get("phones") or self._phones_near(x, y, 25)[:8]
                known = set(w.ue_index())
                kw = {**kw, "phones": [int(i) for i in ids if int(i) in known]}
                if not kw["phones"]:
                    raise ValueError("no phones there to affect")
            p = self._create(w, kind, start_x, y, kw)
            if self.shadow is not None:
                self.shadow_ids[p.id] = self._create(self.shadow, kind, start_x, y, kw).id
            if drive:  # drives in, waits at the stop, then drives off and disappears
                n_in = int(round((float(x) - start_x) / DRIVE_STEP_M))
                route = [(start_x + DRIVE_STEP_M * k, float(y)) for k in range(1, n_in)] + [(float(x), float(y))]
                route += [(float(x), float(y))] * max(0, int(kw.get("stay", 25)))
                route += [(min(w.extent[1], float(x) + LEAVE_STEP_M * k), float(y)) for k in range(1, 4)]
                self.routes[p.id] = route + [None]
            return {"id": p.id, "label": p.label, "kind": p.kind}

    @staticmethod
    def _create(w: World, kind: str, x, y, kw: dict):
        if kind in BLOCKERS:
            return add_blocker(w, kind, float(x), float(y), along_y=bool(kw.get("along_y", False)),
                               hidden=bool(kw.get("hidden", False)))
        if kind == "stuck_beam":
            return stick_beams(w, kw["phones"], int(kw.get("offset", 3)))
        if kind == "misconfig":
            return misconfigure_tower(w, int(kw.get("tower", 2)), float(kw.get("power_db", 6)),
                                      float(kw.get("tilt_deg", -7)))
        if kind == "booster":
            return add_external_interferer(w, float(x), float(y), float(kw.get("power_dbm", 40)))
        if kind == "crowd_surge":
            return crowd_surge(w, float(x), float(y), float(kw.get("radius", 12)),
                               min(int(kw.get("people", 60)), 150), float(kw.get("mbps", 20)))
        raise ValueError(f"unknown problem kind {kind!r}")

    def remove_problem(self, problem_id: str) -> None:
        with self.lock:
            self.routes.pop(problem_id, None)
            self._clear(problem_id)

    def move_problem(self, problem_id: str, x: float, y: float) -> None:
        with self.lock:
            p = self.world.problems.get(problem_id)
            if p is None:
                raise KeyError(problem_id)
            if "box" not in p.detail:
                raise ValueError(f"{p.kind} can't be moved")
            self.routes.pop(problem_id, None)
            x0, x1, y0, y1 = self.world.extent
            self._move(problem_id, min(max(float(x), x0), x1), min(max(float(y), y0), y1))

    def send_away(self, problem_id: str) -> None:
        """A parked vehicle leaves (or a blocker is lifted away) on the next tick. It is taken off the street
        rather than driven along it, so leaving doesn't briefly block other users' signal paths."""
        with self.lock:
            if problem_id not in self.world.problems:
                raise KeyError(problem_id)
            self.routes[problem_id] = [None]

    def answer(self, incident_id: str, decision: str) -> None:
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be approve or reject")
        with self.lock:
            inc = self.agent.incidents.get(incident_id) if self.agent else None
            if inc is None or inc.status != "waiting_human":
                raise LookupError(f"{incident_id} isn't waiting for an answer")
            self.operator.answers[incident_id] = decision

    def resume(self) -> None:
        self.error, self.paused = None, False

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
        if roles.llm is not None:
            roles.llm.timeout_s = 20.0  # the street waits while the agent thinks: keep that short in a game
        ag = Agent(w, diagnoser=Diagnoser.load(), policy=Policy.load(), roles=roles, operator=op,
                   log=EventLog(sinks=_decision_log_sinks()))
    s = Session(w, ag, op)
    for _ in range(WARMUP_TICKS):
        s.tick()
    s.shadow = w.copy()  # from here on, the same street without the agent
    return s


def _decision_log_sinks() -> list:
    """Write the game's decision log to Postgres when the database is running; otherwise keep it in memory."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return []
    try:
        from ..agent import PgDecisionLog

        return [PgDecisionLog(url, f"game-{uuid.uuid4().hex[:8]}", "Game session on Station Road")]
    except Exception:
        return []
