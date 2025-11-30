"""Routing service supporting congestion-aware shortest paths and rerouting."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple
import heapq
import math


@dataclass
class Router:
    """Compute routes on a directed road graph and manage rerouting events."""

    network: Dict
    congestion_threshold: float = 1.0
    reroute_cooldown: int = 5
    use_a_star: bool = True

    _edge_lookup: Dict[str, Dict] = field(init=False, repr=False)
    _outgoing: Dict[str, List[Dict]] = field(init=False, repr=False)
    _node_positions: Dict[str, Tuple[float, float]] = field(init=False, repr=False)
    _edge_loads: Dict[str, int] = field(default_factory=dict, repr=False)
    _blocked_edges: set[str] = field(default_factory=set, repr=False)
    _vehicles: Dict[str, Dict] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._edge_lookup = {edge["id"]: edge for edge in self.network.get("edges", [])}
        self._outgoing = {}
        for edge in self.network.get("edges", []):
            self._outgoing.setdefault(edge["from"], []).append(edge)
        self._node_positions = {
            node["id"]: (float(node.get("x", 0.0)), float(node.get("y", 0.0)))
            for node in self.network.get("nodes", [])
        }

    # ------------------------------------------------------------------
    # Routing primitives
    # ------------------------------------------------------------------
    def _heuristic(self, node: str, goal: str) -> float:
        if not self.use_a_star:
            return 0.0
        x1, y1 = self._node_positions.get(node, (0.0, 0.0))
        x2, y2 = self._node_positions.get(goal, (0.0, 0.0))
        return math.hypot(x2 - x1, y2 - y1)

    def _edge_weight(self, edge: Dict) -> float:
        if edge["id"] in self._blocked_edges:
            return math.inf
        length = float(edge.get("length", 1.0))
        speed = float(edge.get("speed_limit", 1.0)) or 1.0
        base_time = length / speed
        capacity = max(1, int(edge.get("capacity", 1)))
        load = self._edge_loads.get(edge["id"], 0)
        congestion = 1 + (load / capacity)
        return base_time * congestion

    def _neighbors(self, node_id: str) -> Iterable[Tuple[Dict, float]]:
        for edge in self._outgoing.get(node_id, []):
            weight = self._edge_weight(edge)
            if math.isfinite(weight):
                yield edge, weight

    def plan_route(self, start: str, destination: str) -> List[Dict]:
        if start == destination:
            return []
        queue: list[Tuple[float, float, str, List[Dict]]] = []
        heapq.heappush(queue, (0.0, 0.0, start, []))
        best_costs = {start: 0.0}

        while queue:
            est_total, cost_so_far, node, path = heapq.heappop(queue)
            if node == destination:
                return path
            if cost_so_far > best_costs.get(node, math.inf):
                continue
            for edge, weight in self._neighbors(node):
                new_cost = cost_so_far + weight
                next_node = edge["to"]
                if new_cost < best_costs.get(next_node, math.inf):
                    best_costs[next_node] = new_cost
                    priority = new_cost + self._heuristic(next_node, destination)
                    heapq.heappush(queue, (priority, new_cost, next_node, path + [edge]))

        raise ValueError(f"No route found from {start} to {destination}")

    # ------------------------------------------------------------------
    # Load bookkeeping
    # ------------------------------------------------------------------
    def _apply_route_load(self, route: Iterable[Dict], delta: int) -> None:
        for edge in route:
            edge_id = edge["id"]
            self._edge_loads[edge_id] = max(0, self._edge_loads.get(edge_id, 0) + delta)

    def mark_edge_complete(self, vehicle_id: str, edge_id: str) -> None:
        state = self._vehicles.get(vehicle_id)
        if not state:
            return
        remaining = state.get("route", [])
        if remaining and remaining[0]["id"] == edge_id:
            completed = remaining.pop(0)
            self._edge_loads[edge_id] = max(0, self._edge_loads.get(edge_id, 0) - 1)
            state["route"] = remaining
            # Update the vehicle's current node to the edge destination
            state["current_node"] = completed["to"]

    # ------------------------------------------------------------------
    # Vehicle management
    # ------------------------------------------------------------------
    def register_vehicle(self, vehicle_id: str, start: str, destination: str, tick: int = 0) -> List[Dict]:
        route = self.plan_route(start, destination)
        self._vehicles[vehicle_id] = {
            "current_node": start,
            "destination": destination,
            "route": route.copy(),
            "last_reroute": tick,
        }
        self._apply_route_load(route, delta=1)
        return route

    def release_vehicle(self, vehicle_id: str) -> None:
        state = self._vehicles.pop(vehicle_id, None)
        if state:
            self._apply_route_load(state.get("route", []), delta=-1)

    def _remaining_route(self, vehicle_id: str) -> List[Dict]:
        state = self._vehicles.get(vehicle_id)
        if not state:
            return []
        current = state.get("current_node")
        route = state.get("route", [])
        for idx, edge in enumerate(route):
            if edge.get("from") == current:
                return route[idx:]
        return route

    def _needs_reroute(self, vehicle_id: str) -> bool:
        remaining = self._remaining_route(vehicle_id)
        for edge in remaining:
            capacity = max(1, int(edge.get("capacity", 1)))
            load = self._edge_loads.get(edge["id"], 0)
            if edge["id"] in self._blocked_edges:
                return True
            if load >= capacity * self.congestion_threshold:
                return True
        return False

    def _reroute_vehicle(self, vehicle_id: str, tick: int) -> List[Dict]:
        state = self._vehicles[vehicle_id]
        current_node = state.get("current_node")
        destination = state.get("destination")
        old_route = state.get("route", [])
        new_route = self.plan_route(current_node, destination)
        self._apply_route_load(old_route, delta=-1)
        state["route"] = new_route.copy()
        state["last_reroute"] = tick
        self._apply_route_load(new_route, delta=1)
        return new_route

    def update_vehicle_position(self, vehicle_id: str, current_node: str, tick: int) -> List[Dict]:
        state = self._vehicles.get(vehicle_id)
        if not state:
            raise KeyError(f"Vehicle {vehicle_id} is not registered")
        state["current_node"] = current_node

        if tick - state.get("last_reroute", -math.inf) < self.reroute_cooldown:
            return state.get("route", [])

        if self._needs_reroute(vehicle_id):
            return self._reroute_vehicle(vehicle_id, tick)
        return state.get("route", [])

    # ------------------------------------------------------------------
    # Road status management
    # ------------------------------------------------------------------
    def block_edge(self, edge_id: str, tick: int = 0) -> None:
        self._blocked_edges.add(edge_id)
        affected = [vid for vid, state in self._vehicles.items() if any(e["id"] == edge_id for e in state.get("route", []))]
        for vid in affected:
            if tick - self._vehicles[vid].get("last_reroute", -math.inf) >= self.reroute_cooldown:
                self._reroute_vehicle(vid, tick)

    def unblock_edge(self, edge_id: str) -> None:
        self._blocked_edges.discard(edge_id)

    def record_external_load(self, edge_id: str, delta: int) -> None:
        """Adjust an edge's load to reflect vehicles managed elsewhere."""
        self._edge_loads[edge_id] = max(0, self._edge_loads.get(edge_id, 0) + delta)

