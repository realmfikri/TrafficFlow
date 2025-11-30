import pytest

from src.pathfinding.router import Router


@pytest.mark.integration
def test_router_adjusts_loads_and_reroutes_when_congested():
    network = {
        "nodes": [
            {"id": "A", "x": 0, "y": 0},
            {"id": "B", "x": 1, "y": 0},
            {"id": "C", "x": 2, "y": 0},
            {"id": "D", "x": 1, "y": 1},
        ],
        "edges": [
            {
                "id": "A_B",
                "from": "A",
                "to": "B",
                "length": 5.0,
                "speed_limit": 10.0,
                "capacity": 1,
            },
            {
                "id": "B_C",
                "from": "B",
                "to": "C",
                "length": 5.0,
                "speed_limit": 10.0,
                "capacity": 1,
            },
            {
                "id": "A_D",
                "from": "A",
                "to": "D",
                "length": 6.0,
                "speed_limit": 10.0,
                "capacity": 2,
            },
            {
                "id": "D_C",
                "from": "D",
                "to": "C",
                "length": 6.0,
                "speed_limit": 10.0,
                "capacity": 2,
            },
        ],
    }

    router = Router(network, congestion_threshold=0.8, reroute_cooldown=0)
    initial_route = router.register_vehicle("veh_1", "A", "C", tick=0)
    assert [edge["id"] for edge in initial_route] == ["A_B", "B_C"]

    # External congestion makes the original path undesirable
    router.record_external_load("A_B", delta=2)
    router.record_external_load("B_C", delta=2)

    rerouted = router.update_vehicle_position("veh_1", "A", tick=1)
    assert [edge["id"] for edge in rerouted] == ["A_D", "D_C"]

    # As the vehicle traverses edges, loads should be decremented
    router.mark_edge_complete("veh_1", "A_D")
    assert router._edge_loads["A_D"] == 0

    router.release_vehicle("veh_1")
    assert router._edge_loads.get("D_C", 0) == 0
