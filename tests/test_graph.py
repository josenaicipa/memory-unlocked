"""Tests for the public-safe semantic graph layer."""

import json

from memory_unlocked import (
    ENTITY_KINDS,
    Memory,
    Namespace,
    SEMANTIC_RELATIONS,
    Source,
    cli,
)
from memory_unlocked import ops
from memory_unlocked.graph import extract_graph
from memory_unlocked.mcp_server import MemoryMcpServer, build_tools
from memory_unlocked.persistence import JsonlStore

NS = Namespace("acme", "demo")


def _mem(ns, title, body, confidence=1.0):
    return Memory(namespace=ns, title=title, body=body,
                  source=Source(kind="doc", ref="docs/x.md"), confidence=confidence)


def _rels(memories, ns=NS):
    return extract_graph(memories, ns).relations


# --- Vocabulary --------------------------------------------------------------

def test_relation_vocabulary_is_complete():
    expected = {
        "owns", "routes_to", "separate_from", "uses_provider", "fallback_provider",
        "deploys_to", "source_of_truth_for", "sensitive_write", "depends_on", "supersedes",
    }
    assert set(SEMANTIC_RELATIONS) == expected
    # co_occurs is a low-priority fallback, kept out of the semantic set.
    assert "co_occurs" not in SEMANTIC_RELATIONS


def test_entity_kinds_cover_required_set():
    for kind in ("project", "channel", "repo", "url", "provider", "service",
                 "workflow", "decision", "source_of_truth", "module", "topic"):
        assert kind in ENTITY_KINDS


# --- English extraction ------------------------------------------------------

def test_english_patterns_extract_expected_relations():
    m = _mem(NS, "ownership",
             "Billing service owns refunds. Worker depends on Redis. "
             "App deploys to staging. Catalog is the source of truth for products. "
             "Do not mix billing with marketing. Gateway routes to checkout.")
    found = {(r.rel, r.subject, r.object) for r in _rels([m])}
    assert ("owns", "billing service", "refunds") in found
    assert ("depends_on", "worker", "redis") in found
    assert ("deploys_to", "app", "staging") in found
    assert ("source_of_truth_for", "catalog", "products") in found
    assert ("separate_from", "billing", "marketing") in found
    assert ("routes_to", "gateway", "checkout") in found


def test_english_supersedes_and_uses():
    m = _mem(NS, "decisions", "v2 replaces v1. The API uses Stripe.")
    found = {(r.rel, r.subject, r.object) for r in _rels([m])}
    assert ("supersedes", "v2", "v1") in found
    assert ("uses_provider", "api", "stripe") in found


# --- Spanish / Spanglish extraction ------------------------------------------

def test_spanish_patterns_extract_expected_relations():
    m = _mem(NS, "semántica",
             "El landing usa Gemini. El worker depende de Postgres. "
             "CRM es la fuente de verdad de revenue. No mezclar ventas con soporte. "
             "Gestiona la facturacion. Ya no usar legacy usar moderno.")
    found = {(r.rel, r.subject, r.object) for r in _rels([m])}
    assert ("uses_provider", "landing", "gemini") in found
    assert ("depends_on", "worker", "postgres") in found
    assert ("source_of_truth_for", "crm", "revenue") in found
    assert ("separate_from", "ventas", "soporte") in found
    assert ("supersedes", "moderno", "legacy") in found


# --- Nearest-subject fallback (the key requirement) --------------------------

def test_fallback_binds_to_nearest_preceding_subject():
    m = _mem(NS, "providers",
             "Landing AI usa Gemini. CallCenter usa OpenAI. fallback a local_ollama.")
    rels = _rels([m])
    fallbacks = [r for r in rels if r.rel == "fallback_provider"]
    assert len(fallbacks) == 1
    # Binds to the nearest preceding subject (CallCenter), NOT the first (Landing AI).
    assert fallbacks[0].subject == "callcenter"
    assert fallbacks[0].object == "local_ollama"


def test_fallback_without_any_subject_is_dropped():
    m = _mem(NS, "orphan", "fallback a local_ollama.")
    assert [r for r in _rels([m]) if r.rel == "fallback_provider"] == []


# --- Namespace isolation -----------------------------------------------------

