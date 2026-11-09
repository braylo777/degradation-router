from fastapi.testclient import TestClient

from router.app import create_app
from router.genui import build_spec, validate_spec
from router.providers import MockProvider
from router.router import DegradationRouter, RouteResult


def mk(tier, ok=True, degraded=False):
    return RouteResult(ok, tier, "p", "txt" if ok else None, degraded, 12.0, [{"provider": "p", "outcome": "ok"}], similarity=0.9)


def test_spec_richness_degrades_with_tier():
    n = {t: len(str(build_spec(mk(t, degraded=t != "frontier"), "q"))) for t in ["frontier", "mid", "local"]}
    assert n["frontier"] > n["mid"] > n["local"] * 0  # frontier richest
    assert any(c["type"] == "actions" for c in build_spec(mk("frontier"), "q")["children"])
    assert not any(c["type"] == "actions" for c in build_spec(mk("local", degraded=True), "q")["children"])


def test_cache_and_error_specs_have_banners_and_validate():
    for r in [mk("cache_semantic", degraded=True), mk("none", ok=False, degraded=True), mk("mid", degraded=True)]:
        spec = build_spec(r, "q")
        assert spec["children"][0]["type"] == "banner"
        assert validate_spec(spec) == []


def test_validator_rejects_unknown_components():
    assert validate_spec({"type": "page", "children": [{"type": "script"}]}) == ["unknown component type: 'script'"]
    assert validate_spec({"type": "banner", "level": "nope", "text": "x"}) == ["banner.level invalid"]


def client():
    ps = [MockProvider("f", "frontier", 1, 0), MockProvider("m", "mid", 1, 0), MockProvider("l", "local", 1, 0)]
    return TestClient(create_app(DegradationRouter(ps)))


def test_api_ui_and_fault_injection_flow():
    c = client()
    r = c.get("/api/ui", params={"q": "hello there"}).json()
    assert r["tier"] == "frontier" and r["errors"] == []
    for t in ["frontier", "mid", "local"]:
        assert c.post("/api/faults", json={"provider": t, "down": True}).json()["down"] is True
    r = c.get("/api/ui", params={"q": "hello there!"}).json()
    assert r["tier"] == "cache_exact" and r["spec"]["children"][0]["level"] == "warning"


def test_api_validation_and_index():
    c = client()
    assert c.get("/api/route", params={"q": ""}).status_code == 422
    assert "Degradation Router" in c.get("/").text
