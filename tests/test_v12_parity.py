"""Portable v1.2 memory-fabric surfaces remain local and scope-bound."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from memory_unlocked import (
    AssetRegistry,
    MarkdownMirror,
    Memory,
    MemoryStore,
    Namespace,
    Source,
    build_channel_contracts,
    control_loop_report,
    dashboard_data,
    plan_consolidation,
    profile_namespace,
    rank_v2,
    reflex_post_task,
    reflex_pre_task,
    review_memory_record,
    validate_channel_contracts,
)


NS = Namespace("example", "demo")


def _memory(title: str, body: str, status: str = "active") -> Memory:
    return Memory(NS, title, body, Source("doc", "docs/example.md"), status=status)


def test_profiles_mirror_and_dashboard_are_schema_safe(tmp_path):
    assert profile_namespace("agent", "example", "demo") == Namespace("example", "agent-demo")
    store = MemoryStore()
    memory = store.add(_memory("Durable fact", "A stable, public-safe fact."))
    target = MarkdownMirror(tmp_path / "mirror").sync(memory)
    assert target and target.is_file()
    assert "A stable, public-safe fact." in target.read_text(encoding="utf-8")
    snapshot = dashboard_data(store, NS)
    assert snapshot["stats"]["total"] == 1
    assert "body" not in str(snapshot).lower()


def test_reflex_consolidation_and_control_loop_are_propose_only():
    store = MemoryStore()
    first = store.add(_memory("Routing", "Requests route through the worker."))
    second = store.add(_memory("Routing duplicate", "Requests route through the worker."))
    before = len(list(store.all()))
    assert "context" in reflex_pre_task(store, NS, "worker")
    proposal = reflex_post_task(store, NS, "New finding", "A durable finding.", "run:1")
    assert proposal["requires_review"] is True
    assert len(list(store.all())) == before
    plans = plan_consolidation([first, second], NS, threshold=0.1)
    assert plans and plans[0].requires_approval is True
    assert control_loop_report(store, NS)["mode"] == "dry_run"


def test_assets_retrieval_review_and_channel_contracts_are_scoped(tmp_path):
    assets = AssetRegistry(tmp_path / "assets.json")
    candidate = assets.create(NS, "Example template", "Use a neutral template.", "docs/template.md")
    assets.set_status(candidate.id, "active")
    assert [item.id for item in assets.list(NS)] == [candidate.id]
    try:
        assets.create(NS, "Unsafe", "api_key=not-a-real-key", "docs/template.md")
    except ValueError as exc:
        assert "secret" in str(exc)
    else:  # pragma: no cover - a secret-shaped asset must never persist
        raise AssertionError("secret-shaped asset was accepted")

    store = MemoryStore()
    stored = store.add(_memory("Refund routing", "Refund requests route to billing."))
    other = store.add(Memory(Namespace("other", "demo"), "Other", "refund outside scope", Source("doc", "docs/other.md")))
    ranked = rank_v2(store.query(NS, match=False), "refund")
    assert [item.memory.id for item in ranked] == [stored.id]
    assert other.id not in [item.memory.id for item in ranked]

    assert review_memory_record({"namespace": {"tenant": "x", "project": "y"}, "source": {"ref": "docs/x.md"}})["ok"]
    contracts = build_channel_contracts({"support": NS})
    assert validate_channel_contracts(contracts) == [{"channel": "support", "status": "ready", "reason": ""}]


def test_packaged_hermes_provider_is_configuration_bound(tmp_path, monkeypatch):
    plugin_path = Path(__file__).parents[1] / "memory_unlocked" / "hermes_plugin" / "__init__.py"
    spec = importlib.util.spec_from_file_location("memory_fabric_test_plugin", plugin_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MEMORY_FABRIC_PATH", "local-store")
    monkeypatch.setenv("MEMORY_FABRIC_BACKEND", "sqlite")
    monkeypatch.setenv("MEMORY_FABRIC_TENANT", "example")
    monkeypatch.setenv("MEMORY_FABRIC_PROJECT", "demo")
    provider = module.MemoryFabricProvider()
    assert provider.is_available()
    assert 'initialized' in provider.handle_tool_call("memory_fabric_context", {"query": "x"})
    provider.initialize("session-1")
    proposal = provider.handle_tool_call("memory_fabric_propose", {"title": "Fact", "body": "A durable fact.", "source": "docs/fact.md"})
    assert '"proposal"' in proposal
    written = provider.handle_tool_call("memory_fabric_propose", {"title": "Fact", "body": "A durable fact.", "source": "docs/fact.md", "write": True})
    assert '"candidate"' in written
    assert "Fact" not in provider.handle_tool_call("memory_fabric_context", {"query": "Fact"})