def test_no_cross_namespace_leakage():
    other = Namespace("globex", "ops")
    acme_mem = _mem(NS, "acme", "Billing owns refunds.")
    globex_mem = _mem(other, "globex", "Shipping owns labels.")
    graph = extract_graph([acme_mem, globex_mem], NS)
    subjects = {r.subject for r in graph.relations}
    assert "billing" in subjects
    assert "shipping" not in subjects  # the globex memory is excluded by scope


def test_graph_report_is_scope_filtered(tmp_path):
    store = JsonlStore(tmp_path, clock=lambda: "2026-01-01T00:00:00Z")
    store.add(_mem(NS, "acme", "Billing owns refunds."))
    store.add(_mem(Namespace("globex", "ops"), "globex", "Shipping owns labels."))
    report = ops.graph_report(store, NS)
    names = {e["name"] for e in report["entities"]}
    assert "billing" in names
    assert "shipping" not in names


# --- Privacy: no bodies, secret/PII redaction --------------------------------

def test_graph_report_omits_bodies(tmp_path):
    store = JsonlStore(tmp_path, clock=lambda: "2026-01-01T00:00:00Z")
    body = "Billing owns refunds and this body text must never appear in a report."
    store.add(_mem(NS, "ownership", body))
    report = ops.graph_report(store, NS)
    blob = json.dumps(report)
    assert "must never appear" not in blob
    # Titles are allowed (like the audit report); bodies are not.
    assert "ownership" in blob


def test_secret_shaped_relation_is_dropped():
    # Build the memory directly so we exercise the graph gate, not the write gate.
    m = _mem(NS, "keys", "service uses sk-abc123def456ghi789jkl012. worker depends on Redis.")
    rels = _rels([m])
    blob = " ".join(f"{r.subject} {r.object}" for r in rels)
    assert "sk-abc123def456ghi789jkl012" not in blob
    # The clean relation in the same memory still survives.
    assert ("depends_on", "worker", "redis") in {(r.rel, r.subject, r.object) for r in rels}


def test_pii_shaped_relation_is_dropped():
    m = _mem(NS, "contact", "owner is jane.doe@example.com. Worker depends on Redis.")
    blob = " ".join(f"{r.subject} {r.object}" for r in _rels([m]))
    assert "@example.com" not in blob


# --- co_occurs fallback ------------------------------------------------------

def test_co_occurs_only_when_no_semantic_relation():
    m = _mem(NS, "channels", "Discussion in #general about openai and the example.com/site app.")
    graph = extract_graph([m], NS)
    assert graph.relations == []
    pairs = {(r.subject, r.object) for r in graph.co_occurs}
    assert ("#general", "openai") in pairs


# --- CLI smoke ---------------------------------------------------------------

def run(args, path):
    return cli.main(["--path", str(path), *args])


def test_cli_graph_and_graph_context_smoke(tmp_path, capsys):
    store = tmp_path / "store"
    assert run([
        "write", "--tenant", "acme", "--project", "demo",
        "--title", "ownership", "--body", "Billing service owns refunds. Worker depends on Redis.",
        "--source", "docs/public.md",
    ], store) == 0
    capsys.readouterr()

    assert run(["graph", "--tenant", "acme", "--project", "demo", "--json"], store) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["relations"] >= 2
    assert "owns" in report["semantic_relations"]

    assert run([
        "graph-context", "--tenant", "acme", "--project", "demo",
        "--token-budget", "200", "--json",
    ], store) == 0
    ctx = json.loads(capsys.readouterr().out)
    assert ctx["estimated_tokens"] <= 200
    assert "owns" in ctx["context"]


# --- MCP smoke ---------------------------------------------------------------

def test_mcp_lists_and_calls_graph_tool(tmp_path):
    names = {t["name"] for t in build_tools()}
    assert "memory_graph_context" in names

    store = JsonlStore(tmp_path, clock=lambda: "2026-01-01T00:00:00Z")
    server = MemoryMcpServer(store=store, namespace=NS)
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "memory_write",
        "arguments": {"title": "ownership", "body": "Billing owns refunds.",
                      "source": "docs/public.md", "status": "active"},
    }})
    resp = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "memory_graph_context",
        "arguments": {"query": "", "token_budget": 200},
    }})
    assert resp["result"]["isError"] is False
    assert "owns" in resp["result"]["content"][0]["text"]
