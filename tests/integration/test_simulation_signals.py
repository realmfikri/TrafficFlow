import pytest

from src.agents.vehicle import Vehicle
from src.map.generator import GridConfig
from src.signals.lights import TrafficSignalController
from src.simulation.core import SimulationConfig, SimulationEngine


@pytest.mark.integration
def test_vehicle_waits_for_signal_and_proceeds():
    network = {
        "nodes": [
            {"id": "n_0_0", "row": 0, "col": 0},
            {"id": "n_0_1", "row": 0, "col": 1},
            {"id": "n_0_2", "row": 0, "col": 2},
        ],
        "edges": [
            {
                "id": "e_n_0_0_to_n_0_1",
                "from": "n_0_0",
                "to": "n_0_1",
                "length": 10.0,
                "speed_limit": 10.0,
                "capacity": 2,
            },
            {
                "id": "e_n_0_1_to_n_0_2",
                "from": "n_0_1",
                "to": "n_0_2",
                "length": 10.0,
                "speed_limit": 10.0,
                "capacity": 2,
            },
        ],
    }

    config = SimulationConfig(tick_duration=1.0, grid=GridConfig(rows=1, cols=3, block_length=10.0))
    engine = SimulationEngine(config, network=network)

    controller = TrafficSignalController(
        network,
        phase_durations={"NS": 2.0, "EW": 2.0},
        start_phase="NS",
    )
    controller.register(engine)

    vehicle = Vehicle(
        "veh_1",
        route=network["edges"],
        patience=1.0,
        destination="n_0_2",
        velocity=5.0,
        position=9.0,
    )
    history: list[tuple[int, str, float]] = []

    def _vehicle_agent(state, tick):
        vehicle.step(
            dt=engine.config.tick_duration,
            can_enter_next=lambda cur, nxt: controller.can_enter(cur, nxt) if nxt else True,
        )
        history.append((tick, vehicle.current_edge_id, vehicle.velocity))

    engine.register_agent("vehicle", _vehicle_agent, start_tick=0, interval=1)
    engine.run(max_ticks=2)

    first_tick_edge = history[0][1]
    assert first_tick_edge == "e_n_0_0_to_n_0_1"
    assert history[0][2] == 0.0

    second_tick_edge = history[1][1]
    assert second_tick_edge == "e_n_0_1_to_n_0_2"
    assert history[1][2] > 0.0
