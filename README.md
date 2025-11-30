# TrafficFlow

A lightweight sandbox for experimenting with discrete-time traffic simulations.

## Simulation core
- ``src/simulation/core.py`` provides a tick-based scheduler that maintains a
  shared state object, advances time deterministically, and allows agents to be
  registered with configurable update intervals.
- Default tick duration is one second with a 3x3 grid and modest per-lane
  capacity (30 vehicles/tick). Seeds are honored by both the scheduler and map
  generator to keep runs reproducible.

## Map generation
- ``src/map/generator.py`` builds a directed grid network with nodes positioned
  on evenly spaced intersections and edges carrying lane, speed limit, and
  capacity metadata.
- The generator assumes orthogonal roads with equal block lengths and creates
  paired edges for bidirectional travel.

## Configuration
- Use JSON or YAML files to override defaults. Expected keys include
  ``tick_duration``, ``max_ticks``, ``seed``, and a ``grid`` block with
  ``rows``, ``cols``, ``block_length``, ``lanes_per_road``, ``speed_limit``,
  ``capacity_per_lane``, and an optional ``seed`` for the map layout.
- Load configurations via ``simulation.core.load_config(<path>)``; the helper
  returns a ``SimulationConfig`` instance ready for the engine.

## Example
```python
from src.simulation.core import SimulationEngine, load_config

config = load_config("config.yml")
engine = SimulationEngine(config)
engine.register_agent("logger", lambda state, tick: print(tick))
engine.run(10)
```
