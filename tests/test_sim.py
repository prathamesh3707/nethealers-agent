import numpy as np
import pytest

from nethealers.sim import (
    ActionError,
    BeamOverride,
    Handover,
    LoadRebalance,
    PowerChange,
    TiltChange,
    add_blocker,
    add_external_interferer,
    apply_action,
    clear_problem,
    crowd_surge,
    misconfigure_tower,
    random_city,
    station_road,
    stick_beams,
    undo_action,
    without,
)
from nethealers.sim.channel import REFLECT, panel_gain_db, path_loss_los_db, path_loss_nlos_db, trace_paths
from nethealers.sim.config import PanelConfig
from nethealers.sim.geometry import Box, boxes_array, segments_hit_boxes, walls_of
from nethealers.sim.layouts import BUS_POSITION
from nethealers.sim.world import UE, Tower, World


def sinr_of(df, ids):
    return df.set_index("ue").loc[ids].true_sinr_db


# ---------------------------------------------------------------- physics building blocks

def test_path_loss_matches_3gpp_umi_los():
    # TR 38.901 UMi LOS at 100 m and 28 GHz: 32.4 + 21*2 + 20*log10(28) = 103.34 dB
    assert path_loss_los_db(100.0, 28.0) == pytest.approx(103.34, abs=0.01)
    assert path_loss_nlos_db(100.0, 28.0) > path_loss_los_db(100.0, 28.0)


def test_beam_gain_peaks_where_it_points():
    panel = PanelConfig()
    beam_az = np.linspace(-56, 56, 16)
    gains = panel_gain_db(beam_az, np.zeros(16), np.zeros(16), beam_az, panel)
    assert (gains.argmax(axis=1) == np.arange(16)).all()
    assert gains[8, 8] == pytest.approx(8 + 10 * np.log10(64), abs=1.5)  # element 8 dBi + 64-element array


def test_segment_box_hits():
    box = boxes_array([Box("b", 10, 20, -5, 5, 0, 10)])
    p0 = np.array([[0.0, 0, 5], [0.0, 0, 15], [0.0, 0, 5]])
    p1 = np.array([[30.0, 0, 5], [30.0, 0, 15], [10.0, 0, 5]])  # through, above, stops at the face
    assert segments_hit_boxes(p0, p1, box)[:, 0].tolist() == [True, False, False]


def test_mirror_reflection_off_one_wall():
    wall_box = Box("w", -50, 50, 20, 30, 0, 30, material="glass")
    walls = walls_of(wall_box)
    tower = np.array([[-10.0, 0, 10]])
    ue = np.array([[10.0, 0, 10]])
    paths = trace_paths(tower, ue, boxes_array([wall_box]), np.zeros((0, 6)), np.zeros(0), walls,
                        np.full(len(walls), 4.0), 28.0, 10.0)
    refl = paths.subset(paths.kind == REFLECT)
    assert len(refl) == 1
    assert refl.length_m[0] == pytest.approx(2 * np.hypot(10, 20))  # image method: unfolded path
    assert refl.via[0][1] == pytest.approx(20.0)  # bounces on the south face


def test_blocker_adds_its_loss_to_the_direct_path():
    def world(with_bus):
        w = World("t", [], [Tower(0, "T", 0, 0, 8, boresight_deg=0)], [UE(0, 100, 0)], seed=1)
        if with_bus:
            w.boxes.append(Box("bus", 60, 72, -1.3, 1.3, 0, 3.4, kind="bus", loss_db=25.0, dynamic=True))
        return w.trace()
    clear, blocked = world(False), world(True)
    d0 = clear.loss_db[clear.kind == 0][0]
    d1 = blocked.loss_db[blocked.kind == 0][0]
    assert d1 - d0 == pytest.approx(25.0, abs=1e-6)


# ---------------------------------------------------------------- the street behaves sensibly

def test_normal_day_is_healthy():
    w = station_road()
    df = w.run(4)
    assert (df.true_sinr_db >= 0).all()
    assert (df.throughput_mbps >= 0.95 * df.demand_mbps).all()
    assert (df.true_sinr_db >= 13).mean() > 0.5


def test_bus_blocks_tower_a_by_about_its_loss():
    w = station_road()
    w.missing_relations = {(0, 1), (0, 2)}  # no escape: the coverage hole stays
    base = w.run(4)
    bus_stop = base[base.group == "bus_stop"].ue.tolist()
    a_before = 10 * np.log10(w.last.rx_mw[0].max(axis=0))
    add_blocker(w, "bus", *BUS_POSITION)
    after = w.run(3)
    a_after = 10 * np.log10(w.last.rx_mw[0].max(axis=0))
    idx = w.ue_index()
    drops = np.array([a_after[idx[u]] - a_before[idx[u]] for u in bus_stop])
    assert np.median(drops) < -18  # 25 dB bus, minus what still bounces around it
    assert sinr_of(after, bus_stop).median() < 0


def test_built_in_handover_rescues_when_neighbours_exist():
    w = station_road()
    base = w.run(4)
    bus_stop = base[base.group == "bus_stop"].ue.tolist()
    add_blocker(w, "bus", *BUS_POSITION)
    first = w.step()
    later = w.run(3)
    assert sinr_of(later, bus_stop).median() > sinr_of(first, bus_stop).median() + 10


def test_stuck_beam_hurts_and_override_fixes():
    w = station_road()
    base = w.run(4)
    ids = base[base.group == "bus_stop"].ue.tolist()[:6]
    stick_beams(w, ids, offset=3)
    bad = w.run(2)
    ids = [i for i in ids if w.ue(i).serving == 0]
    best = int(bad.set_index("ue").loc[ids].best_beam.mode()[0])
    apply_action(w, BeamOverride(0, tuple(ids), best))
    good = w.run(2)
    assert sinr_of(bad, ids).median() < sinr_of(base, ids).median() - 5
    assert sinr_of(good, ids).median() > sinr_of(bad, ids).median() + 5


