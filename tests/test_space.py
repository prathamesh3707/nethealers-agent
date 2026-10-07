import pytest

from nethealers.api.session import MAX_WAIT_TICKS, new_session
from nethealers.sim import space
from nethealers.sim.layouts import BUS_POSITION

LANE_Y = BUS_POSITION[1]


def rect_of(session, pid):
    b = session.world.box(pid)
    return b.xmin, b.xmax, b.ymin, b.ymax


def gap_between(a, b):
    return max(b[0] - a[1], a[0] - b[1])


@pytest.fixture
def game():
    return new_session(agent=False)


def test_a_second_vehicle_slides_to_the_next_free_spot(game):
    bus = game.add_problem("bus", 200, LANE_Y)
    truck = game.add_problem("truck", 200, LANE_Y)  # dropped right on top of the bus
    assert truck["x"] != 200
    assert gap_between(rect_of(game, bus["id"]), rect_of(game, truck["id"])) >= space.GAP_M - 1e-6
    # ...and so does its copy in the "without the agent" street
    tb = game.shadow.box(game.shadow_ids[truck["id"]])
    assert (tb.xmin + tb.xmax) / 2 == pytest.approx(truck["x"])


def test_a_full_lane_is_refused_with_a_reason(game):
    with pytest.raises(ValueError, match="No room"):
        for _ in range(60):
            game.add_problem("bus", 200, LANE_Y)


def test_other_blockers_cant_be_dropped_on_vehicles_or_buildings(game):
    game.add_problem("bus", 200, LANE_Y)
    with pytest.raises(ValueError, match="taken by the bus"):
        game.add_problem("kiosk", 200, LANE_Y)
    with pytest.raises(ValueError, match="taken by Glass office"):
        game.add_problem("kiosk", 278, 150)  # inside the Glass office


def test_moving_a_vehicle_stops_short_of_the_one_in_front(game):
    front = game.add_problem("bus", 230, LANE_Y)
    back = game.add_problem("car", 190, LANE_Y)
    game.move_problem(back["id"], 260, LANE_Y)  # try to drive straight through the bus
    gap = gap_between(rect_of(game, back["id"]), rect_of(game, front["id"]))
    assert space.GAP_M - 1e-6 <= gap <= space.GAP_M + space.MOVE_STEP_M + 1e-6
    assert rect_of(game, back["id"])[1] < rect_of(game, front["id"])[0]  # still behind it


def test_moving_into_open_road_works_normally(game):
    car = game.add_problem("car", 150, LANE_Y)
    game.move_problem(car["id"], 160, LANE_Y)
    b = game.world.box(car["id"])
    assert (b.xmin + b.xmax) / 2 == pytest.approx(160)


def test_a_driving_vehicle_queues_and_eventually_turns_off(game):
    game.add_problem("bus", 210, LANE_Y)  # parked across the route
    car = game.add_problem("car", 240, LANE_Y, drive=True)  # drives in from 40 m back, through the bus
    for _ in range(6):
        game.tick()
        c = game.world.box(car["id"])
        for other in game.world.boxes:
            if other.kind != "building" and other.name != car["id"]:
                a = (c.xmin, c.xmax, c.ymin, c.ymax)
                o = (other.xmin, other.xmax, other.ymin, other.ymax)
                assert not space._touch(a, o, 0.0), "vehicles overlapped"
    assert game.waiting.get(car["id"], 0) > 0  # it is queueing behind the bus
    for _ in range(MAX_WAIT_TICKS + 2):
        game.tick()
    assert car["id"] not in game.world.problems  # gave up and left the street
