"""Everything the agent does is an Event: what the game's side panel shows and the audit log keeps."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

STAGES = ("detect", "diagnose", "rehearse", "check", "act", "verify", "undo", "escalate", "approve", "withdraw",
          "resolve", "note")
AGENTS = ("monitor", "diagnosis", "planner", "twin", "safety", "executor", "verifier", "operator")


@dataclass
class Event:
    tick: int
    stage: str
    agent: str
    text: str  # plain-language sentence for people
    incident: str | None = None
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class EventLog:
    def __init__(self, path: Path | None = None):
        self.events: list[Event] = []
        self.path = path
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")

    def add(self, e: Event) -> Event:
        self.events.append(e)
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(e.to_dict(), default=_jsonable) + "\n")
        return e

    def for_incident(self, incident: str) -> list[Event]:
        return [e for e in self.events if e.incident == incident]

    def since(self, tick: int) -> list[Event]:
        return [e for e in self.events if e.tick >= tick]


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
