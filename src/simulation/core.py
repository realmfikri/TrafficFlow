"""Core simulation engine for TrafficFlow.

Assumptions
-----------
- Time advances in discrete ticks of equal duration; all scheduled agents for a
  tick run before the clock advances.
- Agents are responsible for updating the shared ``state`` dictionary and must
  be idempotent per tick to avoid double-counting.
- The scheduler is deterministic when seeded, using the registration order to
  process callbacks scheduled for the same tick.

Default parameters are chosen for quick experiments: one-second ticks, a modest
maximum tick count, and a small grid topology. These values are intended as
starting points and can be overridden via configuration files or constructor
arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping, Optional
import json
import random

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - dependency may be optional
    yaml = None

from src.map.generator import GridConfig, generate_grid_network

AgentCallback = Callable[[Dict, int], None]


@dataclass
class SimulationConfig:
    """Aggregate configuration for the simulation engine and map generation."""

    tick_duration: float = 1.0
    max_ticks: int = 3600
    seed: Optional[int] = None
    grid: GridConfig = field(default_factory=GridConfig)

    @classmethod
    def from_mapping(cls, mapping: Mapping) -> "SimulationConfig":
        """Build a configuration object from a dictionary-like source."""

        grid_cfg = mapping.get("grid", {}) if isinstance(mapping.get("grid", {}), Mapping) else {}
        grid = GridConfig(
            rows=grid_cfg.get("rows", GridConfig.rows),
            cols=grid_cfg.get("cols", GridConfig.cols),
            block_length=grid_cfg.get("block_length", GridConfig.block_length),
            lanes_per_road=grid_cfg.get("lanes_per_road", GridConfig.lanes_per_road),
            speed_limit=grid_cfg.get("speed_limit", GridConfig.speed_limit),
            capacity_per_lane=grid_cfg.get("capacity_per_lane", GridConfig.capacity_per_lane),
            seed=grid_cfg.get("seed", grid_cfg.get("map_seed")),
        )

        return cls(
            tick_duration=mapping.get("tick_duration", cls.tick_duration),
            max_ticks=mapping.get("max_ticks", cls.max_ticks),
            seed=mapping.get("seed"),
            grid=grid,
        )


def load_config(path: str | Path) -> SimulationConfig:
    """Load simulation configuration from a JSON or YAML file."""

    path = Path(path)
    content = path.read_text()
    if path.suffix.lower() in {".yml", ".yaml"}:
        if yaml is None:
            raise ImportError("PyYAML is required to parse YAML configuration files.")
        mapping = yaml.safe_load(content)
    else:
        mapping = json.loads(content)

    if not isinstance(mapping, Mapping):
        raise ValueError("Configuration file must contain a mapping at the top level.")

    return SimulationConfig.from_mapping(mapping)


class SimulationEngine:
    """Tick-based scheduler coordinating agent updates and global state."""

    def __init__(self, config: SimulationConfig, *, network: Optional[Dict] = None):
        self.config = config
        self.random = random.Random(config.seed)
        self.tick = 0
        self.state: Dict = {
            "network": network or generate_grid_network(config.grid),
            "agents": {},
        }
        self._schedule: Dict[int, list[str]] = {}

    def register_agent(
        self,
        name: str,
        callback: AgentCallback,
        *,
        start_tick: int = 0,
        interval: int = 1,
    ) -> None:
        """Register an agent callback and schedule its first update."""

        self.state["agents"][name] = {
            "callback": callback,
            "interval": max(1, interval),
        }
        self._schedule.setdefault(start_tick, []).append(name)

    def _run_callbacks(self, agent_names: Iterable[str]) -> None:
        for name in agent_names:
            agent = self.state["agents"][name]
            agent["callback"](self.state, self.tick)
            next_tick = self.tick + agent["interval"]
            self._schedule.setdefault(next_tick, []).append(name)

    def advance_tick(self) -> None:
        """Run all scheduled callbacks for the current tick and advance time."""

        due_agents = list(self._schedule.pop(self.tick, []))
        self._run_callbacks(due_agents)
        self.tick += 1

    def run(self, max_ticks: Optional[int] = None) -> None:
        """Advance the simulation until the configured limit is reached."""

        limit = max_ticks if max_ticks is not None else self.config.max_ticks
        while self.tick < limit:
            self.advance_tick()
