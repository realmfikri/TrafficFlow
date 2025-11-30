import pytest

from src.agents.vehicle import Vehicle, VehicleSpawner
from src.signals.lights import TrafficLight, TrafficSignalController


pytestmark = pytest.mark.unit


def test_traffic_light_cycles_between_phases():
    light = TrafficLight(phase_durations={"NS": 1.0, "EW": 2.0}, current_phase="NS")

    light.tick(0.5)
    assert light.current_phase == "NS"
    light.tick(0.6)
    assert light.current_phase == "EW"

    light.tick(1.0)
    assert light.current_phase == "EW"
    light.tick(1.1)
    assert light.current_phase == "NS"


def _simple_network():
    return {
        "nodes": [
            {"id": "n_0_0", "row": 0, "col": 0},
            {"id": "n_0_1", "row": 0, "col": 1},
            {"id": "n_0_2", "row": 0, "col": 2},
        ],
        "edges": [
            {
                "id": "e_west",
                "from": "n_0_0",
                "to": "n_0_1",
                "length": 10.0,
                "speed_limit": 10.0,
                "capacity": 2,
            },
            {
                "id": "e_east",
                "from": "n_0_1",
                "to": "n_0_2",
                "length": 10.0,
                "speed_limit": 10.0,
                "capacity": 2,
            },
        ],
    }


def test_vehicle_yields_to_red_and_proceeds_on_green():
    network = _simple_network()
    signals = TrafficSignalController(
        network, phase_durations={"NS": 1.0, "EW": 1.0}, start_phase="NS"
    )
    spawner = VehicleSpawner(max_vehicles=0)

    vehicle = Vehicle(
        "veh_1",
        route=network["edges"],
        patience=1.0,
        destination="n_0_2",
        velocity=5.0,
        position=9.0,
    )
    spawner.vehicles[vehicle.vehicle_id] = vehicle
    state = {"network": network, "signals": signals}

    # First tick: east-west movement should be red, vehicle waits
    spawner.tick(state, tick=0, dt=1.0)
    assert vehicle.current_edge_id == "e_west"
    assert vehicle.velocity == 0.0

    # Switch to EW green and allow the vehicle to clear the intersection
    signals.tick(1.0)
    spawner.tick(state, tick=1, dt=1.0)

    assert vehicle.current_edge_id == "e_east"
    assert vehicle.velocity > 0.0


def test_gridlock_prevents_entry_when_exit_is_full():
    network = _simple_network()
    signals = TrafficSignalController(network, start_phase="EW")
    spawner = VehicleSpawner(max_vehicles=0)

    follower = Vehicle(
        "veh_follow",
        route=network["edges"],
        patience=1.0,
        destination="n_0_2",
        velocity=5.0,
        position=9.0,
    )
    leader = Vehicle(
        "veh_lead",
        route=network["edges"],
        patience=1.0,
        destination="n_0_2",
        current_edge_index=1,
        position=9.0,
        velocity=0.0,
    )
    leader.stuck = True
    leader.stuck_ticks = 10

    spawner.vehicles[leader.vehicle_id] = leader
    spawner.vehicles[follower.vehicle_id] = follower
    state = {"network": network, "signals": signals}

    spawner.tick(state, tick=0, dt=1.0)

    # Follower should be held at the upstream edge because the exit edge is full/blocked
    assert follower.current_edge_id == "e_west"
    assert follower.velocity == 0.0
    assert follower.stuck_ticks > 0
