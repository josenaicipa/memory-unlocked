"""Safe Kaizen-style improvement loop that only reports recommended actions."""

from __future__ import annotations

from typing import Any

from .models import Namespace
from .ops import audit, compute_stats
from .store import MemoryStore


def control_loop_report(store: MemoryStore, namespace: Namespace | None = None) -> dict[str, Any]:
    """Return prioritized remediation proposals. Applying them is external and explicit."""
    report = audit(store, namespace)
    actions = []
    for key, message in (
        ("candidates", "review candidate memories"),
        ("duplicates", "review duplicate groups for consolidation"),
        ("contradictions", "review contradictory memories"),
        ("low_confidence", "revalidate low-confidence memories"),
        ("expired", "archive or refresh expired memories"),
    ):
        count = len(report[key])
        if count:
            actions.append({"action": key, "count": count, "recommendation": message, "apply": False})
    return {
        "mode": "dry_run", "scope": namespace.as_key() if namespace else "all",
        "stats": compute_stats(store, namespace), "actions": actions,
    }
