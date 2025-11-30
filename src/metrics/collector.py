"""Collects metrics about commute times, throughput, and queue lengths."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import mean
from typing import Deque, Dict, List


@dataclass
class MetricSnapshot:
    """Roll-up of simulation metrics for charting and monitoring."""

    tick: int
    average_speed: float
    average_commute_time: float
    completed_commutes: int
    stuck_vehicles: int
    throughput_per_minute: float
    average_queue_length: float
    max_queue_length: int
    queue_lengths: Dict[str, int]
    tick_duration_ms: float


@dataclass
class MetricsCollector:
    """Tracks vehicle lifecycle and queue metrics across ticks."""

    window: int = 120
    spawn_times: Dict[str, int] = field(default_factory=dict)
    commute_times: Deque[int] = field(default_factory=lambda: deque(maxlen=5000))
    throughput: Deque[int] = field(default_factory=lambda: deque(maxlen=240))
    queue_history: Deque[Dict[str, int]] = field(default_factory=lambda: deque(maxlen=240))
    tick_durations: Deque[float] = field(default_factory=lambda: deque(maxlen=240))

    _arrivals_this_tick: int = 0

    def on_spawn(self, vehicle_id: str, tick: int) -> None:
        self.spawn_times[vehicle_id] = tick

    def on_arrival(self, vehicle_id: str, tick: int) -> int:
        start_tick = self.spawn_times.pop(vehicle_id, tick)
        commute = max(tick - start_tick, 0)
        self.commute_times.append(commute)
        self._arrivals_this_tick += 1
        return commute

    def record_queues(self, queue_lengths: Dict[str, int]) -> None:
        self.queue_history.append(dict(queue_lengths))

    def record_tick_duration(self, seconds: float) -> None:
        self.tick_durations.append(seconds)

    def finalize_tick(self) -> None:
        self.throughput.append(self._arrivals_this_tick)
        self._arrivals_this_tick = 0

    def _average_commute(self) -> float:
        return mean(self.commute_times) if self.commute_times else 0.0

    def _average_queue_length(self) -> float:
        if not self.queue_history:
            return 0.0
        totals: List[int] = []
        for snapshot in self.queue_history:
            totals.extend(snapshot.values())
        return mean(totals) if totals else 0.0

    def _max_queue_length(self) -> int:
        max_lengths = [max(snapshot.values()) for snapshot in self.queue_history if snapshot]
        return max(max_lengths) if max_lengths else 0

    def _throughput_per_minute(self, tick_duration: float) -> float:
        if not self.throughput:
            return 0.0
        ticks_per_minute = max(int(60 / max(tick_duration, 1e-6)), 1)
        recent = list(self.throughput)[-ticks_per_minute:]
        return sum(recent)

    def _queue_lengths(self) -> Dict[str, int]:
        if not self.queue_history:
            return {}
        latest = self.queue_history[-1]
        # Keep only the busiest edges for easier charting
        busiest = sorted(latest.items(), key=lambda kv: kv[1], reverse=True)
        return dict(busiest[:10])

    def snapshot(
        self,
        *,
        tick: int,
        average_speed: float,
        completed_commutes: int,
        stuck_vehicles: int,
        tick_duration: float,
    ) -> MetricSnapshot:
        throughput_per_minute = self._throughput_per_minute(tick_duration)
        avg_queue_length = self._average_queue_length()
        max_queue = self._max_queue_length()
        queue_lengths = self._queue_lengths()
        tick_ms = (mean(self.tick_durations) if self.tick_durations else 0.0) * 1000

        return MetricSnapshot(
            tick=tick,
            average_speed=average_speed,
            average_commute_time=self._average_commute(),
            completed_commutes=completed_commutes,
            stuck_vehicles=stuck_vehicles,
            throughput_per_minute=throughput_per_minute,
            average_queue_length=avg_queue_length,
            max_queue_length=max_queue,
            queue_lengths=queue_lengths,
            tick_duration_ms=tick_ms,
        )
