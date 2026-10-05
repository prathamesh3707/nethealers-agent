from pathlib import Path

import numpy as np
import pytest

from nethealers.diagnosis.dataset import run_episode
from nethealers.diagnosis.features import feature_columns, lwm_columns, phone_features
from nethealers.diagnosis.lwm import N_ANT, N_SUB, channel_grids, tokenize
from nethealers.sim import add_blocker, station_road
from nethealers.sim.layouts import BUS_POSITION


def test_features_use_only_what_the_network_sees():
    df = run_episode(11, with_lwm=False)
    cols = feature_columns(df)
    assert cols, "no features"
    for c in cols:
        assert not c.startswith("true"), c
        assert c not in {"label", "kind", "affected", "fixable", "x", "y", "group"}, c
    assert np.isfinite(df[cols].to_numpy(dtype=float)).all()


def test_bus_shows_up_as_a_signal_drop_without_extra_interference():
    w = station_road()
    w.missing_relations = {(0, 1), (0, 2)}
    w.run(4)
    base_frames, base_result = w.history[-3:], w.last
    add_blocker(w, "bus", *BUS_POSITION)
    w.step()
    f = phone_features(w, base_frames, base_result)
    hurt = f[f.d_sinr < -10]
    assert len(hurt) >= 6
    assert hurt.d_rsrp.median() < -15  # own tower got much weaker
    assert abs(hurt.d_interf.median()) < 3  # interference didn't change


@pytest.mark.parametrize("seed", [2, 5, 8, 13, 21, 34])
def test_episode_labels_match_the_problem(seed):
    df = run_episode(seed, with_lwm=False)
    hurt = df[df.label != "none"]
    if len(hurt):
        expected = {"bus": "blockage", "truck": "blockage", "car": "blockage", "crowd": "blockage",
                    "kiosk": "blockage", "hoarding": "blockage", "stuck_beam": "wrong_beam",
                    "neighbour_misconfig": "interference", "external_interferer": "interference",
                    "crowd_surge": "congestion"}[df.kind.iloc[0]]
        if expected == "congestion":  # phones on other towers are hurt by the busy tower's interference
            assert set(hurt.label) <= {"congestion", "interference"}
        else:
            assert set(hurt.label) == {expected}
    assert (df[df.kind == "none"].label == "none").all()


def test_lwm_input_shape():
    w = station_road()
    w.run(2)
    pairs = [(u.serving, i) for i, u in enumerate(w.ues[:5])]
    grids = channel_grids(w.last.paths, pairs, np.array([t.boresight_deg for t in w.towers]), 28.0)
    assert grids.shape == (5, N_ANT, N_SUB)
    assert np.abs(grids).max() > 0
    assert tokenize(grids).shape == (5, 129, 16)


def test_episode_with_lwm_adds_fingerprints():
    df = run_episode(4, with_lwm=True)
    cols = lwm_columns(df)
    assert len(cols) == 64 + 64 + 1
    assert np.isfinite(df[cols].to_numpy(dtype=float)).all()


MODEL = Path(__file__).resolve().parents[1] / "models" / "diagnosis.joblib"


@pytest.mark.skipif(not MODEL.exists(), reason="train the model first: scripts/train_diagnosis.py")
def test_trained_model_names_the_right_causes_on_station_road():
    from nethealers.diagnosis import Diagnoser
    from nethealers.sim import misconfigure_tower

    d = Diagnoser.load()
    # A bus with no escape: the bus-stop phones should read as blockage.
    w = station_road()
    w.missing_relations = {(0, 1), (0, 2)}
    w.run(4)
    base_frames, base_result = w.history[-3:], w.last
    add_blocker(w, "bus", *BUS_POSITION)
    w.step()
    bus_stop = [u.id for u in w.ues if u.group == "bus_stop"]
    rep = d.diagnose(w, base_frames, base_result, phones=bus_stop)
    hurt = rep.loc[[u for u in bus_stop if w.snapshot().set_index("ue").loc[u, "true_sinr_db"] < 0]]
    assert (hurt.cause == "blockage").mean() >= 0.7
    # A misconfigured tower: the phones it hurts should read as interference.
    w = station_road()
    w.run(4)
    base_frames, base_result = w.history[-3:], w.last
    misconfigure_tower(w, 2, 6.0, -7.0)
    w.step()
    now = w.snapshot().set_index("ue")
    before = base_frames[-1].set_index("ue")
    hurt_ids = [u for u in now.index if now.loc[u, "true_sinr_db"] < before.loc[u, "true_sinr_db"] - 5]
    rep = d.diagnose(w, base_frames, base_result, phones=hurt_ids)
    assert len(rep) >= 3 and (rep.cause == "interference").mean() >= 0.6
