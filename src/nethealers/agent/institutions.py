"""Who knew what, when: one incident seen as three institutional roles and a person.

The agent's steps already run as separate roles that are given different information:
  - the NOC engineer (monitor, diagnosis model, executor, verifier) sees phones' signal reports and tower load;
  - the radio planner (digital twin and planner) works from the diagnosis and the twin; its language-model
    step gets a summary (place, cause, number of phones, no phone ids), the rehearsed fixes and the operator's
    intents, but no law text;
  - the regulator adviser (rule-checker and safety adviser) checks one proposed change; its language-model step
    gets that change, the protected-zone loads, the operator's intents and passages from the law, and can object;
  - a person approves big or unsure changes and takes over what the agent hands on.
Each role starts only when the one before it has finished, so information is released in sequence. This module
groups the incident's logged events by role; it adds no new behaviour.
"""

from __future__ import annotations

ROLES = [
    {"id": "noc", "name": "NOC engineer",
     "mandate": "Keep service up: spot users who lost service, name the cause, apply approved changes and check them.",
     "sees": "Phones' signal reports, tower load, the diagnosis model",
     "cannot": "Choose or approve a fix"},
    {"id": "planner", "name": "Radio planner",
     "mandate": "Find the fix with the most gain and the least harm to others.",
     "sees": "The diagnosis, the digital twin, the operator's intents (no law text)",
     "cannot": "See the law passages, or approve its own change"},
    {"id": "regulator", "name": "Regulator adviser",
     "mandate": "Check each change against the operator policy, protected zones and the law; object if needed.",
     "sees": "One proposed change, protected-zone loads, law and policy passages (no phone ids)",
     "cannot": "See phone ids, or change the network"},
    {"id": "person", "name": "Operator (a person)",
     "mandate": "Approve big or unsure changes; take over what the agent hands on.",
     "sees": "Everything on screen",
     "cannot": "-"},
]

_BY_AGENT = {"monitor": "noc", "diagnosis": "noc", "executor": "noc", "verifier": "noc",
             "twin": "planner", "planner": "planner",
             "safety": "regulator", "adviser": "regulator",
             "operator": "person"}


def role_of(event: dict) -> str:
    if event["stage"] in ("escalate", "approve"):
        return "person"  # a hand-over or an answer: it lands with the person
    return _BY_AGENT.get(event["agent"], "noc")


def coordination(events: list[dict], opened_tick: int) -> dict:
    """The incident's events in time order, each tagged with the role that produced it, plus the hand-overs."""
    msgs, handovers, last = [], [], None
    for e in events:
        if e["stage"] == "note":
            continue
        r = role_of(e)
        t = e["tick"] - opened_tick
        if last is not None and r != last:
            handovers.append({"from": last, "to": r, "t": t})
        msgs.append({"role": r, "t": t, "tick": e["tick"], "stage": e["stage"], "text": e["text"]})
        last = r
    first = {}
    for m in msgs:
        first.setdefault(m["role"], m["t"])
    return {"roles": ROLES, "messages": msgs, "handovers": handovers, "first_heard": first, "opened_tick": opened_tick}
