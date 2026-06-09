"""Public-safe graph promotion surfaces: temporal, lineage, effective backend."""

from __future__ import annotations

import json

from memory_unlocked import Namespace, cli
from memory_unlocked.mcp_server import MemoryMcpServer, build_tools
from memory_unlocked.persistence import JsonlStore
from memory_unlocked.policy import PolicyConfig
from tests.test_graph import NS, _mem, run
from memory_unlocked import ops


def test_temporal_lineage_and_effective_backend_are_public_safe(tmp_path):
    store = JsonlStore(tmp_path, policy=PolicyConfig(pii_mode="redact"), clock=lambda: "2026-01-01T00:00:00Z")
    stored = store.add(_mem(NS, "ownership", "Billing owns refunds. Contact jane@example.com must not leak."))
    other = Namespace("other", "demo")
    store.add(_mem(other, "other", "Shipping owns labels."))

    temporal = ops.graph_temporal_report(store, NS)
    assert temporal["command"] == "memory_graph_temporal_report"
    assert temporal["dry_run"] is True
    assert temporal["writes_performed"] == 0
    assert temporal["relations"][0]["current"] is True
    assert temporal["relations"][0]["valid_from"] == "2026-01-01T00:00:00Z"

    lineage = ops.graph_lineage_report(store, NS)
    blob = json.dumps(lineage)
    assert lineage["relation_evidence"][0]["memory_handle"] == "m1"
    assert str(stored.id) not in blob
    assert "docs/x.md" not in blob
    assert "jane@example.com" not in blob
    assert "must not leak" not in blob
    assert "Shipping" not in blob

    backend = ops.graph_effective_backend(store, NS)
    assert backend["command"] == "memory_graph_effective_backend"
    assert backend["effective_backend"] == "memory_unlocked"
    assert backend["cutover_ready"] is True
    assert backend["dry_run"] is True
    assert backend["writes_performed"] == 0
    assert backend["edge_count"] == 1
    backend_blob = json.dumps(backend)
    assert "source_memory_id" not in backend_blob
    assert str(stored.id) not in backend_blob
    assert "Shipping" not in backend_blob


def test_cli_public_graph_surfaces(tmp_path, capsys):
    store = tmp_path / "store"
    assert run([
        "write", "--tenant", "acme", "--project", "demo",
        "--title", "ownership", "--body", "Billing owns refunds.",
        "--source", "docs/public.md",
    ], store) == 0
    capsys.readouterr()

    for command, expected in [
        ("graph-temporal", "memory_graph_temporal_report"),
        ("graph-lineage", "memory_graph_lineage"),
        ("graph-effective-backend", "memory_graph_effective_backend"),
    ]:
        assert run([command, "--tenant", "acme", "--project", "demo", "--json"], store) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["command"] == expected
        assert out["dry_run"] is True
        assert out["writes_performed"] == 0


def test_mcp_exposes_public_graph_surfaces(tmp_path):
    names = {tool["name"] for tool in build_tools()}
    assert {"memory_graph_temporal", "memory_graph_lineage", "memory_graph_effective_backend"} <= names

    store = JsonlStore(tmp_path, clock=lambda: "2026-01-01T00:00:00Z")
    server = MemoryMcpServer(store=store, namespace=NS)
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "memory_write",
        "arguments": {"title": "ownership", "body": "Billing owns refunds.",
                      "source": "docs/public.md", "status": "active"},
    }})
    resp = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "memory_graph_effective_backend", "arguments": {},
    }})
    assert resp is not None
    assert resp["result"]["isError"] is False
    assert resp["result"]["structuredContent"]["effective_backend"] == "memory_unlocked"
