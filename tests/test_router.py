import asyncio

from router.providers import MockProvider, ProviderError, default_chain
from router.router import DegradationRouter


def run(c): return asyncio.run(c)


def chain(**down):
    ps = [MockProvider("f", "frontier", 1, 0), MockProvider("m", "mid", 1, 0), MockProvider("l", "local", 1, 0)]
    for p in ps:
        p.down = down.get(p.tier, False)
    return ps


def test_happy_path_uses_frontier_not_degraded():
    r = run(DegradationRouter(chain()).route("hi"))
    assert r.ok and r.tier == "frontier" and not r.degraded and len(r.attempts) == 1


def test_falls_back_in_order():
    r = run(DegradationRouter(chain(frontier=True)).route("hi"))
    assert r.tier == "mid" and r.degraded
    r = run(DegradationRouter(chain(frontier=True, mid=True)).route("hi"))
    assert r.tier == "local" and [a["outcome"] for a in r.attempts] == ["http_503", "http_503", "ok"]


def test_timeout_triggers_fallback():
    ps = chain(); ps[0].latency_ms = 300
    r = run(DegradationRouter(ps, timeouts_ms={"frontier": 50}).route("hi"))
    assert r.tier == "mid" and r.attempts[0]["outcome"] == "timeout"


def test_all_down_serves_exact_then_semantic_cache():
    async def go():
        ps = chain(); rt = DegradationRouter(ps)
        await rt.route("how do i reset my password")
        for p in ps: p.down = True
        return await rt.route("How do I reset my password?"), await rt.route("how can i reset my password"), await rt.route("totally new question about invoices")
    exact, sem, miss = run(go())
    assert exact.ok and exact.tier == "cache_exact"
    assert sem.ok and sem.tier == "cache_semantic" and sem.similarity >= 0.85
    assert not miss.ok and miss.tier == "none"


def test_breaker_skips_failing_provider_after_threshold():
    async def go():
        ps = chain(frontier=True)
        rt = DegradationRouter(ps, breaker_threshold=2, breaker_cooldown_s=60)
        for _ in range(5):
            await rt.route("x")
        return ps[0].calls, rt.breaker_states()
    calls, states = run(go())
    assert calls == 2 and states["f"] == "open"


def test_no_cache_mode_fails_when_all_down():
    r = run(DegradationRouter(chain(frontier=True, mid=True, local=True), use_cache=False).route("x"))
    assert not r.ok


def test_injected_error_rate_is_seeded_and_reproducible():
    async def go(seed):
        p = MockProvider("f", "frontier", 0, 0, error_rate=0.3, seed=seed)
        out = []
        for _ in range(50):
            try:
                await p.complete("x"); out.append(1)
            except ProviderError:
                out.append(0)
        return out
    a, b = run(go(7)), run(go(7))
    assert a == b and 0 < a.count(0) < 50


def test_default_chain_tiers():
    assert [p.tier for p in default_chain()] == ["frontier", "mid", "local"]
