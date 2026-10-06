from pathlib import Path

import numpy as np
import pytest

from nethealers.agent import Agent, Policy, RuleChecker
from nethealers.agent.planner import Prediction
from nethealers.agent.twin import build_twin
from nethealers.sim import (
    BeamOverride,
    Handover,
    PowerChange,
    TiltChange,
    add_blocker,
    misconfigure_tower,
    station_road,
)
from nethealers.sim.layouts import BUS_POSITION

MODEL = Path(__file__).resolve().parents[1] / "models" / "diagnosis.joblib"
needs_model = pytest.mark.skipif(not MODEL.exists(), reason="train the model first: scripts/train_diagnosis.py")


def pred(action, gain=8.0, harmed=0, other=0.0, zone=None):
    return Prediction(action, "test", gain, 0.0, 10.0, harmed, other, zone or {})


@pytest.fixture
def world():
    w = station_road()
    w.run(3)
    return w


# ---------------------------------------------------------------- rule-checker

def test_rules_limit_step_size_and_drift(world):
    rc = RuleChecker(Policy.load(), world)
    assert rc.check(PowerChange(0, 4.0), world, 10, pred=pred(PowerChange(0, 4.0))).status == "rejected"
    assert rc.check(TiltChange(0, -3.0), world, 10, pred=pred(TiltChange(0, -3.0))).status == "rejected"
    ok = rc.check(PowerChange(0, 1.0), world, 10, pred=pred(PowerChange(0, 1.0)), confidence=0.95)
    assert ok.status == "approved"


def test_rules_let_a_tower_go_back_to_its_planned_settings(world):
    rc = RuleChecker(Policy.load(), world)
    misconfigure_tower(world, 2, 6.0, -7.0)  # +6 dB, 7 degrees up: far outside the normal step
    back = PowerChange(2, -6.0)
    v = rc.check(back, world, 10, pred=pred(back), confidence=0.9)
    assert v.status == "approved", v.reasons
    overshoot = PowerChange(2, -8.0)
    assert rc.check(overshoot, world, 10, pred=pred(overshoot)).status == "rejected"


def test_rules_protect_the_hospital_zone(world):
    rc = RuleChecker(Policy.load(), world)
    move = Handover((0, 1, 2), 1)
    v = rc.check(move, world, 10, pred=pred(move, zone={"Hospital zone": 0.69}))  # inside limit, but not the margin
    assert v.status == "rejected" and any("Hospital zone" in r for r in v.reasons)
    v = rc.check(move, world, 10, pred=pred(move, zone={"Hospital zone": 0.40}), confidence=0.95)
    assert v.status == "approved"
    # Already over the limit (a crowd on the hospital's tower): a change that takes load off it is not blocked,
    # judged against the twin's own "do nothing" load rather than the measured one.
    relief = pred(PowerChange(0, 1.0), zone={"Hospital zone": 3.1})
    relief.zone_loads_if_nothing = {"Hospital zone": 3.5}
    v = rc.check(relief.action, world, 10, pred=relief, confidence=0.95)
    assert not any("Hospital zone" in r for r in v.reasons)
    worse = pred(PowerChange(0, 1.0), zone={"Hospital zone": 3.6})
    worse.zone_loads_if_nothing = {"Hospital zone": 3.5}
    assert any("Hospital zone" in r for r in rc.check(worse.action, world, 10, pred=worse).reasons)


def test_rules_cooldown_and_harm(world):
    rc = RuleChecker(Policy.load(), world)
    rc.record(PowerChange(0, 1.0), 10)
    assert rc.check(PowerChange(0, 1.0), world, 12, pred=pred(PowerChange(0, 1.0))).status == "rejected"
    assert rc.check(PowerChange(0, 1.0), world, 25, pred=pred(PowerChange(0, 1.0)), confidence=0.95).ok
    hurt = pred(BeamOverride(0, (0,), 3), harmed=5)
    assert rc.check(hurt.action, world, 30, pred=hurt).status == "rejected"


def test_rules_ask_a_person_for_big_or_unsure_changes(world):
    rc = RuleChecker(Policy.load(), world)
    big = PowerChange(0, 3.0)
    assert rc.check(big, world, 10, pred=pred(big), confidence=0.95).status == "needs_approval"
    small = BeamOverride(0, (0,), 3)
    assert rc.check(small, world, 10, pred=pred(small), confidence=0.4).status == "needs_approval"
    assert rc.check(small, world, 10, pred=pred(small), confidence=0.7).status == "approved"


