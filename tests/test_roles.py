import os
import uuid
from pathlib import Path

import pytest

from nethealers.agent import Agent, EventLog, Roles
from nethealers.llm import Answer, LLMUnavailable, parse_json
from nethealers.sim import add_blocker, station_road
from nethealers.sim.layouts import BUS_POSITION

MODEL = Path(__file__).resolve().parents[1] / "models" / "diagnosis.joblib"
needs_model = pytest.mark.skipif(not MODEL.exists(), reason="train the model first")


class FakeLLM:
    """Scripted answers: a list of dicts, handed out in order (planner, adviser, planner, ...)."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []
        self.ready = ["fake"]

    def chat_json(self, system, user):
        self.prompts.append((system, user))
        if not self.answers:
            raise LLMUnavailable("script exhausted")
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return Answer(a, "fake", "scripted")


def run_bus(roles, ticks=8):
    from nethealers.diagnosis import Diagnoser

    w = station_road()
    w.missing_relations = {(0, 1), (0, 2)}
    w.zones = []  # no hospital limit: several safe options exist
    ag = Agent(w, diagnoser=Diagnoser.load(), roles=roles, log=EventLog())
    for _ in range(8):
        w.step()
        ag.on_tick()
    add_blocker(w, "bus", *BUS_POSITION)
    for _ in range(ticks):
        w.step()
        ag.on_tick()
    return ag


def stages(ag):
    return [(e.stage, e.text) for e in ag.log.events]


def test_parse_json_digs_the_object_out_of_prose():
    assert parse_json('Sure! ```json\n{"choice": 2, "reason": "x"}\n```') == {"choice": 2, "reason": "x"}
    assert parse_json('blah {"a": {"b": 1}} trailing') == {"a": {"b": 1}}
    with pytest.raises(ValueError):
        parse_json("no json here")


@needs_model
def test_planner_choice_is_used_and_explained():
    llm = FakeLLM([{"choice": 2, "reason": "Smaller move, nearly as good."},
                   {"decision": "agree", "reason": "Fine.", "citations": []}])
    ag = run_bus(Roles(llm=llm, library=None, intents=[{"text": "be careful"}]))
    plan = [t for s, t in stages(ag) if s == "plan"]
    assert plan and "Smaller move, nearly as good." in plan[0]
    acted = [e for e in ag.log.events if e.stage == "act"][0].data["action"]
    assert acted in plan[0]
    assert "be careful" in llm.prompts[0][1]  # intents reach the planner


@needs_model
def test_objection_leads_to_a_second_pick():
    llm = FakeLLM([{"choice": 1, "reason": "Biggest gain."},
                   {"decision": "object", "reason": "Too many phones on one tower.", "citations": []},
                   {"choice": 1, "reason": "Next best after the objection."},
                   {"decision": "agree", "reason": "OK now.", "citations": []}])
    ag = run_bus(Roles(llm=llm, library=None, intents=[]))
    reviews = [t for s, t in stages(ag) if s == "review"]
    assert reviews[0].startswith("Safety adviser objects") and reviews[1].startswith("Safety adviser agrees")
    picks = [e.data["action"] for e in ag.log.events if e.stage == "plan"]
    assert picks[0] != picks[1]  # the objected option was removed before the second pick


@needs_model
def test_invalid_or_missing_answers_fall_back_to_plain_rules():
    llm = FakeLLM([{"choice": 99, "reason": "made up"}, LLMUnavailable("quota")])
    ag = run_bus(Roles(llm=llm, library=None, intents=[]))
    plan = [e for e in ag.log.events if e.stage == "plan"][0]
    assert "not a listed option" in plan.data["source"]
    assert any(e.stage == "act" for e in ag.log.events)


@needs_model
def test_planner_can_hand_over_to_a_person():
    llm = FakeLLM([{"choice": "escalate", "reason": "The options all touch the hospital tower."}])
    ag = run_bus(Roles(llm=llm, library=None, intents=[]))
    assert any(s == "escalate" and "hospital tower" in t for s, t in stages(ag))
    assert not any(e.stage == "act" for e in ag.log.events)


def test_library_finds_operator_policy(tmp_path):
    from nethealers.kb.library import Library, MemoryStore, load_sources

    lib = Library(MemoryStore(tmp_path / "index"))
    lib.build([s for s in load_sources() if s["id"] == "operator-policy"], log=lambda *_: None)
    hits = lib.search("keep spare capacity at the hospital", k=1)
    assert hits and hits[0].doc_id == "operator-policy"


def test_decision_log_in_postgres():
    url = os.environ.get("DATABASE_URL", "postgresql://nethealers:nethealers@localhost:5435/nethealers")
    try:
        from nethealers.agent import PgDecisionLog

        sink = PgDecisionLog(url, f"test-{uuid.uuid4().hex[:8]}", "unit test")
    except Exception:
        pytest.skip("Postgres not running (docker compose up -d)")
    w = station_road()
    log = EventLog(sinks=[sink])
    ag = Agent(w, log=log)
    ag._say("note", "monitor", "hello from the test")
    rows = sink.read()
    assert rows and rows[-1]["text"] == "hello from the test"


@needs_model
def test_planner_escalating_after_a_kept_fix_still_looks_after_that_fix():
    from nethealers.diagnosis import Diagnoser
    from nethealers.sim import clear_problem

    # first fix: planner picks option 1, adviser agrees; afterwards the planner always hands over
    llm = FakeLLM([{"choice": 1, "reason": "best"}, {"decision": "agree", "reason": "ok"}]
                  + [{"choice": "escalate", "reason": "let a person decide"}] * 20)
    w = station_road()  # with the hospital zone, as in the game: only a partial handover is safe
    w.missing_relations = {(0, 1), (0, 2)}
    ag = Agent(w, diagnoser=Diagnoser.load(), roles=Roles(llm=llm, library=None), log=EventLog())
    for _ in range(8):
        w.step()
        ag.on_tick()
    bus = add_blocker(w, "bus", *BUS_POSITION)
    for _ in range(10):
        w.step()
        ag.on_tick()
    inc = ag.incidents["INC-001"]
    assert inc.kept, "the first fix should have been kept"
    assert inc.status != "escalated", "a handover must not abandon fixes already in place"
    left = w.tick
    clear_problem(w, bus.id)
    for _ in range(10):
        w.step()
        ag.on_tick()
    # the applied handover is still looked after: withdrawn, or undone by the hospital-zone guard
    assert any(e.stage in ("withdraw", "undo") and e.incident == "INC-001" and e.tick > left for e in ag.log.events)
    assert not any(u.forced_tower is not None for u in w.ues)
