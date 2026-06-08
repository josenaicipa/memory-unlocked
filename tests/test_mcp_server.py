"""MCP stdio server tests: JSON-RPC methods and tool dispatch."""

import io
import itertools
import json

import pytest

from memory_unlocked import Namespace
from memory_unlocked.mcp_server import MemoryMcpServer
from memory_unlocked.persistence import JsonlStore

NS = Namespace("acme", "billing")


def _clock():
    counter = itertools.count(0)
    return lambda: f"2026-01-01T00:00:{next(counter):02d}Z"


@pytest.fixture
def server(tmp_path):
    store = JsonlStore(tmp_path, clock=_clock())
    return MemoryMcpServer(store=store, namespace=NS)


def _req(method, params=None, id=1):
    msg = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def test_initialize_returns_server_info(server):
    resp = server.handle(_req("initialize", {"protocolVersion": "2024-11-05"}))
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert "protocolVersion" in resp["result"]
    assert resp["result"]["serverInfo"]["name"]
    assert "tools" in resp["result"]["capabilities"]


def test_tools_list_exposes_expected_tools(server):
    resp = server.handle(_req("tools/list"))
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {
        "memory_write", "memory_recall", "memory_context",
        "memory_graph_context", "memory_list", "memory_stats",
    }
    for tool in resp["result"]["tools"]:
        assert "inputSchema" in tool
        # Namespace is injected server-side; never a model-controlled param.
        assert "tenant" not in tool["inputSchema"].get("properties", {})
        assert "project" not in tool["inputSchema"].get("properties", {})


def test_tools_call_write_then_recall(server):
    write = server.handle(_req("tools/call", {
        "name": "memory_write",
        "arguments": {
            "title": "Refunds are async",
            "body": "Processed by a worker.",
            "source": "docs/refunds.md",
            "tags": ["billing"],
            "status": "active",
        },
    }))
    assert write["result"]["isError"] is False
    assert write["result"]["structuredContent"]["ok"] is True
    assert write["result"]["structuredContent"]["status"] == "active"

    recall = server.handle(_req("tools/call", {
        "name": "memory_recall",
        "arguments": {"query": "refunds"},
    }))
    text = recall["result"]["content"][0]["text"]
    assert "Refunds are async" in text


def test_tools_call_rejects_secret(server):
    resp = server.handle(_req("tools/call", {
        "name": "memory_write",
        "arguments": {
            "title": "leak",
            "body": "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "source": "notes.md",
        },
    }))
    assert resp["result"]["isError"] is True
    text = resp["result"]["content"][0]["text"]
    assert "secret_detected" in text
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in text


def test_recall_cannot_cross_namespace(tmp_path):
    store = JsonlStore(tmp_path, clock=_clock())
    acme = MemoryMcpServer(store=store, namespace=Namespace("acme", "billing"))
    globex = MemoryMcpServer(store=store, namespace=Namespace("globex", "docs"))

    acme.handle(_req("tools/call", {
        "name": "memory_write",
        "arguments": {"title": "acme secret-free", "body": "acme only content",
                      "source": "x"},
    }))
    resp = globex.handle(_req("tools/call", {
        "name": "memory_recall", "arguments": {"query": "content"},
    }))
    text = resp["result"]["content"][0]["text"]
    assert "acme only content" not in text


def test_unknown_method_returns_error(server):
    resp = server.handle(_req("does/notexist"))
    assert resp["error"]["code"] == -32601


def test_unknown_tool_is_error_result(server):
    resp = server.handle(_req("tools/call", {"name": "nope", "arguments": {}}))
    assert resp["result"]["isError"] is True


def test_notification_returns_no_response(server):
    # A request without an id is a notification; no response is emitted.
    resp = server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp is None


def test_stats_tool(server):
    server.handle(_req("tools/call", {
        "name": "memory_write",
        "arguments": {"title": "a", "body": "x", "source": "s"},
    }))
    resp = server.handle(_req("tools/call", {"name": "memory_stats", "arguments": {}}))
    assert resp["result"]["structuredContent"]["total"] == 1


def test_serve_loop_reads_and_writes_lines(tmp_path):
    store = JsonlStore(tmp_path, clock=_clock())
    server = MemoryMcpServer(store=store, namespace=NS)
    stdin = io.StringIO(json.dumps(_req("initialize")) + "\n")
    stdout = io.StringIO()
    server.serve(stdin, stdout)
    line = stdout.getvalue().strip()
    assert json.loads(line)["result"]["serverInfo"]["name"]
