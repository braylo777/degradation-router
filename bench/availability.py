"""Availability under injected failures. Mocked providers, real asyncio timing.

Replays a synthetic workload (templated support questions with paraphrases, seeded)
through three router configs under three fault scenarios and writes
results/availability.json. Providers are mocks: the latencies and failures are
injected, the routing decisions and timings are measured.
"""
from __future__ import annotations

import asyncio
import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from router.providers import default_chain  # noqa: E402
from router.router import DegradationRouter  # noqa: E402

TOPICS = ["reset my password", "cancel my subscription", "update my billing address", "track my order",
          "change my email", "get a refund", "enable two factor auth", "download my invoice",
          "delete my account", "contact support", "upgrade my plan", "add a team member"]
TEMPLATES = ["how do i {t}", "How can I {t}?", "how do I {t} please", "what is the way to {t}",
             "help me {t}", "i need to {t}"]
N, BATCH, SEED = 1200, 20, 42
TIMEOUTS = {"frontier": 200, "mid": 100, "local": 50}


def workload(seed=SEED):
    rng = random.Random(seed)
    out = []
    for i in range(N):
        if rng.random() < 0.15:  # unique long-tail question, never cacheable
            out.append(f"question {i} about order number {rng.randint(10000, 99999)} and warehouse {rng.randint(1, 50)}")
        else:
            t = TOPICS[min(int(rng.paretovariate(1.2)) - 1, len(TOPICS) - 1)]
            out.append(rng.choice(TEMPLATES).format(t=t))
    return out


SCENARIOS = {
    "A_frontier_30pct_503": "frontier returns 503 on 30% of calls for the whole run",
    "B_frontier_outage_mid_flaky": "frontier hard-down for requests 300-899; mid 20% 503s throughout",
    "C_total_outage_tail": "all three providers hard-down for the last 300 requests (900-1199)",
}


def apply_faults(scenario, chain, i):
    f, m, l = chain
    if scenario == "A_frontier_30pct_503":
        f.error_rate = 0.30
    elif scenario == "B_frontier_outage_mid_flaky":
        m.error_rate = 0.20
        f.down = 300 <= i < 900
    elif scenario == "C_total_outage_tail":
        for p in chain:
            p.down = i >= 900


CONFIGS = {
    "frontier_only": dict(chain_len=1, use_breakers=False, use_cache=False),
    "chain_no_breaker_no_cache": dict(chain_len=3, use_breakers=False, use_cache=False),
    "chain_breaker_cache": dict(chain_len=3, use_breakers=True, use_cache=True),
}


async def run(scenario, cfg_name):
    cfg = CONFIGS[cfg_name]
    chain = default_chain(seed=SEED)
    rt = DegradationRouter(chain[: cfg["chain_len"]], timeouts_ms=TIMEOUTS, use_breakers=cfg["use_breakers"],
                           use_cache=cfg["use_cache"], breaker_threshold=3, breaker_cooldown_s=0.5)
    prompts = workload()
    results = []
    t0 = time.perf_counter()
    for start in range(0, N, BATCH):
        apply_faults(scenario, chain, start)
        results += await asyncio.gather(*(rt.route(p) for p in prompts[start:start + BATCH]))
    wall = time.perf_counter() - t0
    ok = [r for r in results if r.ok]
    tiers = {}
    for r in results:
        tiers[r.tier] = tiers.get(r.tier, 0) + 1
    lat = sorted(r.latency_ms for r in ok)
    calls_to_down = sum(1 for r in results for a in r.attempts if a["outcome"] in ("http_503", "timeout"))
    return {
        "availability": round(len(ok) / N, 4),
        "served": len(ok), "failed": N - len(ok),
        "tier_counts": dict(sorted(tiers.items())),
        "latency_ms_p50": round(statistics.median(lat), 1) if lat else None,
        "latency_ms_p95": round(lat[int(0.95 * (len(lat) - 1))], 1) if lat else None,
        "failed_upstream_attempts": calls_to_down,
        "breaker_short_circuits": sum(b.short_circuits for b in rt.breakers.values()),
        "breaker_trips": sum(b.trips for b in rt.breakers.values()),
        "cost_usd": round(sum(r.cost_usd for r in results), 4),
        "wall_s": round(wall, 2),
    }


def main():
    out = {"kind": "MEASURED on MOCKED providers with INJECTED faults", "date": time.strftime("%Y-%m-%d"),
           "requests": N, "batch_concurrency": BATCH, "seed": SEED, "timeouts_ms": TIMEOUTS,
           "scenarios": SCENARIOS, "results": {}}
    for s in SCENARIOS:
        out["results"][s] = {}
        for c in CONFIGS:
            out["results"][s][c] = asyncio.run(run(s, c))
            print(s, c, json.dumps(out["results"][s][c]), flush=True)
    (ROOT / "results" / "availability.json").write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
