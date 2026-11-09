"""Mock LLM providers with injectable 503s, latency and outage windows. No network."""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field


class ProviderError(Exception):
    def __init__(self, provider: str, status: int, msg: str = ""):
        super().__init__(f"{provider}: HTTP {status} {msg}".strip())
        self.provider, self.status = provider, status


@dataclass
class MockProvider:
    name: str
    tier: str
    latency_ms: float = 20.0
    jitter_ms: float = 5.0
    error_rate: float = 0.0          # probability of an injected 503 per call
    slow_rate: float = 0.0           # probability of a latency spike
    slow_ms: float = 500.0
    cost_per_call_usd: float = 0.0
    quality: str = "full"
    seed: int = 0
    down: bool = False               # hard outage switch (every call 503s)
    calls: int = 0
    failures: int = 0
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    async def complete(self, prompt: str) -> str:
        self.calls += 1
        r = self._rng.random()
        lat = max(0.0, self.latency_ms + self._rng.uniform(-self.jitter_ms, self.jitter_ms))
        if self._rng.random() < self.slow_rate:
            lat += self.slow_ms
        await asyncio.sleep(lat / 1000)
        if self.down or r < self.error_rate:
            self.failures += 1
            raise ProviderError(self.name, 503, "injected")
        return f"[{self.tier}:{self.name}] answer to: {prompt.strip()[:120]}"


def default_chain(seed: int = 0) -> list[MockProvider]:
    return [
        MockProvider("frontier-xl", "frontier", latency_ms=60, jitter_ms=20, cost_per_call_usd=0.012, quality="full", seed=seed + 1),
        MockProvider("mid-m", "mid", latency_ms=25, jitter_ms=8, cost_per_call_usd=0.002, quality="reduced", seed=seed + 2),
        MockProvider("local-s", "local", latency_ms=8, jitter_ms=3, cost_per_call_usd=0.0, quality="minimal", seed=seed + 3),
    ]
