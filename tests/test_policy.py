"""Policy gate tests: secret rejection and mandatory source."""

import pytest

from memory_unlocked import Memory, Namespace, PolicyError, Source

NS = Namespace("acme", "billing")


def _good_source() -> Source:
    return Source(kind="doc", ref="docs/example.md")


@pytest.mark.parametrize(
    "body",
    [
        "AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE",
        "use this key AKIAIOSFODNN7EXAMPLE for access",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789",
        "token is ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "set password = hunter2secret",
        "-----BEGIN RSA PRIVATE KEY-----",
        "openai sk-abcdefghijklmnopqrstuvwxyz123456",
    ],
)
def test_rejects_secrets_in_body(store, body):
    """Writes containing credential-shaped content are hard-rejected."""
    mem = Memory(
        namespace=NS,
        title="harmless title",
        body=body,
        source=_good_source(),
    )
    with pytest.raises(PolicyError) as exc:
        store.add(mem)
    assert exc.value.reason == "secret_detected"
    # Nothing was stored.
    assert list(store.all()) == []


def test_rejects_secret_in_title(store):
    mem = Memory(
        namespace=NS,
        title="key AKIAIOSFODNN7EXAMPLE",
        body="a perfectly fine body about architecture",
        source=_good_source(),
    )
    with pytest.raises(PolicyError) as exc:
        store.add(mem)
    assert exc.value.reason == "secret_detected"


def test_rejection_emits_audit_event_without_secret(store):
    mem = Memory(
        namespace=NS,
        title="leak",
        body="password = supersecretvalue",
        source=_good_source(),
    )
    with pytest.raises(PolicyError):
        store.add(mem)

    events = store.events()
    assert len(events) == 1
    assert events[0].type == "memory.reject"
    assert events[0].detail == {"reason": "secret_detected"}
    # The offending value never appears in the audit trail.
    assert "supersecretvalue" not in str(events[0].detail)


def test_missing_source_is_rejected_at_construction():
    """A Source with an empty ref cannot even be constructed."""
    with pytest.raises(ValueError):
        Source(kind="doc", ref="")


def test_clean_memory_passes(store):
    mem = Memory(
        namespace=NS,
        title="Refunds use the async queue",
        body="Refunds are processed by a worker to keep checkout fast.",
        source=_good_source(),
        tags=["billing", "Billing", "architecture"],
    )
    stored = store.add(mem)
    assert stored.id == "mem_0001"
    assert stored.created_at is not None
    # Tags were normalized (lowercased + de-duplicated).
    assert stored.tags == ["billing", "architecture"]
