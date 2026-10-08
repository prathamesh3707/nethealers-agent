"""Everything the agent does is an Event: what the game's side panel shows and the audit log keeps."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

STAGES = ("detect", "diagnose", "rehearse", "check", "plan", "review", "act", "verify", "undo", "escalate", "approve",
          "withdraw", "resolve", "note", "advise")
AGENTS = ("monitor", "diagnosis", "planner", "twin", "safety", "executor", "verifier", "operator", "adviser")


@dataclass
class Event:
    tick: int
    stage: str
    agent: str
    text: str  # plain-language sentence for people
    incident: str | None = None
    data: dict = field(default_factory=dict)
    ms: float = 0.0  # time the agent spent producing this step

    def to_dict(self) -> dict:
        return asdict(self)


class EventLog:
    """Keeps every event in memory, and optionally in a JSON-lines file and in Postgres."""

    def __init__(self, path: Path | None = None, sinks: list | None = None):
        self.events: list[Event] = []
        self.path = path
        self.sinks = sinks or []
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")

    def add(self, e: Event) -> Event:
        self.events.append(e)
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(e.to_dict(), default=_jsonable) + "\n")
        for sink in list(self.sinks):
            try:
                sink.write(e)
            except Exception:  # a lost database connection must not stop the agent; keep logging in memory
                self.sinks.remove(sink)
        return e

    def for_incident(self, incident: str) -> list[Event]:
        return [e for e in self.events if e.incident == incident]

    def since(self, tick: int) -> list[Event]:
        return [e for e in self.events if e.tick >= tick]


class PgDecisionLog:
    """Writes events to Postgres: one row per event, grouped by run. The audit trail survives restarts."""

    def __init__(self, url: str, run_id: str, title: str = ""):
        import psycopg

        self.run_id = run_id
        self.conn = psycopg.connect(url, autocommit=True, connect_timeout=3)
        self.conn.execute("""CREATE TABLE IF NOT EXISTS runs (
            id text PRIMARY KEY, started timestamptz DEFAULT now(), title text)""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS events (
            id bigserial PRIMARY KEY, run_id text REFERENCES runs(id), tick int, incident text, stage text,
            agent text, text text, data jsonb, logged timestamptz DEFAULT now())""")
        self.conn.execute("INSERT INTO runs (id, title) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING", (run_id, title))

    def write(self, e: Event) -> None:
        self.conn.execute(
            "INSERT INTO events (run_id, tick, incident, stage, agent, text, data) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (self.run_id, e.tick, e.incident, e.stage, e.agent, e.text, json.dumps(e.data, default=_jsonable)))

    def read(self) -> list[dict]:
        rows = self.conn.execute("SELECT tick, incident, stage, agent, text FROM events WHERE run_id = %s "
                                 "ORDER BY id", (self.run_id,)).fetchall()
        return [dict(zip(("tick", "incident", "stage", "agent", "text"), r)) for r in rows]


def _jsonable(o):
    try:
        import numpy as np

        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    return str(o)
