"""Schema and namespace review for imports and integration boundaries."""

from __future__ import annotations

from typing import Any, Mapping

from .models import MEMORY_KINDS, MEMORY_STATUSES, Namespace
from .namespaces import profile_of


def review_namespace(namespace: Namespace) -> dict[str, Any]:
    """Return neutral namespace findings without inspecting memory bodies."""
    findings = []
    if namespace.tenant != namespace.tenant.strip() or namespace.project != namespace.project.strip():
        findings.append("namespace labels must not have surrounding whitespace")
    return {"ok": not findings, "namespace": namespace.as_key(), "profile": profile_of(namespace), "findings": findings}


def review_memory_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate public schema shape before an import; no mutation or coercion."""
    findings = []
    namespace = record.get("namespace")
    if not isinstance(namespace, Mapping) or not namespace.get("tenant") or not namespace.get("project"):
        findings.append("namespace tenant and project are required")
    if record.get("kind", "fact") not in MEMORY_KINDS:
        findings.append("invalid kind")
    if record.get("status", "active") not in MEMORY_STATUSES:
        findings.append("invalid status")
    source = record.get("source")
    if not isinstance(source, Mapping) or not source.get("ref"):
        findings.append("source ref is required")
    return {"ok": not findings, "findings": findings}
