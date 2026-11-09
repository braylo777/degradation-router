"""FastAPI app: /api/route (raw result), /api/ui (component spec), /api/faults (inject)."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .genui import build_spec, validate_spec
from .providers import default_chain
from .router import DegradationRouter

WEB = Path(__file__).resolve().parents[1] / "web"


class Faults(BaseModel):
    provider: str
    down: bool | None = None
    error_rate: float | None = None
    latency_ms: float | None = None


def create_app(router: DegradationRouter | None = None) -> FastAPI:
    rt = router or DegradationRouter(default_chain(), timeouts_ms={"frontier": 300, "mid": 150, "local": 80})
    app = FastAPI(title="degradation-router")
    app.state.router = rt

    @app.get("/api/route")
    async def route(q: str = Query(..., min_length=1, max_length=4000)):
        return (await rt.route(q)).as_dict()

    @app.get("/api/ui")
    async def ui(q: str = Query(..., min_length=1, max_length=4000)):
        r = await rt.route(q)
        spec = build_spec(r, q)
        return {"spec": spec, "errors": validate_spec(spec), "breakers": rt.breaker_states(), "tier": r.tier}

    @app.post("/api/faults")
    async def faults(f: Faults):
        for p in rt.chain:
            if p.name == f.provider or p.tier == f.provider:
                for k in ("down", "error_rate", "latency_ms"):
                    v = getattr(f, k)
                    if v is not None:
                        setattr(p, k, v)
                return {"provider": p.name, "down": p.down, "error_rate": p.error_rate, "latency_ms": p.latency_ms}
        return {"error": "unknown provider"}

    @app.get("/api/state")
    async def state():
        return {
            "breakers": rt.breaker_states(),
            "providers": [{"name": p.name, "tier": p.tier, "down": p.down, "error_rate": p.error_rate,
                           "calls": p.calls, "failures": p.failures} for p in rt.chain],
            "cache": {"exact": len(rt.exact), "semantic": len(rt.semantic)},
        }

    @app.get("/")
    async def index():
        return FileResponse(WEB / "index.html")

    return app


app = create_app()
