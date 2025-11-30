import pytest

from src.pathfinding.router import Router


@pytest.fixture
def simple_network():
    return {
        "nodes": [
            {"id": "A", "x": 0, "y": 0},
            {"id": "B", "x": 1, "y": 0},
            {"id": "C", "x": 2, "y": 0},
            {"id": "D", "x": 1, "y": 1},
        ],
        "edges": [
            {"id": "A_B", "from": "A", "to": "B", "length": 10.0, "speed_limit": 10.0, "capacity": 1},
            {"id": "B_C", "from": "B", "to": "C", "length": 10.0, "speed_limit": 10.0, "capacity": 1},
            {"id": "A_D", "from": "A", "to": "D", "length": 15.0, "speed_limit": 10.0, "capacity": 2},
            {"id": "D_C", "from": "D", "to": "C", "length": 10.0, "speed_limit": 10.0, "capacity": 2},
        ],
    }


def test_initial_routing_prefers_fastest_path(simple_network):
    router = Router(simple_network)
    route = router.plan_route("A", "C")
    # A -> B -> C should be preferred because it has lower travel time than A -> D -> C
    assert [edge["id"] for edge in route] == ["A_B", "B_C"]


def test_congestion_triggers_reroute(simple_network):
    router = Router(simple_network, congestion_threshold=1.0, reroute_cooldown=0)
    initial_route = router.register_vehicle("veh_1", "A", "C", tick=0)
    # Another vehicle taking the same path increases load on the shared edges
    router.register_vehicle("veh_2", "A", "C", tick=0)

    # Move vehicle 1 forward in time; congestion should now push it to the alternate path
    new_route = router.update_vehicle_position("veh_1", "A", tick=1)
    assert [edge["id"] for edge in initial_route] == ["A_B", "B_C"]
    assert [edge["id"] for edge in new_route] == ["A_D", "D_C"]


def test_respects_reroute_cooldown(simple_network):
    router = Router(simple_network, congestion_threshold=1.0, reroute_cooldown=3)
    router.register_vehicle("veh_1", "A", "C", tick=0)
    router.register_vehicle("veh_2", "A", "C", tick=0)

    # Within the cooldown window, reroute should not occur even though congestion is high
    same_route = router.update_vehicle_position("veh_1", "A", tick=1)
    assert [edge["id"] for edge in same_route] == ["A_B", "B_C"]

    # After the cooldown window passes, rerouting is allowed
    rerouted = router.update_vehicle_position("veh_1", "A", tick=4)
    assert [edge["id"] for edge in rerouted] == ["A_D", "D_C"]


def test_blocking_edge_forces_new_path(simple_network):
    router = Router(simple_network, reroute_cooldown=0)
    router.register_vehicle("veh_1", "A", "C", tick=0)

    router.block_edge("A_B", tick=1)
    rerouted = router.update_vehicle_position("veh_1", "A", tick=1)

    assert [edge["id"] for edge in rerouted] == ["A_D", "D_C"]
    assert "A_B" in router._blocked_edges

