"""Circuit breaker: CLOSED -> OPEN after N consecutive failures; OPEN -> HALF_OPEN after
cooldown; HALF_OPEN allows one probe; success closes, failure re-opens."""
from __future__ import annotations

import time
from enum import Enum
from typing import Callable


class State(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self.clock = clock
        self.state = State.CLOSED
        self.failures = 0
        self.opened_at = 0.0
        self.probe_in_flight = False
        self.trips = 0
        self.short_circuits = 0

    def allow(self) -> bool:
        if self.state is State.CLOSED:
            return True
        if self.state is State.OPEN:
            if self.clock() - self.opened_at >= self.cooldown_s:
                self.state = State.HALF_OPEN
                self.probe_in_flight = False
            else:
                self.short_circuits += 1
                return False
        # HALF_OPEN: exactly one probe at a time
        if self.probe_in_flight:
            self.short_circuits += 1
            return False
        self.probe_in_flight = True
        return True

    def record_success(self) -> None:
        self.state = State.CLOSED
        self.failures = 0
        self.probe_in_flight = False

    def record_failure(self) -> None:
        self.probe_in_flight = False
        if self.state is State.HALF_OPEN:
            self._open()
            return
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self._open()

    def _open(self) -> None:
        self.state = State.OPEN
        self.opened_at = self.clock()
        self.failures = 0
        self.trips += 1
