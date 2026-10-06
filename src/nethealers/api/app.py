"""HTTP and WebSocket API for the 3D game.

    uv run uvicorn nethealers.api.app:app --reload --port 8010

POST /sessions                         start a game (Station Road, agent on)
GET  /sessions/{id}/scene              buildings, zones, beam angles: build the 3D view once
GET  /sessions/{id}/state              current frame (phones, towers, blockers, incidents, score)
POST /sessions/{id}/problems           drop a problem: bus, truck, car, crowd, kiosk, hoarding,
                                       stuck_beam, misconfig, booster, crowd_surge
                                       (vehicles with drive=true drive in, wait `stay` s, then leave)
POST /sessions/{id}/problems/{pid}/move   put a blocker somewhere else
POST /sessions/{id}/problems/{pid}/leave  a parked vehicle drives off now
DELETE /sessions/{id}/problems/{pid}   remove it
POST /sessions/{id}/control            pause, resume, step, speed
POST /sessions/{id}/answer             approve or reject a fix the agent asked about
GET  /sessions/{id}/events?since=N     the agent's log
GET  /sessions/{id}/incidents/{iid}    one incident's full timeline, for replay
WS   /sessions/{id}/live               one frame per tick, with that tick's events

If the game has been built (web/dist), it is served at / as well.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .session import Session, new_session

app = FastAPI(title="NetHealers self-healing network game")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                                                 "http://localhost:4173", "http://127.0.0.1:4173"],
                   allow_methods=["*"], allow_headers=["*"])
WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"
SESSIONS: dict[str, Session] = {}
MAX_SESSIONS = 4


class NewSession(BaseModel):
    seed: int = 7
    speed: float = Field(1.0, gt=0, le=10)
    agent: bool = True
    language_model: bool = True
    missing_links: bool = True
    auto_approve_after: int | None = Field(None, ge=1, description="seconds before an unanswered request is approved")
    start_paused: bool = False


class NewProblem(BaseModel):
    kind: str
    x: float | None = None
    y: float | None = None
    along_y: bool = False
    hidden: bool = False
    tower: int | None = None
    phones: list[int] | None = None
    offset: int | None = None
    people: int | None = None
    power_dbm: float | None = None
    power_db: float | None = None
    tilt_deg: float | None = None
    radius: float | None = None
    mbps: float | None = None
    drive: bool = False
    stay: int | None = Field(None, ge=0, le=300)


class Move(BaseModel):
    x: float
    y: float


class Control(BaseModel):
    action: str  # pause | resume | step | speed
    value: float | None = None


class AnswerIn(BaseModel):
    incident: str
    decision: str  # approve | reject


def get(session_id: str) -> Session:
    s = SESSIONS.get(session_id)
    if s is None:
        raise HTTPException(404, f"no session {session_id}")
    return s


@app.get("/health")
def health():
    return {"ok": True, "sessions": len(SESSIONS)}


@app.post("/sessions")
async def create(body: NewSession):
    if len(SESSIONS) >= MAX_SESSIONS:  # keep the laptop cool: drop the oldest game
        oldest = min(SESSIONS.values(), key=lambda s: s.created)
        await stop(oldest.id)
    s = await asyncio.to_thread(new_session, seed=body.seed, agent=body.agent, language_model=body.language_model,
                                auto_approve_after=body.auto_approve_after, missing_links=body.missing_links)
    s.speed, s.paused = body.speed, body.start_paused
    SESSIONS[s.id] = s
    s.task = asyncio.create_task(s.run())
    return {"id": s.id, "scene": s.scene(), "state": s.frame(),
            "language_model": bool(s.agent and s.agent.roles and s.agent.roles.live)}


@app.delete("/sessions/{session_id}")
async def stop(session_id: str):
    s = SESSIONS.pop(session_id, None)
    if s and s.task:
        s.task.cancel()
    if s:
        await s.close_viewers("game stopped")
    return {"stopped": bool(s)}


@app.get("/sessions/{session_id}/scene")
def scene(session_id: str):
    return get(session_id).scene()


@app.get("/sessions/{session_id}/state")
async def state(session_id: str):
    return await asyncio.to_thread(get(session_id).locked_frame)


async def show_change(s: Session) -> None:
    """While paused no ticks run, so push a frame right away: the viewer sees a placed or moved bus at once."""
    if s.paused:
        await s.broadcast(await asyncio.to_thread(s.locked_frame))


@app.post("/sessions/{session_id}/problems")
async def add_problem(session_id: str, body: NewProblem):
    s = get(session_id)
    extra = {k: v for k, v in body.model_dump().items() if v is not None and k not in ("kind", "x", "y")}
    try:
        out = await asyncio.to_thread(s.add_problem, body.kind, body.x, body.y, **extra)
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise HTTPException(400, str(e))
    await show_change(s)
    return out


@app.post("/sessions/{session_id}/problems/{problem_id}/move")
async def move_problem(session_id: str, problem_id: str, body: Move):
    s = get(session_id)
    try:
        await asyncio.to_thread(s.move_problem, problem_id, body.x, body.y)
    except KeyError:
        raise HTTPException(404, f"no problem {problem_id}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    await show_change(s)
    return {"moved": problem_id}


@app.post("/sessions/{session_id}/problems/{problem_id}/leave")
def send_away(session_id: str, problem_id: str):
    s = get(session_id)
    try:
        s.send_away(problem_id)
    except KeyError:
        raise HTTPException(404, f"no problem {problem_id}")
    return {"leaving": problem_id}


@app.delete("/sessions/{session_id}/problems/{problem_id}")
async def remove_problem(session_id: str, problem_id: str):
    s = get(session_id)
    try:
        await asyncio.to_thread(s.remove_problem, problem_id)
    except KeyError:
        raise HTTPException(404, f"no problem {problem_id}")
    await show_change(s)
    return {"removed": problem_id}


@app.post("/sessions/{session_id}/control")
async def control(session_id: str, body: Control):
    s = get(session_id)
    if body.action == "pause":
        s.paused = True
    elif body.action == "resume":
        s.resume()
    elif body.action == "speed":
        if not body.value or not 0 < body.value <= 10:
            raise HTTPException(400, "speed must be between 0 and 10 ticks per second")
        s.speed = body.value
    elif body.action == "step":
        if not s.paused:
            raise HTTPException(400, "pause first, then step")
        frame = await asyncio.to_thread(s.tick)
        await s.broadcast(frame)
        return frame
    else:
        raise HTTPException(400, f"unknown action {body.action!r}")
    return {"paused": s.paused, "speed": s.speed}


@app.post("/sessions/{session_id}/answer")
def answer(session_id: str, body: AnswerIn):
    s = get(session_id)
    try:
        s.answer(body.incident, body.decision)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LookupError as e:
        raise HTTPException(409, str(e))
    return {"incident": body.incident, "decision": body.decision}


@app.get("/sessions/{session_id}/events")
def events(session_id: str, since: int = 0):
    s = get(session_id)
    return [e.to_dict() for e in (s.agent.log.events if s.agent else []) if e.tick >= since]


@app.get("/sessions/{session_id}/incidents/{incident_id}")
def incident(session_id: str, incident_id: str):
    s = get(session_id)
    if not s.agent or incident_id not in s.agent.incidents:
        raise HTTPException(404, f"no incident {incident_id}")
    return {"events": [e.to_dict() for e in s.agent.log.for_incident(incident_id)]}


@app.websocket("/sessions/{session_id}/live")
async def live(ws: WebSocket, session_id: str):
    s = SESSIONS.get(session_id)
    await ws.accept()
    if s is None:
        await ws.close(code=4404)
        return
    s.subscribers.add(ws)
    try:
        await ws.send_json(await asyncio.to_thread(s.locked_frame))
        while True:
            await ws.receive_text()  # keep the connection open; the client may send pings
    except WebSocketDisconnect:
        pass
    finally:
        s.subscribers.discard(ws)


if WEB_DIST.is_dir():  # the built game, so one server is enough for a demo
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="game")
