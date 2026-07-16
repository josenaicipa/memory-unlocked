"""MCP stdio server tests: JSON-RPC methods and tool dispatch."""

import io
import itertools
import json

import pytest

from memory_unlocked import Namespace
from memory_unlocked.mcp_server import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    LATEST_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    MemoryMcpServer,
)
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


@pytest.mark.parametrize("protocol_version", SUPPORTED_PROTOCOL_VERSIONS)
def test_initialize_negotiates_supported_protocol_versions(server, protocol_version):
    resp = server.handle(_req("initialize", {"protocolVersion": protocol_version}))
    assert resp["result"]["protocolVersion"] == protocol_version


def test_initialize_uses_latest_protocol_for_unknown_or_missing_client_version(server):
    unknown = server.handle(_req("initialize", {"protocolVersion": "2099-01-01"}))
    missing = server.handle(_req("initialize", {}))
    assert unknown["result"]["protocolVersion"] == LATEST_PROTOCOL_VERSION
    assert missing["result"]["protocolVersion"] == LATEST_PROTOCOL_VERSION


def test_tools_list_exposes_expected_tools(server):
    resp = server.handle(_req("tools/list"))
    names = {t["name"] for t in resp["result"]["tools"]}
    assert {
        "memory_write", "memory_recall", "memory_context",
        "memory_graph_context", "memory_list", "memory_stats",
    } <= names
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


def test_internal_tool_error_never_echoes_exception_text(server, monkeypatch):
    private_marker = "private-input-must-not-be-reflected"

    def fail_write(*args, **kwargs):
        raise RuntimeError(private_marker)

    monkeypatch.setattr("memory_unlocked.mcp_server.ops.write_memory", fail_write)
    resp = server.handle(_req("tools/call", {
        "name": "memory_write",
        "arguments": {"title": "safe", "body": "safe", "source": "safe"},
    }))
    text = resp["result"]["content"][0]["text"]
    assert resp["result"]["isError"] is True
    assert text == "tool failed: internal error"
    assert private_marker not in json.dumps(resp)


def test_notification_returns_no_response(server):
    # A request without an id is a notification; no response is emitted.
    resp = server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp is None


@pytest.mark.parametrize("bad_request", [None, [], "invalid", 7])
def test_non_object_json_rpc_request_returns_invalid_request(server, bad_request):
    resp = server.handle(bad_request)
    assert resp["id"] is None
    assert resp["error"]["code"] == INVALID_REQUEST


@pytest.mark.parametrize(
    "invalid_request",
    [
        {"jsonrpc": "2.0", "id": 1},
        {"jsonrpc": "1.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "id": 1, "method": 7},
    ],
)
def test_malformed_json_rpc_object_returns_invalid_request(server, invalid_request):
    resp = server.handle(invalid_request)
    assert resp["id"] == 1
    assert resp["error"]["code"] == INVALID_REQUEST


def test_ping_notification_never_gets_a_response(server):
    assert server.handle({"jsonrpc": "2.0", "method": "ping"}) is None


def test_array_params_return_invalid_params(server):
    resp = server.handle(_req("tools/call", []))
    assert resp["error"]["code"] == INVALID_PARAMS


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


def test_serve_survives_non_object_and_suppresses_notification(tmp_path):
    store = JsonlStore(tmp_path, clock=_clock())
    server = MemoryMcpServer(store=store, namespace=NS)
    messages = [
        [],
        {"jsonrpc": "2.0", "method": "ping"},
        _req("ping", id=2),
    ]
    stdin = io.StringIO("".join(json.dumps(message) + "\n" for message in messages))
    stdout = io.StringIO()

    server.serve(stdin, stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert len(responses) == 2
    assert responses[0]["error"]["code"] == INVALID_REQUEST
    assert responses[1] == {"jsonrpc": "2.0", "id": 2, "result": {}}
