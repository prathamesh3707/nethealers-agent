from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nethealers.api.app import SESSIONS, app
from nethealers.sim.layouts import BUS_POSITION

MODEL = Path(__file__).resolve().parents[1] / "models" / "diagnosis.joblib"
pytestmark = pytest.mark.skipif(not MODEL.exists(), reason="train the model first")


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    SESSIONS.clear()


def start(client):
    r = client.post("/sessions", json={"language_model": False, "start_paused": True})
    assert r.status_code == 200
    return r.json()


def step(client, sid, n=1):
    frame = None
    for _ in range(n):
        frame = client.post(f"/sessions/{sid}/control", json={"action": "step"}).json()
    return frame


def test_new_game_has_a_scene_and_a_first_frame(client):
    g = start(client)
    assert {b["name"] for b in g["scene"]["buildings"]} >= {"Glass office", "Hospital"}
    assert g["scene"]["zones"][0]["name"] == "Hospital zone"
    st = g["state"]
    assert len(st["phones"]) == 60 and len(st["towers"]) == 3
    assert {"x", "y", "band", "beam_az", "tower"} <= set(st["phones"][0])
    assert g["language_model"] is False


def test_bus_appears_and_the_agent_reacts(client):
    g = start(client)
    sid = g["id"]
    p = client.post(f"/sessions/{sid}/problems", json={"kind": "bus", "x": BUS_POSITION[0], "y": BUS_POSITION[1]})
    assert p.status_code == 200 and p.json()["label"] == "blockage"
    frames = [step(client, sid) for _ in range(5)]
    assert any(b["kind"] == "bus" for b in frames[-1]["blockers"])
    stages = [e["stage"] for f in frames for e in f["events"]]
    assert "detect" in stages and "diagnose" in stages
    assert frames[-1]["incidents"][0]["cause"] == "blockage"
    events = client.get(f"/sessions/{sid}/events").json()
    assert len(events) >= len([s for s in stages])
    assert client.delete(f"/sessions/{sid}/problems/{p.json()['id']}").status_code == 200


def test_bad_requests_are_explained(client):
    sid = start(client)["id"]
    assert client.post(f"/sessions/{sid}/problems", json={"kind": "dragon", "x": 1, "y": 1}).status_code == 400
    assert client.post(f"/sessions/{sid}/answer", json={"incident": "X", "decision": "maybe"}).status_code == 400
    assert client.post(f"/sessions/{sid}/control", json={"action": "speed", "value": 50}).status_code == 400
    assert client.get("/sessions/nope/state").status_code == 404
    client.post(f"/sessions/{sid}/control", json={"action": "resume"})
    assert client.post(f"/sessions/{sid}/control", json={"action": "step"}).status_code == 400
    # missing position, unknown tower, answering an incident that isn't waiting
    assert client.post(f"/sessions/{sid}/problems", json={"kind": "bus"}).status_code == 400
    assert client.post(f"/sessions/{sid}/problems", json={"kind": "misconfig", "tower": 9}).status_code == 400
    assert client.post(f"/sessions/{sid}/problems", json={"kind": "bus", "x": 5000, "y": 1}).status_code == 400
    assert client.post(f"/sessions/{sid}/answer", json={"incident": "INC-999", "decision": "approve"}).status_code == 409


def test_live_stream_sends_frames(client):
    sid = start(client)["id"]
    with client.websocket_connect(f"/sessions/{sid}/live") as ws:
        first = ws.receive_json()
        assert first["tick"] >= 8 and first["phones"]
        step(client, sid)
        nxt = ws.receive_json()
        assert nxt["tick"] == first["tick"] + 1


def test_a_driven_bus_arrives_stops_and_leaves(client):
    sid = start(client)["id"]
    x, y = BUS_POSITION
    p = client.post(f"/sessions/{sid}/problems", json={"kind": "bus", "x": x, "y": y, "drive": True, "stay": 3}).json()
    xs = []
    for _ in range(12):
        f = step(client, sid)
        bus = [b for b in f["blockers"] if b["id"] == p["id"]]
        xs.append((bus[0]["x0"] + bus[0]["x1"]) / 2 if bus else None)
    seen = [v for v in xs if v is not None]
    assert seen[0] < x - 5  # starts up the road
    assert any(abs(v - x) < 0.5 for v in seen)  # stops at the given spot
    assert seen[-1] > x + 5 or xs[-1] is None  # drives off
    assert xs[-1] is None and p["id"] not in {q["id"] for q in f["problems"]}


def test_frames_carry_timings_and_stages(client):
    sid = start(client)["id"]
    client.post(f"/sessions/{sid}/problems", json={"kind": "bus", "x": BUS_POSITION[0], "y": BUS_POSITION[1]})
    frames = [step(client, sid) for _ in range(6)]
    f = frames[-1]
    assert f["timing"]["tick_ms"] > 0 and "agent_ms" in f["timing"]
    inc = f["incidents"][0]
    assert inc["stage"] in {"detect", "diagnose", "rehearse", "check", "plan", "review", "act", "verify", "undo",
                            "escalate", "approve", "withdraw", "resolve", "note"}
    assert all("ms" in e for fr in frames for e in fr["events"])
    timeline = client.get(f"/sessions/{sid}/incidents/{inc['id']}").json()["events"]
    assert timeline and timeline[0]["stage"] == "detect"


