"""Vehicle agents with basic car-following behavior and spawning utilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple
import math
import random


class EdgeSpatialIndex:
    """Bucket vehicles by edge and position for cache-friendly iteration."""

    def __init__(self, bin_size: float = 20.0):
        self.bin_size = bin_size
        self.bins: Dict[str, Dict[int, List["Vehicle"]]] = {}

    def build(self, vehicles: Iterable["Vehicle"]):
        self.bins.clear()
        occupancy: Dict[str, int] = {}

        for vehicle in vehicles:
            if vehicle.arrived:
                continue
            edge_id = vehicle.current_edge_id
            bin_id = int(vehicle.position // self.bin_size)
            self.bins.setdefault(edge_id, {}).setdefault(bin_id, []).append(vehicle)
            occupancy[edge_id] = occupancy.get(edge_id, 0) + 1

        ordered: Dict[str, List["Vehicle"]] = {}
        for edge_id, bins in self.bins.items():
            segments = sorted(bins.items(), key=lambda kv: kv[0], reverse=True)
            vehicles_on_edge: List["Vehicle"] = []
            for _, segment in segments:
                segment.sort(key=lambda v: v.position, reverse=True)
                vehicles_on_edge.extend(segment)
            if vehicles_on_edge:
                ordered[edge_id] = vehicles_on_edge

        return ordered, occupancy


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

    # Simple stuck detection
    stuck_ticks: int = 0
    stuck: bool = False

    # IDM parameters
    desired_time_headway: float = 1.5
    minimum_spacing: float = 2.0
    acceleration_max: float = 1.0
    deceleration_comfortable: float = 1.5
    delta: int = 4

    def _current_edge(self) -> Dict:
        if not self.route:
            return {}
        clamped = min(self.current_edge_index, len(self.route) - 1)
        return self.route[clamped]

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

    def _advance_edge(
        self,
        distance: float,
        *,
        can_enter_next: Optional[Callable[[Dict, Optional[Dict]], bool]] = None,
    ) -> Tuple[float, bool]:
        remaining = self.edge_remaining
        blocked = False

        if remaining > 0 and distance < remaining:
            self.position += min(distance, remaining)
            return 0.0, blocked

        distance -= remaining
        next_edge_index = self.current_edge_index + 1
        next_edge: Optional[Dict] = None
        if next_edge_index < len(self.route):
            next_edge = self.route[next_edge_index]

        if next_edge is not None and can_enter_next is not None:
            if not can_enter_next(self._current_edge(), next_edge):
                # Wait at the end of the current edge
                self.position = self._current_edge().get("length", self.position)
                blocked = True
                return 0.0, blocked

        self.position = 0.0
        self.current_edge_index += 1

        if self.current_edge_index >= len(self.route):
            self.arrived = True
            self.velocity = 0.0
            return 0.0, blocked

        return distance, blocked

    def _update_stuck_state(self, was_blocked: bool) -> None:
        stationary = was_blocked or self.velocity < 0.1
        if stationary and not self.arrived:
            self.stuck_ticks += 1
        else:
            self.stuck_ticks = 0
        self.stuck = self.stuck_ticks >= 5

    def step(
        self,
        dt: float,
        leader: Optional["Vehicle"] = None,
        *,
        can_enter_next: Optional[Callable[[Dict, Optional[Dict]], bool]] = None,
    ) -> None:
        """Advance the vehicle by one tick using IDM dynamics.

        ``can_enter_next`` is a callback that determines whether the vehicle can
        proceed into the next edge (e.g., based on signals or downstream
        capacity). When blocked, the vehicle will wait at the end of its current
        edge and mark itself as stuck after several stationary ticks.
        """

        if self.arrived:
            self.acceleration = 0.0
            self.velocity = 0.0
            return

        self.acceleration = self.compute_acceleration(leader, dt)
        new_velocity = max(0.0, min(self.desired_speed(), self.velocity + self.acceleration * dt))
        distance = max(self.velocity * dt + 0.5 * self.acceleration * dt * dt, 0.0)
        remaining_distance = distance
        was_blocked = False

        while remaining_distance > 0 and not self.arrived:
            remaining_distance, blocked = self._advance_edge(
                remaining_distance, can_enter_next=can_enter_next
            )
            was_blocked = was_blocked or blocked

        if not self.arrived:
            self.velocity = 0.0 if was_blocked else new_velocity
        else:
            self.velocity = 0.0

        self._update_stuck_state(was_blocked)


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
    _spatial_index: EdgeSpatialIndex = field(default_factory=EdgeSpatialIndex, init=False)
    last_queue_lengths: Dict[str, int] = field(default_factory=dict, init=False)

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

    def _remove_arrived(self) -> None:
        to_remove = [vid for vid, v in self.vehicles.items() if v.arrived]
        for vid in to_remove:
            del self.vehicles[vid]

    def _blocked_edges(self, ordering: Dict[str, List[Vehicle]]) -> set[str]:
        blocked: set[str] = set()
        for edge_id, vehicles in ordering.items():
            for veh in vehicles:
                if veh.stuck and veh.edge_remaining < veh.length:
                    blocked.add(edge_id)
                    break
        return blocked

    def _can_enter_next_edge(
        self,
        current_edge: Dict,
        next_edge: Optional[Dict],
        occupancy: Dict[str, int],
        blocked_edges: set[str],
        signals,
        closed_edges: set[str],
    ) -> bool:
        if next_edge is None:
            return True

        next_capacity = int(next_edge.get("capacity", math.inf))
        next_id = next_edge.get("id")
        if occupancy.get(next_id, 0) >= next_capacity:
            return False
        if next_id in blocked_edges:
            return False
        if next_id in closed_edges:
            return False

        if signals is not None and hasattr(signals, "can_enter"):
            if not signals.can_enter(current_edge, next_edge):
                return False

        return True

    def tick(self, state: Dict, tick: int, *, dt: float) -> None:
        """Spawn and advance vehicles for the given tick."""

        if self._tick_counter % self.spawn_interval == 0 and len(self.vehicles) < self.max_vehicles:
            self._spawn_vehicle(state, tick)
        self._tick_counter += 1

        ordering, occupancy = self._spatial_index.build(self.vehicles.values())
        self.last_queue_lengths = occupancy
        signals = state.get("signals") if isinstance(state, dict) else None
        blocked_edges = self._blocked_edges(ordering)
        closed_edges: set[str] = set()
        if isinstance(state, dict):
            closed_edges = set(state.get("closed_edges", []))

        for vehicles in ordering.values():
            leader: Optional[Vehicle] = None
            for veh in vehicles:
                before_edge = veh.current_edge_id
                veh.step(
                    dt,
                    leader,
                    can_enter_next=lambda cur, nxt, occ=occupancy, blocked=blocked_edges: self._can_enter_next_edge(
                        cur, nxt, occ, blocked, signals, closed_edges
                    ),
                )
                after_edge = veh.current_edge_id

                if veh.arrived:
                    occupancy[before_edge] = max(0, occupancy.get(before_edge, 1) - 1)
                elif after_edge != before_edge:
                    occupancy[before_edge] = max(0, occupancy.get(before_edge, 1) - 1)
                    occupancy[after_edge] = occupancy.get(after_edge, 0) + 1

                if veh.stuck:
                    blocked_edges.add(veh.current_edge_id)

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