# ---------------------------------------------------------------- twin and monitor

def test_calibrated_twin_tracks_reports_better_than_the_raw_twin():
    w = station_road()
    w.run(4)
    base = w.last
    obs = base.rsrp_beam_dbm.max(axis=1)
    raw = w.twin()
    raw_pred = 10 * np.log10(raw.received_power(raw.trace()).max(axis=1))
    cal, _ = build_twin(w, base, [])
    cal_pred = 10 * np.log10(cal.received_power(cal.trace()).max(axis=1))
    ok = obs > -115
    assert np.abs(cal_pred - obs)[ok].mean() < 0.5 * np.abs(raw_pred - obs)[ok].mean()


def test_twin_hypothesis_sees_the_bus_without_being_told():
    w = station_road()
    w.missing_relations = {(0, 1), (0, 2)}
    w.run(4)
    base = w.last
    add_blocker(w, "bus", *BUS_POSITION)
    w.step()
    phones = [u.id for u in w.ues if u.group == "bus_stop"]
    tw, notes = build_twin(w, base, phones)
    assert not any(b.kind == "bus" for b in tw.boxes)  # the twin was not told about the bus
    assert len(notes["assumed_extra_loss"]) >= 8  # but it assumes the extra loss a blocker causes
    df = tw.copy().run(1).set_index("ue")
    real = w.snapshot().set_index("ue")
    assert abs(df.loc[phones].sinr_db.median() - real.loc[phones].sinr_db.median()) < 4


def test_quiet_street_raises_no_alarms():
    w = station_road()
    ag = Agent(w)
    for _ in range(40):
        w.step()
        ag.on_tick()
    assert not ag.incidents


# ---------------------------------------------------------------- whole scenarios (need the trained model)

@needs_model
def test_bus_with_hospital_conflict_never_breaks_the_zone():
    from nethealers.eval.runner import run_one

    r = run_one("5_conflict", "agent", 1)
    assert r["zone_violations"] == 0 and r["limit_violations"] == 0
    stages = [e["stage"] for e in r["events"]]
    assert "detect" in stages and "diagnose" in stages
    assert any("Hospital zone" in e["text"] for e in r["events"] if e["stage"] == "check")


@needs_model
def test_wrong_beam_is_fixed_quickly():
    from nethealers.eval.runner import run_one

    r = run_one("3_wrong_beam", "agent", 2)
    assert r["recovered"] and r["recovery_s"] <= 10
    assert r["diagnosis"] == "wrong_beam"


@needs_model
def test_faulty_controls_are_detected_and_escalated():
    from nethealers.eval.runner import run_one

    r = run_one("6_bad_data", "agent", 0)  # a seed where the agent needs the tower whose controls are broken
    texts = " ".join(e["text"] for e in r["events"])
    assert "did not accept the change" in texts
    assert "out-of-date" in texts
    assert r["limit_violations"] == 0


@needs_model
def test_twin_mismatch_is_caught_and_undone():
    from nethealers.eval.runner import run_one

    r = run_one("4_twin_mismatch", "agent", 1)
    assert r["undos"] >= 1
    assert r["degraded_phone_seconds"] < 0.6 * run_one("4_twin_mismatch", "standard", 1)["degraded_phone_seconds"]


@needs_model
def test_a_withdrawn_fix_is_no_longer_counted_as_an_active_change():
    from nethealers.diagnosis import Diagnoser
    from nethealers.sim import clear_problem

    w = station_road()
    w.missing_relations = {(0, 1), (0, 2)}
    w.zones = []
    ag = Agent(w, diagnoser=Diagnoser.load(), policy=Policy.load())
    w.run(8)
    for _ in range(8):
        w.step()
        ag.on_tick()
    bus = add_blocker(w, "bus", *BUS_POSITION)
    for _ in range(12):
        w.step()
        ag.on_tick()
    clear_problem(w, bus.id)
    for _ in range(15):
        w.step()
        ag.on_tick()
    if any(e.stage == "withdraw" for e in ag.log.events):
        assert not ag._active_changes()  # tidy-up must never undo a withdrawn fix a second time