def test_shadow_street_shows_what_happens_without_the_agent(client):
    sid = start(client)["id"]
    p = client.post(f"/sessions/{sid}/problems", json={"kind": "bus", "x": BUS_POSITION[0], "y": BUS_POSITION[1]}).json()
    first = step(client, sid)
    assert first["without_agent"]["degraded_now"] >= 1  # the bus hurts the shadow street too
    s = SESSIONS[sid]
    assert p["id"] in s.shadow_ids and s.shadow_ids[p["id"]] in s.shadow.problems
    r = client.post(f"/sessions/{sid}/problems/{p['id']}/move", json={"x": BUS_POSITION[0] - 30, "y": BUS_POSITION[1]})
    assert r.status_code == 200
    assert s.shadow.box(s.shadow_ids[p["id"]]).center[0] == pytest.approx(BUS_POSITION[0] - 30, abs=0.01)
    frames = [step(client, sid) for _ in range(10)]
    f = frames[-1]
    assert f["score"]["degraded_now"] <= f["without_agent"]["degraded_now"]
    client.delete(f"/sessions/{sid}/problems/{p['id']}")
    assert not s.shadow.problems


@pytest.mark.parametrize("problem", [
    {"kind": "misconfig", "tower": 0},
    {"kind": "misconfig", "tower": 2},
    {"kind": "bus", "x": BUS_POSITION[0], "y": BUS_POSITION[1]},
    {"kind": "stuck_beam", "x": 233, "y": 115},
])
def test_after_a_problem_is_removed_nothing_stays_stuck(client, problem):
    sid = start(client)["id"]
    p = client.post(f"/sessions/{sid}/problems", json=problem).json()
    step(client, sid, 20)
    client.delete(f"/sessions/{sid}/problems/{p['id']}")
    f = step(client, sid, 60)
    still_open = [i for i in f["incidents"] if i["status"] not in ("resolved", "false_alarm")]
    assert not still_open, still_open
    # the agent never leaves the street worse than it would be without it
    assert f["score"]["degraded_now"] <= f["without_agent"]["degraded_now"]
    s = SESSIONS[sid]
    assert all(abs(t.power_dbm - 33.0) <= 3 for t in s.world.towers)


def test_an_incident_downloads_as_an_audit_report(client):
    sid = start(client)["id"]
    client.post(f"/sessions/{sid}/problems", json={"kind": "bus", "x": BUS_POSITION[0], "y": BUS_POSITION[1]})
    frame = step(client, sid, 12)
    iid = frame["incidents"][0]["id"]
    r = client.get(f"/sessions/{sid}/incidents/{iid}/report")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    rep = r.json()
    assert rep["incident"]["cause"] == "blockage" and rep["timeline"]
    assert set(rep["manifest"]["sha256"]) == {"models/diagnosis.joblib", "config/policy.yaml", "config/intents.yaml"}
    assert all({"fix", "predicted_gain_db", "measured_gain_db", "kept"} <= set(f) for f in rep["fixes_tried"])
    assert client.get(f"/sessions/{sid}/incidents/INC-999/report").status_code == 404


def test_questions_to_the_adviser_are_logged_but_are_not_a_loop_step(client):
    sid = start(client)["id"]
    client.post(f"/sessions/{sid}/problems", json={"kind": "bus", "x": BUS_POSITION[0], "y": BUS_POSITION[1]})
    frame = step(client, sid, 6)
    inc = frame["incidents"][0]
    s = SESSIONS[sid]
    brief = s.incident_brief(inc["id"])
    assert brief["cause"] == "blockage" and "phones" not in brief  # counts only, no phone ids
    s.log_consultation(inc["id"], {"question": "May it?", "verdict": "not established", "answer": "", "conditions": [],
                                   "responsible": "", "recommended_action": "", "confidence": "low", "cited": [],
                                   "passages": {}, "method": "test"})
    events = client.get(f"/sessions/{sid}/incidents/{inc['id']}").json()["events"]
    assert events[-1]["stage"] == "advise" and events[-1]["data"]["question"] == "May it?"
    assert step(client, sid)["incidents"][0]["stage"] != "advise"
    assert client.post("/adviser", json={"question": ""}).status_code == 422


def test_itu_alignment_lists_the_pipeline_and_the_policy_trace(client):
    d = client.get("/alignment").json()
    assert [r["node"].split()[0] for r in d["y3172"]][:7] == ["SRC", "C", "PP", "M", "P", "D", "SINK"]
    assert len(d["y3173"]) == 5 and len(d["ai_ready"]) == 6
    assert all(r["sources"] for r in d["policy_to_control"])


def test_who_knew_what_splits_the_incident_by_institutional_role(client):
    sid = start(client)["id"]
    client.post(f"/sessions/{sid}/problems", json={"kind": "bus", "x": BUS_POSITION[0], "y": BUS_POSITION[1]})
    iid = step(client, sid, 12)["incidents"][0]["id"]
    d = client.get(f"/sessions/{sid}/incidents/{iid}/roles").json()
    assert [r["id"] for r in d["roles"]] == ["noc", "planner", "regulator", "person"]
    order = [m["role"] for m in d["messages"]]
    assert order[0] == "noc" and "planner" in order and "regulator" in order
    assert order.index("planner") < order.index("regulator")  # the planner proposes before the regulator checks
    assert d["first_heard"]["noc"] <= d["first_heard"]["planner"] <= d["first_heard"]["regulator"]
