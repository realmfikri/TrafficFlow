import math

import pytest

from src.agents.vehicle import Vehicle, VehicleSpawner


pytestmark = pytest.mark.unit


@pytest.fixture
def simple_route():
    return [
        {"id": "edge_a", "from": "n_0_0", "to": "n_0_1", "length": 10.0, "speed_limit": 20.0},
    ]


def test_idm_acceleration_free_road(simple_route):
    vehicle = Vehicle("v1", route=simple_route, patience=1.0, destination="n_0_1", velocity=10.0)
    accel = vehicle.compute_acceleration(leader=None, dt=1.0)
    assert accel == pytest.approx(0.9375, rel=1e-4)


def test_idm_acceleration_with_leader(simple_route):
    follower = Vehicle(
        "v1", route=simple_route, patience=1.0, destination="n_0_1", position=5.0, velocity=10.0
    )
    leader = Vehicle(
        "v2", route=simple_route, patience=1.0, destination="n_0_1", position=20.0, velocity=8.0
    )

    accel = follower.compute_acceleration(leader=leader, dt=1.0)

    expected_gap = max(leader.position - follower.position - leader.length, 0.1)
    relative_speed = follower.velocity - leader.velocity
    s_star = follower.minimum_spacing + max(
        0.0,
        follower.velocity * follower.desired_time_headway
        + (follower.velocity * relative_speed)
        / (2 * math.sqrt(follower.acceleration_max * follower.deceleration_comfortable)),
    )
    expected = follower.acceleration_max * (
        1
        - (follower.velocity / follower.desired_speed()) ** follower.delta
        - (s_star / expected_gap) ** 2
    )

    assert accel == pytest.approx(expected, rel=1e-4)


def test_vehicle_arrival_removes_from_spawner():
    network = {
        "nodes": [
            {"id": "n_0_0"},
            {"id": "n_0_1"},
        ],
        "edges": [
            {"id": "e_forward", "from": "n_0_0", "to": "n_0_1", "length": 5.0, "speed_limit": 5.0},
            {"id": "e_backward", "from": "n_0_1", "to": "n_0_0", "length": 5.0, "speed_limit": 5.0},
        ],
    }

    spawner = VehicleSpawner(random_seed=42, max_vehicles=1, spawn_interval=100)
    state = {"network": network}

    for tick in range(3):
        spawner.tick(state, tick, dt=1.0)

    assert len(spawner.vehicles) == 1

    # Advance enough for the vehicle to traverse the short edge and be removed
    for tick in range(3, 10):
        spawner.tick(state, tick, dt=1.0)

    assert len(spawner.vehicles) == 0
