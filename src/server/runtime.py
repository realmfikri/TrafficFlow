from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Dict, List, Set
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.agents.vehicle import Vehicle, VehicleSpawner
from src.map.generator import generate_grid_network
from src.signals.lights import TrafficSignalController
from src.simulation.core import SimulationConfig, SimulationEngine


@dataclass
class MetricSnapshot:
    tick: int
    average_speed: float
    average_commute_time: float
    completed_commutes: int
    stuck_vehicles: int


@dataclass
class SimulationRuntime:
    config: SimulationConfig = field(default_factory=SimulationConfig)
    _engine: SimulationEngine = field(init=False)
    _spawner: VehicleSpawner = field(init=False)
    _signals: TrafficSignalController = field(init=False)
    _lock: Lock = field(default_factory=Lock, init=False)
    _stop_event: Event = field(default_factory=Event, init=False)
    _thread: Thread | None = field(default=None, init=False)
    closed_edges: Set[str] = field(default_factory=set)
    _spawn_times: Dict[str, int] = field(default_factory=dict, init=False)
    _completed_commutes: int = field(default=0, init=False)
    _total_commute_time: float = field(default=0.0, init=False)
    metrics_history: List[MetricSnapshot] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._engine = SimulationEngine(self.config, network=generate_grid_network(self.config.grid))
        self._engine.state["closed_edges"] = self.closed_edges

        self._signals = TrafficSignalController(self._engine.state["network"])
        self._signals.register(self._engine)

        self._spawner = VehicleSpawner()
        self._spawner.register(self._engine)

        self._thread = Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        tick_seconds = max(self.config.tick_duration, 0.01)
        while not self._stop_event.is_set():
            time.sleep(tick_seconds)
            with self._lock:
                self._engine.advance_tick()
                self._update_metrics()

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    @property
    def vehicles(self) -> Dict[str, Vehicle]:
        return self._spawner.vehicles

    def toggle_edge_closure(self, edge_id: str) -> Dict[str, bool]:
        with self._lock:
            if edge_id in self.closed_edges:
                self.closed_edges.remove(edge_id)
            else:
                self.closed_edges.add(edge_id)
        return {"edge_id": edge_id, "closed": edge_id in self.closed_edges}

    def update_signal_timings(self, ns: float, ew: float) -> Dict[str, float]:
        durations = {"NS": max(ns, 1.0), "EW": max(ew, 1.0)}
        with self._lock:
            self._signals.update_phase_durations(durations)
        return durations

    def update_spawn_interval(self, interval: int) -> Dict[str, int]:
        interval = max(1, interval)
        with self._lock:
            self._spawner.spawn_interval = interval
        return {"spawn_interval": interval}

    def _update_metrics(self) -> None:
        current_ids = set(self.vehicles.keys())
        new_ids = current_ids - set(self._spawn_times.keys())
        for vid in new_ids:
            self._spawn_times[vid] = self._engine.tick

        arrived_ids = set(self._spawn_times.keys()) - current_ids
        for vid in arrived_ids:
            start_tick = self._spawn_times.pop(vid, self._engine.tick)
            self._completed_commutes += 1
            self._total_commute_time += max(self._engine.tick - start_tick, 0)

        speeds = [veh.velocity for veh in self.vehicles.values()]
        average_speed = sum(speeds) / len(speeds) if speeds else 0.0
        average_commute = (
            self._total_commute_time / self._completed_commutes
            if self._completed_commutes
            else 0.0
        )
        stuck_count = sum(1 for veh in self.vehicles.values() if veh.stuck)

        snapshot = MetricSnapshot(
            tick=self._engine.tick,
            average_speed=average_speed,
            average_commute_time=average_commute,
            completed_commutes=self._completed_commutes,
            stuck_vehicles=stuck_count,
        )
        self.metrics_history.append(snapshot)
        self.metrics_history = self.metrics_history[-200:]

    def _edge_lookup(self) -> Dict[str, Dict]:
        edges = self._engine.state.get("network", {}).get("edges", [])
        return {edge.get("id"): edge for edge in edges}

    def _node_lookup(self) -> Dict[str, Dict]:
        nodes = self._engine.state.get("network", {}).get("nodes", [])
        return {node.get("id"): node for node in nodes}

    def _vehicle_position(self, vehicle: Vehicle) -> Dict[str, float]:
        edge = self._edge_lookup().get(vehicle.current_edge_id, {})
        nodes = self._node_lookup()
        src = nodes.get(edge.get("from", ""), {})
        dst = nodes.get(edge.get("to", ""), {})
        length = float(edge.get("length", 1.0)) or 1.0
        ratio = min(max(vehicle.position / length, 0.0), 1.0)
        x = float(src.get("x", 0.0)) + (float(dst.get("x", 0.0)) - float(src.get("x", 0.0))) * ratio
        y = float(src.get("y", 0.0)) + (float(dst.get("y", 0.0)) - float(src.get("y", 0.0))) * ratio
        return {"x": x, "y": y}

    def snapshot(self) -> Dict:
        with self._lock:
            vehicles = [
                {
                    "id": veh.vehicle_id,
                    "edge_id": veh.current_edge_id,
                    "position": veh.position,
                    "velocity": veh.velocity,
                    "arrived": veh.arrived,
                    "stuck": veh.stuck,
                    "coords": self._vehicle_position(veh),
                }
                for veh in self.vehicles.values()
            ]

            metrics = self.metrics_history[-1] if self.metrics_history else MetricSnapshot(0, 0.0, 0.0, 0, 0)

            return {
                "tick": self._engine.tick,
                "network": self._engine.state.get("network", {}),
                "vehicles": vehicles,
                "closed_edges": list(self.closed_edges),
                "metrics": {
                    "average_speed": metrics.average_speed,
                    "average_commute_time": metrics.average_commute_time,
                    "completed_commutes": metrics.completed_commutes,
                    "stuck_vehicles": metrics.stuck_vehicles,
                },
                "history": [snapshot.__dict__ for snapshot in self.metrics_history[-60:]],
                "settings": {
                    "spawn_interval": self._spawner.spawn_interval,
                    "signal_timings": self._signals.phase_durations,
                },
            }


