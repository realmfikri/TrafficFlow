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

## Metrics & API endpoints
- ``src/metrics/collector.py`` tracks commute durations, stuck vehicles,
  throughput-per-minute, and queue lengths for the busiest edges.
- ``/api/state`` returns the latest metrics alongside the map and vehicle
  state, while ``/api/metrics`` returns a metrics-only payload with recent
  history for charting.
- ``tick_duration_ms`` exposes the average runtime of the simulation loop so
  you can watch for regressions when scaling up to ~2,000 agents.

## Presets
- ``/api/presets`` lists available presets; ``/api/presets/apply`` applies the
  preset and updates spawn rates and signal timing in one call.
- The frontend includes a selector for "Sunday Morning" (light traffic) and
  "Rush Hour" (aggressive spawning with longer green phases for the north/south
  corridor).

## Performance tuning
- Use the preset selector or the spawn/signal inputs to throttle load when you
  approach 2,000 active vehicles. The metrics panel will surface queue lengths
  and the runtime of each tick.
- Vehicles are bucketed by edge and position before each tick, improving cache
  locality and reducing per-edge sorting overhead for large fleets.
- Keep ``tick_duration`` modest (1–5 ms) when running headless performance
  sweeps; you can still render the frontend while the backend advances more
  quickly than real time.
- Quick benchmark (0.5s headless run, 2 ms tick target): the loop averaged
  ~1.99 ms per tick with a peak queue of 12 vehicles and ~3.9 average queue
  depth, leaving headroom for 2k vehicles on this container's CPUs.【949f0a†L1-L5】

## Example
```python
from src.simulation.core import SimulationEngine, load_config

config = load_config("config.yml")
engine = SimulationEngine(config)
engine.register_agent("logger", lambda state, tick: print(tick))
engine.run(10)
```
