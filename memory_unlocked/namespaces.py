"""Generic namespace profiles for common agent boundaries.

Profiles are conveniences, not a third namespace dimension: every returned
value is still the public ``Namespace(tenant, project)`` schema.
"""

from __future__ import annotations

from .models import Namespace

NAMESPACE_PROFILES = ("internal", "lead", "customer", "bot", "agent")


def profile_namespace(profile: str, tenant: str, project: str) -> Namespace:
    """Return a schema-compatible namespace for a named generic profile.

    The profile is part of the project label so stores with different profiles
    stay isolated without changing the serialized namespace schema.
    """
    normalized = (profile or "").strip().lower()
    if normalized not in NAMESPACE_PROFILES:
        raise ValueError(f"profile must be one of {NAMESPACE_PROFILES}")
    safe_project = (project or "").strip()
    if not safe_project:
        raise ValueError("project must be non-empty")
    return Namespace(tenant=tenant, project=f"{normalized}-{safe_project}")


def profile_of(namespace: Namespace) -> str | None:
    """Return the generic profile encoded in a namespace, if present."""
    project = namespace.project.lower()
    for profile in NAMESPACE_PROFILES:
        if project == profile or project.startswith(profile + "-"):
            return profile
    return None
