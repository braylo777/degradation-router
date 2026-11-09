"""Degradation router: Frontier -> Mid -> Local -> Cache, with per-provider circuit breakers."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from .breaker import CircuitBreaker
from .cache import ExactCache, SemanticCache
from .providers import MockProvider, ProviderError


@dataclass
class RouteResult:
    ok: bool
    tier: str                 # frontier | mid | local | cache_exact | cache_semantic | none
    provider: str | None
    text: str | None
    degraded: bool
    latency_ms: float
    attempts: list[dict] = field(default_factory=list)
    cost_usd: float = 0.0
    similarity: float | None = None

    def as_dict(self) -> dict:
        return dict(self.__dict__)


class DegradationRouter:
    def __init__(
        self,
        chain: list[MockProvider],
        *,
        timeouts_ms: dict[str, float] | None = None,
        use_breakers: bool = True,
        use_cache: bool = True,
        breaker_threshold: int = 3,
        breaker_cooldown_s: float = 1.0,
        exact: ExactCache | None = None,
        semantic: SemanticCache | None = None,
    ):
        self.chain = chain
        self.timeouts_ms = timeouts_ms or {}
        self.use_breakers = use_breakers
        self.use_cache = use_cache
        self.breakers = {
            p.name: CircuitBreaker(breaker_threshold, breaker_cooldown_s) for p in chain
        }
        self.exact = exact or ExactCache()
        self.semantic = semantic or SemanticCache()

    async def route(self, prompt: str) -> RouteResult:
        t0 = time.perf_counter()
        attempts: list[dict] = []
        for i, p in enumerate(self.chain):
            br = self.breakers[p.name]
            if self.use_breakers and not br.allow():
                attempts.append({"provider": p.name, "outcome": "breaker_open"})
                continue
            try:
                timeout = self.timeouts_ms.get(p.tier)
                coro = p.complete(prompt)
                text = await (asyncio.wait_for(coro, timeout / 1000) if timeout else coro)
            except (ProviderError, asyncio.TimeoutError) as e:
                outcome = "timeout" if isinstance(e, asyncio.TimeoutError) else f"http_{e.status}"
                attempts.append({"provider": p.name, "outcome": outcome})
                if self.use_breakers:
                    br.record_failure()
                continue
            if self.use_breakers:
                br.record_success()
            attempts.append({"provider": p.name, "outcome": "ok"})
            if self.use_cache:
                self.exact.put(prompt, text)
                self.semantic.put(prompt, text)
            return RouteResult(
                True, p.tier, p.name, text, degraded=i > 0,
                latency_ms=(time.perf_counter() - t0) * 1000,
                attempts=attempts, cost_usd=p.cost_per_call_usd,
            )
        if self.use_cache:
            hit = self.exact.get(prompt)
            if hit is not None:
                attempts.append({"provider": "cache_exact", "outcome": "hit"})
                return RouteResult(True, "cache_exact", None, hit, True,
                                   (time.perf_counter() - t0) * 1000, attempts, similarity=1.0)
            sem = self.semantic.get(prompt)
            if sem is not None:
                attempts.append({"provider": "cache_semantic", "outcome": "hit"})
                return RouteResult(True, "cache_semantic", None, sem[0], True,
                                   (time.perf_counter() - t0) * 1000, attempts, similarity=sem[1])
            attempts.append({"provider": "cache", "outcome": "miss"})
        return RouteResult(False, "none", None, None, True,
                           (time.perf_counter() - t0) * 1000, attempts)

    def breaker_states(self) -> dict[str, str]:
        return {k: b.state.value for k, b in self.breakers.items()}
