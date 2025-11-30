from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Dict, List, Set, TypedDict
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.agents.vehicle import Vehicle, VehicleSpawner
from src.map.generator import generate_grid_network
from src.metrics import MetricSnapshot, MetricsCollector
from src.signals.lights import TrafficSignalController
from src.simulation.core import SimulationConfig, SimulationEngine


class PresetConfig(TypedDict, total=False):
    spawn_interval: int
    signal_timings: Dict[str, float]


PRESETS: Dict[str, PresetConfig] = {
    "Sunday Morning": {"spawn_interval": 4, "signal_timings": {"NS": 28.0, "EW": 28.0}},
    "Rush Hour": {"spawn_interval": 1, "signal_timings": {"NS": 40.0, "EW": 32.0}},
}


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
    metrics_history: List[MetricSnapshot] = field(default_factory=list, init=False)
    metrics_collector: MetricsCollector = field(default_factory=MetricsCollector, init=False)
    active_preset: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._engine = SimulationEngine(
            self.config, network=generate_grid_network(self.config.grid)
        )
        self._engine.state["closed_edges"] = self.closed_edges

        self._signals = TrafficSignalController(self._engine.state["network"])
        self._signals.register(self._engine)

        self._spawner = VehicleSpawner()
        self._spawner.register(self._engine)

        self._thread = Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            start = time.perf_counter()
            with self._lock:
                self._engine.advance_tick()
                self._update_metrics()
            elapsed = time.perf_counter() - start
            self.metrics_collector.record_tick_duration(elapsed)
            tick_seconds = max(self.config.tick_duration - elapsed, 0.0)
            time.sleep(max(tick_seconds, 0.001))

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    @property
    def vehicles(self) -> Dict[str, Vehicle]:
        return self._spawner.vehicles

    def toggle_edge_closure(self, edge_id: str) -> Dict[str, str | bool]:
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
            self.active_preset = None
        return durations

    def update_spawn_interval(self, interval: int) -> Dict[str, int]:
        interval = max(1, interval)
        with self._lock:
            self._spawner.spawn_interval = interval
            self.active_preset = None
        return {"spawn_interval": interval}

    def apply_preset(self, name: str) -> Dict:
        preset = PRESETS.get(name)
        if not preset:
            raise ValueError(f"Unknown preset: {name}")

        with self._lock:
            spawn_interval_raw = preset.get("spawn_interval")
            if isinstance(spawn_interval_raw, (int, float)):
                self._spawner.spawn_interval = max(int(spawn_interval_raw), 1)

            timings = preset.get("signal_timings")
            if isinstance(timings, dict):
                durations = {
                    "NS": max(float(timings.get("NS", 1.0)), 1.0),
                    "EW": max(float(timings.get("EW", 1.0)), 1.0),
                }
                self._signals.update_phase_durations(durations)
            self.active_preset = name

        return {
            "applied": name,
            "spawn_interval": self._spawner.spawn_interval,
            "signal_timings": self._signals.phase_durations,
        }

    def _update_metrics(self) -> None:
        current_ids = set(self.vehicles.keys())
        new_ids = current_ids - set(self.metrics_collector.spawn_times.keys())
        for vid in new_ids:
            self.metrics_collector.on_spawn(vid, self._engine.tick)

        arrived_ids = set(self.metrics_collector.spawn_times.keys()) - current_ids
        for vid in arrived_ids:
            self.metrics_collector.on_arrival(vid, self._engine.tick)

        speeds = [veh.velocity for veh in self.vehicles.values()]
        average_speed = sum(speeds) / len(speeds) if speeds else 0.0
        stuck_count = sum(1 for veh in self.vehicles.values() if veh.stuck)

        self.metrics_collector.record_queues(self._spawner.last_queue_lengths)
        self.metrics_collector.finalize_tick()

        snapshot = self.metrics_collector.snapshot(
            tick=self._engine.tick,
            average_speed=average_speed,
            completed_commutes=len(self.metrics_collector.commute_times),
            stuck_vehicles=stuck_count,
            tick_duration=self.config.tick_duration,
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

            metrics = (
                self.metrics_history[-1]
                if self.metrics_history
                else MetricSnapshot(
                    0,
                    0.0,
                    0.0,
                    0,
                    0,
                    0.0,
                    0.0,
                    0,
                    {},
                    0.0,
                )
            )

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
                    "throughput_per_minute": metrics.throughput_per_minute,
                    "average_queue_length": metrics.average_queue_length,
                    "max_queue_length": metrics.max_queue_length,
                    "queue_lengths": metrics.queue_lengths,
                    "tick_duration_ms": metrics.tick_duration_ms,
                },
                "history": [snapshot.__dict__ for snapshot in self.metrics_history[-60:]],
                "settings": {
                    "spawn_interval": self._spawner.spawn_interval,
                    "signal_timings": self._signals.phase_durations,
                    "active_preset": self.active_preset,
                },
            }


class TimingUpdate(BaseModel):
    ns: float
    ew: float


class SpawnUpdate(BaseModel):
    spawn_interval: int


class ClosureUpdate(BaseModel):
    edge_id: str


class PresetUpdate(BaseModel):
    name: str


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
        snap = runtime.snapshot()
        return {"latest": snap.get("metrics", {}), "history": snap.get("history", [])}

    @app.get("/api/presets")
    async def list_presets() -> Dict:
        return {"presets": list(PRESETS.keys()), "active": runtime.active_preset}

    @app.post("/api/presets/apply")
    async def set_preset(update: PresetUpdate) -> Dict:
        try:
            return runtime.apply_preset(update.name)
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/settings/signals")
    async def set_signals(update: TimingUpdate) -> Dict[str, float]:
        return runtime.update_signal_timings(update.ns, update.ew)

    @app.post("/api/settings/spawn")
    async def set_spawn(update: SpawnUpdate) -> Dict[str, int]:
        return runtime.update_spawn_interval(update.spawn_interval)

    @app.post("/api/closures/toggle")
    async def toggle_closure(update: ClosureUpdate) -> Dict[str, str | bool]:
        return runtime.toggle_edge_closure(update.edge_id)

    return app


app = create_app()
