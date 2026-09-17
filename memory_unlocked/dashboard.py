"""Body-free audit dashboard data and a standalone local HTML rendering."""

from __future__ import annotations

from html import escape
from typing import Any

from .models import Namespace
from .ops import audit, compute_stats
from .store import MemoryStore


def dashboard_data(store: MemoryStore, namespace: Namespace | None = None) -> dict[str, Any]:
    """Return a safe operational snapshot; memory bodies are deliberately absent."""
    report = audit(store, namespace=namespace)
    stats = compute_stats(store, namespace=namespace)
    return {
        "scope": namespace.as_key() if namespace else "all",
        "stats": stats,
        "review": {
            "candidates": len(report["candidates"]),
            "low_confidence": len(report["low_confidence"]),
            "duplicates": len(report["duplicates"]),
            "contradictions": len(report["contradictions"]),
            "expired": len(report["expired"]),
        },
    }


def render_dashboard(store: MemoryStore, namespace: Namespace | None = None) -> str:
    """Render a dependency-free HTML dashboard from the safe snapshot."""
    data = dashboard_data(store, namespace)
    cards = list(data["review"].items()) + [("memories", data["stats"]["total"])]
    items = "".join(
        f"<li><strong>{escape(key.replace('_', ' '))}</strong>: {escape(str(value))}</li>"
        for key, value in cards
    )
    return (
        "<!doctype html><meta charset=utf-8><title>Memory Fabric audit</title>"
        "<main><h1>Memory Fabric audit</h1>"
        f"<p>Scope: {escape(data['scope'])}</p><ul>{items}</ul>"
        "<p>Memory bodies are intentionally omitted.</p></main>"
    )