def test_misconfigured_neighbour_raises_interference_and_clears_exactly():
    w = station_road()
    base = w.run(4)
    p = misconfigure_tower(w, 2, 5.0, -6.0)
    bad = w.run(3)
    assert bad.true_sinr_db.median() < base.true_sinr_db.median() - 1
    clear_problem(w, p.id)
    assert (w.towers[2].power_dbm, w.towers[2].tilt_deg) == (33.0, 10.0)


def test_external_interferer_hurts_nearby_phones():
    w = station_road()
    base = w.run(4)
    add_external_interferer(w, 232, 100)
    bad = w.run(2)
    near = base[(abs(base.x - 232) < 25) & (base.group == "bus_stop")].ue.tolist()
    assert sinr_of(bad, near).median() < sinr_of(base, near).median() - 6


def test_crowd_surge_overloads_and_clears():
    w = station_road()
    n = len(w.ues)
    w.run(4)
    p = crowd_surge(w, 200, 114, 12, 60, demand_mbps=20)
    df = w.run(3)
    assert w.last.load.max() > 1
    assert (df.throughput_mbps < 0.95 * df.demand_mbps).sum() > 5
    clear_problem(w, p.id)
    assert len(w.ues) == n


# ---------------------------------------------------------------- twin, fixes, undo

def test_twin_leaves_out_what_the_operator_cant_see():
    w = station_road()
    w.run(2)
    add_blocker(w, "kiosk", 230, 111, hidden=True)
    add_blocker(w, "bus", *BUS_POSITION)
    add_external_interferer(w, 232, 100)
    tw = w.twin()
    assert not any(b.hidden or b.dynamic for b in tw.boxes)
    assert tw.interferers == []
    df = tw.step()
    assert np.allclose(df.sinr_db, df.true_sinr_db)  # no measurement noise in the twin
    aware = w.twin(include_dynamic=True)
    assert any(b.kind == "bus" for b in aware.boxes) and not any(b.hidden for b in aware.boxes)


@pytest.mark.parametrize("action", [
    BeamOverride(0, (0, 1), 3),
    Handover((0, 1, 2), 2),
    PowerChange(0, 2.0),
    TiltChange(1, -2.0),
    LoadRebalance(0, 1, 4.0),
])
def test_every_fix_undoes_exactly(action):
    w = station_road()
    w.run(3)
    if isinstance(action, BeamOverride):
        action = BeamOverride(w.ue(0).serving, tuple(u for u in (0, 1) if w.ue(u).serving == w.ue(0).serving), 3)
    ref, test = w.copy(), w.copy()
    rec = apply_action(test, action)
    undo_action(test, rec)
    assert np.allclose(ref.step().true_sinr_db, test.step().true_sinr_db)


def test_undoing_one_fix_keeps_a_later_fix_on_the_same_tower():
    w = station_road()
    first = apply_action(w, PowerChange(0, 2.0))
    apply_action(w, PowerChange(0, 1.0))
    undo_action(w, first)  # the second change (+1 dB) must survive
    assert w.towers[0].power_dbm == pytest.approx(station_road().towers[0].power_dbm + 1.0)
    a = apply_action(w, LoadRebalance(0, 1, 3.0))
    apply_action(w, LoadRebalance(0, 1, 2.0))
    undo_action(w, a)
    assert w.cio[(0, 1)] == pytest.approx(2.0) and w.cio[(1, 0)] == pytest.approx(-2.0)


def test_a_fix_for_phones_that_left_is_refused_cleanly():
    w = station_road()
    w.run(2)
    with pytest.raises(ActionError):
        apply_action(w, Handover((0, 9999), 1))
    with pytest.raises(ActionError):
        apply_action(w, BeamOverride(w.ue(0).serving, (0, 9999), 2))


def test_physical_limits_are_enforced():
    w = station_road()
    with pytest.raises(ActionError):
        apply_action(w, PowerChange(0, 10.0))
    with pytest.raises(ActionError):
        apply_action(w, TiltChange(0, -20.0))
    with pytest.raises(ActionError):
        apply_action(w, LoadRebalance(0, 1, 12.0))


def test_without_removes_every_problem():
    w = station_road()
    w.run(2)
    add_blocker(w, "bus", *BUS_POSITION)
    misconfigure_tower(w, 2)
    clean = without(w)
    assert clean.problems == {} and not any(b.dynamic for b in clean.boxes)
    assert clean.towers[2].power_dbm == 33.0
    assert len(w.problems) == 2  # the original is untouched


# ---------------------------------------------------------------- random cities and repeatability

@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_city_is_valid(seed):
    w = random_city(seed)
    for u in w.ues:
        assert not any(b.contains_xy(u.x, u.y) for b in w.boxes)
    df = w.run(3)
    assert np.isfinite(df.true_sinr_db).all() and len(df) == 60


def test_same_seed_same_results():
    a = station_road(seed=5).run(3)
    b = station_road(seed=5).run(3)
    assert np.allclose(a.sinr_db, b.sinr_db) and np.allclose(a.true_sinr_db, b.true_sinr_db)


def test_fixing_a_misconfigured_tower_restores_its_settings_even_after_compensation():
    w = station_road()
    before = (w.towers[2].power_dbm, w.towers[2].tilt_deg)
    p = misconfigure_tower(w, 2, 6.0, -7.0)
    apply_action(w, TiltChange(2, 7.0))  # someone compensated in the meantime
    clear_problem(w, p.id)
    assert (w.towers[2].power_dbm, w.towers[2].tilt_deg) == before  # back to plan, not plan + 7 degrees
