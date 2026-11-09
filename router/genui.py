"""Generative UI: turn a RouteResult into a JSON component spec.

The richer the tier that answered, the richer the UI. When the router degrades, the UI
degrades with it (fewer components, a visible banner) instead of failing.
"""
from __future__ import annotations

from .router import RouteResult

ALLOWED = {"page", "banner", "card", "text", "list", "badge", "actions", "button", "metric"}
BANNER_LEVELS = {"info", "warning", "error"}


def _badge(r: RouteResult) -> dict:
    return {"type": "badge", "label": r.tier, "tone": "ok" if not r.degraded else "warn"}


def build_spec(r: RouteResult, prompt: str) -> dict:
    kids: list[dict] = []
    if not r.ok:
        kids.append({"type": "banner", "level": "error",
                     "text": "All providers unavailable and no cached answer. Try again shortly."})
        kids.append({"type": "actions", "children": [{"type": "button", "label": "Retry", "action": "retry"}]})
        return {"type": "page", "title": "Unavailable", "children": kids}

    if r.tier.startswith("cache"):
        sim = f" (similarity {r.similarity})" if r.tier == "cache_semantic" else ""
        kids.append({"type": "banner", "level": "warning",
                     "text": f"Live models unavailable. Showing a cached answer{sim}."})
    elif r.degraded:
        kids.append({"type": "banner", "level": "info",
                     "text": f"Answered by the {r.tier} tier after upstream failures."})

    card = {"type": "card", "title": prompt[:80], "children": [_badge(r), {"type": "text", "text": r.text}]}
    if r.tier == "frontier":
        card["children"].append({"type": "metric", "label": "latency_ms", "value": round(r.latency_ms, 1)})
        card["children"].append({"type": "list", "items": [a["provider"] + ": " + a["outcome"] for a in r.attempts]})
        kids.append(card)
        kids.append({"type": "actions", "children": [
            {"type": "button", "label": "Follow up", "action": "follow_up"},
            {"type": "button", "label": "Copy", "action": "copy"},
        ]})
    elif r.tier == "mid":
        card["children"].append({"type": "list", "items": [a["provider"] + ": " + a["outcome"] for a in r.attempts]})
        kids.append(card)
    else:  # local or cache: minimal
        kids.append(card)
    return {"type": "page", "title": "Answer", "children": kids}


def validate_spec(node: dict, depth: int = 0) -> list[str]:
    """Return a list of schema errors (empty = valid)."""
    errs: list[str] = []
    if depth > 6:
        return ["too deep"]
    t = node.get("type")
    if t not in ALLOWED:
        errs.append(f"unknown component type: {t!r}")
    if t == "banner" and node.get("level") not in BANNER_LEVELS:
        errs.append("banner.level invalid")
    if t in {"text", "banner"} and not isinstance(node.get("text"), str):
        errs.append(f"{t}.text must be a string")
    if t == "list" and not all(isinstance(i, str) for i in node.get("items", [])):
        errs.append("list.items must be strings")
    for c in node.get("children", []):
        errs.extend(validate_spec(c, depth + 1))
    return errs
