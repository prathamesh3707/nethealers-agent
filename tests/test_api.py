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


def test_live_stream_sends_frames(client):
    sid = start(client)["id"]
    with client.websocket_connect(f"/sessions/{sid}/live") as ws:
        first = ws.receive_json()
        assert first["tick"] >= 8 and first["phones"]
        step(client, sid)
        nxt = ws.receive_json()
        assert nxt["tick"] == first["tick"] + 1
