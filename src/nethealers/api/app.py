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
GET  /sessions/{id}/incidents/{iid}/report   download everything about one incident (JSON), for audit
GET  /sessions/{id}/incidents/{iid}/roles    who knew what, when: the incident by institutional role
POST /adviser                          ask the policy and legal adviser a question (optionally about an incident)
GET  /alignment                        ITU-T Y.3172 / Y.3173 / AI Ready mapping and the policy-to-control trace
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


DOCS = Path(__file__).resolve().parents[3] / "docs"
_LIBRARY = None


def library():
    global _LIBRARY
    if _LIBRARY is None:
        from ..kb import Library

        _LIBRARY = Library.open()
    return _LIBRARY


@app.on_event("startup")
async def warm_up_library():
    """Load the embedding model in the background, so the first search isn't slow."""
    async def warm():
        try:
            await asyncio.to_thread(lambda: library().search("warm up", k=1))
        except Exception:
            pass

    asyncio.create_task(warm())


@app.get("/kb")
async def kb_overview():
    """The knowledge base: its documents (scope, country, passages, checksum) and the retrieval test results."""
    import json

    docs = await asyncio.to_thread(lambda: library().documents())
    ev = DOCS / "kb_eval.json"
    return {"documents": docs, "passages": sum(d["passages"] for d in docs),
            "evaluation": json.loads(ev.read_text()) if ev.exists() else None}


@app.get("/kb/search")
async def kb_search(q: str, scope: str | None = None, k: int = 6):
    """Search the knowledge base. scope: national, operator, standard, global or regional (comma-separated)."""
    if not q.strip():
        raise HTTPException(400, "empty query")
    scopes = [x.strip() for x in scope.split(",")] if scope else None
    hits = await asyncio.to_thread(lambda: library().search(q, k=min(max(k, 1), 20), scopes=scopes))
    from ..kb import source_meta

    meta = source_meta()
    return [{"id": h.id, "doc_id": h.doc_id, "title": h.title, "page": h.page, "score": round(h.score, 3),
             "kind": h.kind, "scope": meta.get(h.doc_id, {}).get("scope", ""),
             "country": meta.get(h.doc_id, {}).get("country", ""), "url": meta.get(h.doc_id, {}).get("url", ""),
             "text": " ".join(h.text.split())} for h in hits]


@app.get("/gaps")
def gaps():
    """The latest policy, strategy and standards gap analysis (scripts/gap_analysis.py)."""
    import json

    f = DOCS / "gap_analysis.json"
    if not f.exists():
        raise HTTPException(404, "no gap analysis yet: run scripts/gap_analysis.py")
    return json.loads(f.read_text())


class AskIn(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    session_id: str | None = None
    incident_id: str | None = None


_ADVISER_LLM = None


def adviser_llm():
    """The adviser's own language-model client: longer timeout than the game's agent, answers cached on disk."""
    global _ADVISER_LLM
    if _ADVISER_LLM is None:
        from ..llm import LLM

        llm = LLM()
        llm.timeout_s, llm.max_tokens = 60.0, 900
        _ADVISER_LLM = llm if llm.ready else False
    return _ADVISER_LLM or None


@app.post("/adviser")
async def ask_adviser(body: AskIn):
    """The policy and legal adviser. It answers from the knowledge base with citations and only advises: it has
    no way to change the network. The question and answer go into the session's audit log."""
    from ..kb.adviser import ask

    s = SESSIONS.get(body.session_id) if body.session_id else None
    brief = None
    if s is not None and body.incident_id:
        try:
            brief = await asyncio.to_thread(s.incident_brief, body.incident_id)
        except KeyError:
            raise HTTPException(404, f"no incident {body.incident_id}")
    try:
        out = await asyncio.to_thread(ask, body.question, library(), adviser_llm(), brief)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if s is not None:
        await asyncio.to_thread(s.log_consultation, body.incident_id, out)
    return out


@app.get("/alignment")
async def alignment():
    """config/itu_alignment.yaml, with the text of every pinned passage looked up in the knowledge base."""
    import yaml

    from ..kb import source_meta
    from ..kb.adviser import authority

    data = yaml.safe_load((Path(__file__).resolve().parents[3] / "config" / "itu_alignment.yaml").read_text())
    ids = sorted({pid for row in data.get("policy_to_control", []) for pid in row.get("passages", [])})
    found = await asyncio.to_thread(lambda: library().get(ids))
    meta = source_meta()
    for row in data.get("policy_to_control", []):
        row["sources"] = []
        for pid in row.get("passages", []):
            p = found.get(pid)
            if p is None:  # not built yet, or the documents changed: say so rather than show nothing
                row["sources"].append({"id": pid, "missing": True})
                continue
            m = meta.get(p.doc_id, {})
            row["sources"].append({"id": pid, "title": p.title, "page": p.page, "url": m.get("url", ""),
                                   "authority": authority(m.get("scope", ""), p.kind),
                                   "excerpt": " ".join(p.text.split())[:500]})
    return data


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


@app.get("/sessions/{session_id}/incidents/{incident_id}/report")
async def incident_report(session_id: str, incident_id: str):
    """One incident as a downloadable JSON file: version stamps, diagnosis, every fix with predicted vs measured
    result, approvals, questions to the policy adviser and the full timeline."""
    import json

    from fastapi import Response

    from ..agent.events import _jsonable

    s = get(session_id)
    try:
        report = await asyncio.to_thread(s.incident_report, incident_id)
    except KeyError:
        raise HTTPException(404, f"no incident {incident_id}")
    name = f"nethealers-{incident_id}-{session_id}.json"
    return Response(json.dumps(report, indent=1, default=_jsonable, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/sessions/{session_id}/incidents/{incident_id}/roles")
async def incident_roles(session_id: str, incident_id: str):
    s = get(session_id)
    try:
        return await asyncio.to_thread(s.coordination, incident_id)
    except KeyError:
        raise HTTPException(404, f"no incident {incident_id}")


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
