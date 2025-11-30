"""Utilities for generating simple grid-based road networks.

Assumptions
-----------
- Roads form an orthogonal grid with evenly spaced intersections.
- Each bidirectional road segment is represented as two directed edges so
  agents can traverse in both directions without additional logic.
- Capacity is represented as vehicles per lane per tick and scaled by the
  number of lanes on each edge.

Default parameters are intentionally modest to keep simulations fast while
still being representative of a small downtown block.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
import random


@dataclass
class GridConfig:
    """Configuration for a grid-shaped road network.

    Parameters
    ----------
    rows: int
        Number of north-south streets (vertical roads).
    cols: int
        Number of east-west streets (horizontal roads).
    block_length: float
        Distance between adjacent intersections in meters.
    lanes_per_road: int
        Number of lanes available in each direction for every road segment.
    speed_limit: float
        Maximum allowed speed (m/s) used to guide agent movement models.
    capacity_per_lane: int
        Vehicle capacity per lane per tick.
    seed: int | None
        Random seed to ensure reproducible ordering when generating IDs.
    """

    rows: int = 3
    cols: int = 3
    block_length: float = 100.0
    lanes_per_road: int = 1
    speed_limit: float = 13.9  # ~50 km/h
    capacity_per_lane: int = 30
    seed: int | None = None

    def capacity_for_edge(self) -> int:
        """Return total capacity for each edge given the lane count."""

        return self.capacity_per_lane * self.lanes_per_road


Node = Dict[str, float]
Edge = Dict[str, float]
Network = Dict[str, List[Dict[str, float]]]


def generate_grid_network(config: GridConfig) -> Network:
    """Generate a directed grid network with metadata.

    Nodes are keyed by integer coordinates (row, col) and store x/y positions
    derived from the grid spacing. Each undirected road is represented as a
    pair of directed edges to simplify routing and scheduling.

    Parameters
    ----------
    config:
        ``GridConfig`` describing the size of the grid and road attributes.

    Returns
    -------
    dict
        A dictionary with ``nodes`` and ``edges`` lists. Nodes include
        ``id``, ``row``, ``col``, ``x``, and ``y`` fields. Edges include
        ``id``, ``from``, ``to``, ``length``, ``lanes``, ``speed_limit``, and
        ``capacity`` fields.
    """

    rng = random.Random(config.seed)
    nodes: List[Node] = []
    edges: List[Edge] = []

    for row in range(config.rows):
        for col in range(config.cols):
            node_id = f"n_{row}_{col}"
            nodes.append(
                {
                    "id": node_id,
                    "row": row,
                    "col": col,
                    "x": col * config.block_length,
                    "y": row * config.block_length,
                }
            )

    def _add_edge(src: Tuple[int, int], dst: Tuple[int, int]) -> None:
        src_id = f"n_{src[0]}_{src[1]}"
        dst_id = f"n_{dst[0]}_{dst[1]}"
        edge_id = f"e_{src_id}_to_{dst_id}"
        edges.append(
            {
                "id": edge_id,
                "from": src_id,
                "to": dst_id,
                "length": config.block_length,
                "lanes": config.lanes_per_road,
                "speed_limit": config.speed_limit,
                "capacity": config.capacity_for_edge(),
            }
        )

    for row in range(config.rows):
        for col in range(config.cols):
            if col + 1 < config.cols:
                _add_edge((row, col), (row, col + 1))
                _add_edge((row, col + 1), (row, col))
            if row + 1 < config.rows:
                _add_edge((row, col), (row + 1, col))
                _add_edge((row + 1, col), (row, col))

    rng.shuffle(edges)

    return {"nodes": nodes, "edges": edges}
