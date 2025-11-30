"""Simple traffic light state machines for grid intersections."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class TrafficLight:
    """Two-phase traffic light with configurable north/south and east/west durations."""

    phase_durations: Dict[str, float] = field(
        default_factory=lambda: {"NS": 30.0, "EW": 30.0}
    )
    current_phase: str = "NS"
    elapsed: float = 0.0

    def tick(self, dt: float) -> None:
        self.elapsed += dt
        duration = float(self.phase_durations.get(self.current_phase, 0))
        if duration <= 0:
            return
        if self.elapsed >= duration:
            self.elapsed = 0.0
            self.current_phase = "EW" if self.current_phase == "NS" else "NS"

    def allows(self, orientation: str) -> bool:
        return self.current_phase == orientation.upper()


class TrafficSignalController:
    """Manage a collection of :class:`TrafficLight` objects for a network."""

    def __init__(
        self,
        network: Dict,
        *,
        phase_durations: Optional[Dict[str, float]] = None,
        start_phase: str = "NS",
    ) -> None:
        self.network = network
        self.phase_durations = phase_durations or {"NS": 30.0, "EW": 30.0}
        self.lights: Dict[str, TrafficLight] = {
            node.get("id"): TrafficLight(
                phase_durations=self.phase_durations.copy(),
                current_phase=start_phase,
            )
            for node in network.get("nodes", [])
        }
        self._node_lookup = {node.get("id"): node for node in network.get("nodes", [])}

    def _orientation(self, from_id: str, to_id: str) -> str:
        from_node = self._node_lookup.get(from_id, {})
        to_node = self._node_lookup.get(to_id, {})

        from_row = from_node.get("row", from_node.get("y"))
        to_row = to_node.get("row", to_node.get("y"))
        from_col = from_node.get("col", from_node.get("x"))
        to_col = to_node.get("col", to_node.get("x"))

        if from_row is not None and to_row is not None and from_row != to_row:
            return "NS"
        if from_col is not None and to_col is not None and from_col != to_col:
            return "EW"
        # Fallback for degenerate data
        return "NS"

    def tick(self, dt: float) -> None:
        for light in self.lights.values():
            light.tick(dt)

    def can_enter(self, current_edge: Dict, next_edge: Dict) -> bool:
        dest = current_edge.get("to")
        light = self.lights.get(dest)
        if light is None:
            return True
        orientation = self._orientation(current_edge.get("from"), dest)
        return light.allows(orientation)

    def register(self, engine) -> None:
        """Register the controller as a simulation agent."""

        def _callback(state: Dict, tick: int) -> None:
            self.tick(engine.config.tick_duration)

        engine.state["signals"] = self
        engine.register_agent("signals", _callback, start_tick=0, interval=1)

