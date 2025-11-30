"""Vehicle agents with basic car-following behavior and spawning utilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import math
import random


@dataclass
class Vehicle:
    """Simple Intelligent Driver Model (IDM) vehicle."""

    vehicle_id: str
    route: List[Dict]
    patience: float
    destination: str
    position: float = 0.0
    velocity: float = 0.0
    current_edge_index: int = 0
    arrived: bool = False
    length: float = 4.5
    acceleration: float = 0.0

    # IDM parameters
    desired_time_headway: float = 1.5
    minimum_spacing: float = 2.0
    acceleration_max: float = 1.0
    deceleration_comfortable: float = 1.5
    delta: int = 4

    def _current_edge(self) -> Dict:
        return self.route[self.current_edge_index]

    @property
    def current_edge_id(self) -> str:
        return self._current_edge().get("id", f"edge_{self.current_edge_index}")

    @property
    def edge_remaining(self) -> float:
        return max(self._current_edge().get("length", 0.0) - self.position, 0.0)

    def desired_speed(self) -> float:
        speed_limit = float(self._current_edge().get("speed_limit", 0.0))
        return max(speed_limit * self.patience, 0.0)

    def _idm_desired_gap(self, relative_speed: float) -> float:
        return self.minimum_spacing + max(
            0.0,
            self.velocity * self.desired_time_headway
            + (self.velocity * relative_speed)
            / (2 * math.sqrt(self.acceleration_max * self.deceleration_comfortable)),
        )

    def compute_acceleration(self, leader: Optional["Vehicle"], dt: float) -> float:
        """Compute IDM acceleration given an optional leader."""

        desired = self.desired_speed()
        if desired <= 0:
            return -self.deceleration_comfortable

        leader_gap = math.inf
        relative_speed = 0.0
        if leader is not None and leader.current_edge_id == self.current_edge_id:
            leader_gap = max(leader.position - self.position - leader.length, 0.1)
            relative_speed = self.velocity - leader.velocity

        s_star = self._idm_desired_gap(relative_speed)
        free_flow_term = (self.velocity / desired) ** self.delta
        interaction_term = (s_star / leader_gap) ** 2 if math.isfinite(leader_gap) else 0.0

        return self.acceleration_max * (1 - free_flow_term - interaction_term)

    def _advance_edge(self, distance: float) -> float:
        remaining = self.edge_remaining
        if distance < remaining:
            self.position += distance
            return 0.0

        distance -= remaining
        self.position = 0.0
        self.current_edge_index += 1

        if self.current_edge_index >= len(self.route):
            self.arrived = True
            self.velocity = 0.0
            return 0.0

        return distance

    def step(self, dt: float, leader: Optional["Vehicle"] = None) -> None:
        """Advance the vehicle by one tick using IDM dynamics."""

        if self.arrived:
            self.acceleration = 0.0
            self.velocity = 0.0
            return

        self.acceleration = self.compute_acceleration(leader, dt)
        new_velocity = max(0.0, min(self.desired_speed(), self.velocity + self.acceleration * dt))
        distance = max(self.velocity * dt + 0.5 * self.acceleration * dt * dt, 0.0)
        remaining_distance = distance

        while remaining_distance > 0 and not self.arrived:
            remaining_distance = self._advance_edge(remaining_distance)

        if not self.arrived:
            self.velocity = new_velocity
        else:
            self.velocity = 0.0


@dataclass
class VehicleSpawner:
    """Spawner responsible for creating and updating vehicles each tick."""

    max_vehicles: int = 2000
    patience_range: tuple[float, float] = (0.8, 1.2)
    destinations: Optional[List[str]] = None
    random_seed: Optional[int] = None
    spawn_interval: int = 1

    vehicles: Dict[str, Vehicle] = field(default_factory=dict)
    _tick_counter: int = 0
    _rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.random_seed)

    def _choose_destination(self, network: Dict) -> str:
        candidates = self.destinations or [n["id"] for n in network.get("nodes", [])]
        return self._rng.choice(candidates)

    def _build_route(self, network: Dict, destination: str) -> List[Dict]:
        edges = network.get("edges", [])
        if not edges:
            raise ValueError("Network must contain edges to build a route")

        by_from: Dict[str, List[Dict]] = {}
        for edge in edges:
            by_from.setdefault(edge["from"], []).append(edge)

        # Start from a random node
        start_node = self._rng.choice(network.get("nodes", []))
        start_id = start_node["id"]

        def _coords(node_id: str) -> tuple[int, int]:
            _, r, c = node_id.split("_")
            return int(r), int(c)

        route: List[Dict] = []
        current = start_id
        dest_row, dest_col = _coords(destination)
        cur_row, cur_col = _coords(current)

        while (cur_row, cur_col) != (dest_row, dest_col):
            step_options: List[Dict] = []
            if dest_col > cur_col:
                step_options.extend([e for e in by_from.get(current, []) if e["to"].endswith(f"_{cur_row}_{cur_col+1}")])
            elif dest_col < cur_col:
                step_options.extend([e for e in by_from.get(current, []) if e["to"].endswith(f"_{cur_row}_{cur_col-1}")])
            if dest_row > cur_row:
                step_options.extend([e for e in by_from.get(current, []) if e["to"].endswith(f"_{cur_row+1}_{cur_col}")])
            elif dest_row < cur_row:
                step_options.extend([e for e in by_from.get(current, []) if e["to"].endswith(f"_{cur_row-1}_{cur_col}")])

            if not step_options:
                step_options = by_from.get(current, [])

            if not step_options:
                raise ValueError("No outbound edges to continue route")

            edge_choice = self._rng.choice(step_options)
            route.append(edge_choice)
            current = edge_choice["to"]
            cur_row, cur_col = _coords(current)

        if not route:
            route.append(self._rng.choice(edges))

        return route

    def _spawn_vehicle(self, state: Dict, tick: int) -> None:
        network = state.get("network", {})
        destination = self._choose_destination(network)
        route = self._build_route(network, destination)
        patience = self._rng.uniform(*self.patience_range)

        vehicle_id = f"veh_{tick}_{len(self.vehicles)}"
        vehicle = Vehicle(
            vehicle_id=vehicle_id,
            route=route,
            patience=patience,
            destination=destination,
        )
        self.vehicles[vehicle_id] = vehicle

    def _leaders_by_edge(self) -> Dict[str, List[Vehicle]]:
        edges: Dict[str, List[Vehicle]] = {}
        for vehicle in self.vehicles.values():
            if vehicle.arrived:
                continue
            edges.setdefault(vehicle.current_edge_id, []).append(vehicle)

        for vehs in edges.values():
            vehs.sort(key=lambda v: v.position, reverse=True)
        return edges

    def _remove_arrived(self) -> None:
        to_remove = [vid for vid, v in self.vehicles.items() if v.arrived]
        for vid in to_remove:
            del self.vehicles[vid]

    def tick(self, state: Dict, tick: int, *, dt: float) -> None:
        """Spawn and advance vehicles for the given tick."""

        if self._tick_counter % self.spawn_interval == 0 and len(self.vehicles) < self.max_vehicles:
            self._spawn_vehicle(state, tick)
        self._tick_counter += 1

        ordering = self._leaders_by_edge()
        for vehicles in ordering.values():
            leader: Optional[Vehicle] = None
            for veh in vehicles:
                veh.step(dt, leader)
                leader = veh if not veh.arrived else None

        self._remove_arrived()

    def register(self, engine) -> None:
        """Register with the simulation engine for periodic updates."""

        def _callback(state: Dict, tick: int) -> None:
            self.tick(state, tick, dt=engine.config.tick_duration)

        engine.register_agent("vehicle_spawner", _callback, start_tick=0, interval=1)
        state = getattr(engine, "state", None)
        if isinstance(state, dict):
            state.setdefault("vehicles", self.vehicles)