class TimingUpdate(BaseModel):
    ns: float
    ew: float


class SpawnUpdate(BaseModel):
    spawn_interval: int


class ClosureUpdate(BaseModel):
    edge_id: str


def create_app(runtime: SimulationRuntime | None = None) -> FastAPI:
    runtime = runtime or SimulationRuntime()
    app = FastAPI(title="TrafficFlow")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    project_root = Path(__file__).resolve().parents[2]
    static_dir = project_root / "frontend"
    if static_dir.exists():
        app.mount("/frontend", StaticFiles(directory=static_dir, html=True), name="frontend")

    @app.on_event("shutdown")
    async def _shutdown() -> None:  # pragma: no cover - lifecycle hook
        runtime.shutdown()

    @app.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/frontend")

    @app.get("/api/state")
    async def get_state() -> Dict:
        return runtime.snapshot()

    @app.get("/api/metrics")
    async def get_metrics() -> Dict:
        return runtime.snapshot().get("metrics", {})

    @app.post("/api/settings/signals")
    async def set_signals(update: TimingUpdate) -> Dict[str, float]:
        return runtime.update_signal_timings(update.ns, update.ew)

    @app.post("/api/settings/spawn")
    async def set_spawn(update: SpawnUpdate) -> Dict[str, int]:
        return runtime.update_spawn_interval(update.spawn_interval)

    @app.post("/api/closures/toggle")
    async def toggle_closure(update: ClosureUpdate) -> Dict[str, bool]:
        return runtime.toggle_edge_closure(update.edge_id)

    return app


app = create_app()
