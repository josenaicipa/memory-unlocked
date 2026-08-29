"""v1.1 public-safe capabilities: thread scope, retrieval, curator, TTL, session."""

from __future__ import annotations

import json

import pytest

from memory_unlocked import (
    Memory,
    Namespace,
    PolicyError,
    Source,
    admits_thread,
    curate,
    rank_candidates,
    summarize_session_events,
)
from memory_unlocked.cli import main as cli_main
from memory_unlocked.fusion import UnauthorizedCandidateError, reciprocal_rank_fusion
from memory_unlocked.mcp_server import FORBIDDEN_SCOPE_KEYS, MemoryMcpServer, build_tools
from memory_unlocked.persistence import JsonlStore
from memory_unlocked.sqlite_store import SqliteStore
from memory_unlocked.store import MemoryStore
from memory_unlocked.thread_scope import ThreadScopeError, normalize_thread

NS = Namespace("acme", "billing")


def _mem(title, body, thread=None, expires_at=None, status="active", confidence=1.0):
    return Memory(
        namespace=NS,
        title=title,
        body=body,
        source=Source(kind="doc", ref="docs/x.md"),
        thread=thread,
        expires_at=expires_at,
        status=status,
        confidence=confidence,
    )


def test_thread_predicate_never_admits_siblings():
    assert admits_thread(None, None) is True
    assert admits_thread("ticket-1", None) is False
    assert admits_thread("ticket-1", "ticket-1") is True
    assert admits_thread(None, "ticket-1") is True  # inherit project-level
    assert admits_thread("ticket-2", "ticket-1") is False
    assert admits_thread("ticket-1", "ticket-1", mode="exact") is True
    assert admits_thread(None, "ticket-1", mode="exact") is False


def test_thread_wildcards_are_rejected():
    with pytest.raises(ThreadScopeError):
        normalize_thread("all_threads")
    with pytest.raises(ThreadScopeError):
        normalize_thread("*")


def test_store_query_isolates_threads(store):
    store.add(_mem("project fact", "Refunds are async."))
    store.add(_mem("thread a", "Ticket A uses the worker.", thread="ticket-a"))
    store.add(_mem("thread b", "Ticket B uses a different queue.", thread="ticket-b"))

    unnamed = [m.title for m in store.query(NS)]
    assert unnamed == ["project fact"]

    ticket_a = [m.title for m in store.query(NS, thread="ticket-a")]
    assert ticket_a == ["project fact", "thread a"]

    ticket_b = [m.title for m in store.query(NS, thread="ticket-b")]
    assert ticket_b == ["project fact", "thread b"]
    assert "thread a" not in ticket_b


def test_expired_memories_leave_recall_but_remain_stored(store):
    live = store.add(_mem("live", "Still valid."))
    expired = store.add(_mem("gone", "Past the ttl.", expires_at="2020-01-01T00:00:00Z"))
    recalled = store.query(NS, now="2026-01-01T00:00:00Z")
    assert [m.id for m in recalled] == [live.id]
    assert store.get(expired.id) is not None
    kept = store.query(NS, include_expired=True, now="2026-01-01T00:00:00Z")
    assert {m.id for m in kept} == {live.id, expired.id}


def test_v10_jsonl_without_thread_still_loads(tmp_path):
    path = tmp_path / "memories.jsonl"
    path.write_text(
        json.dumps({
            "id": "mem_old",
            "namespace": {"tenant": "acme", "project": "billing"},
            "title": "legacy",
            "body": "Written before threads existed.",
            "kind": "fact",
            "tags": [],
            "source": {"kind": "doc", "ref": "docs/old.md", "note": None},
            "links": [],
            "confidence": 1.0,
            "status": "active",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        })
        + "\n",
        encoding="utf-8",
    )
    store = JsonlStore(tmp_path)
    loaded = list(store.query(NS))
    assert len(loaded) == 1
    assert loaded[0].thread is None
    assert loaded[0].expires_at is None


def test_sqlite_adds_v11_columns_on_legacy_schema(tmp_path):
    db = tmp_path / "legacy.db"
    import sqlite3

    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE memories (id TEXT PRIMARY KEY, tenant TEXT, project TEXT, "
        "title TEXT, body TEXT, kind TEXT, tags TEXT, source TEXT, links TEXT, "
        "confidence REAL, status TEXT, created_at TEXT, updated_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, "
        "tenant TEXT, project TEXT, at TEXT, detail TEXT)"
    )
    conn.execute(
        "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "mem_legacy",
            "acme",
            "billing",
            "old sqlite",
            "Legacy row without thread.",
            "fact",
            "[]",
            json.dumps({"kind": "doc", "ref": "docs/old.md"}),
            "[]",
            1.0,
            "active",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    store = SqliteStore(db)
    loaded = list(store.query(NS))
    assert loaded[0].title == "old sqlite"
    assert loaded[0].thread is None
    added = store.add(_mem("threaded", "New row.", thread="ticket-a"))
    reopened = SqliteStore(db)
    titles = {m.title: m.thread for m in reopened.query(NS, thread="ticket-a")}
    assert titles["old sqlite"] is None
    assert titles["threaded"] == "ticket-a"
    assert added.id in {m.id for m in reopened.all()}


def test_hybrid_retrieval_cannot_widen_authorized_set(store):
    in_scope = store.add(_mem("Refunds", "Refunds run through the async worker."))
    other = Memory(
        namespace=Namespace("other", "demo"),
        title="Secret sibling",
        body="Refunds in another project.",
        source=Source(kind="doc", ref="docs/y.md"),
    )
    store.add(other)
    authorized = store.query(NS)
    ranked = rank_candidates(authorized, query="refunds worker", mode="hybrid")
    assert [m.id for m in ranked] == [in_scope.id]


def test_fusion_rejects_unauthorized_ids():
    with pytest.raises(UnauthorizedCandidateError) as exc:
        reciprocal_rank_fusion(
            [["mem_ok", "mem_leak"]],
            authorized_ids=frozenset({"mem_ok"}),
        )
    assert "mem_leak" in exc.value.offending_ids


def test_lexical_mode_prefers_query_terms(store):
    weak = store.add(_mem("Shipping", "Warehouse prints labels."))
    strong = store.add(_mem("Refund worker", "Refunds are handled by the billing worker."))
    ranked = rank_candidates(list(store.query(NS)), query="refund worker", mode="lexical")
    assert ranked[0].id == strong.id
    assert weak.id not in {m.id for m in ranked} or ranked[0].id == strong.id


def test_curator_is_propose_only_and_deterministic(store):
    first = store.add(_mem("Dup", "The same fact twice."))
    store.add(_mem("Dup", "The same fact twice."))
    snapshot = list(store.all())
    plan_a = curate(snapshot, namespace=NS, now="2026-01-01T00:00:00Z")
    plan_b = curate(snapshot, namespace=NS, now="2026-01-01T00:00:00Z")
    assert plan_a["writes_performed"] == 0
    assert plan_a["applied"] is False
    assert plan_a["requires_human_review"] is True
    assert plan_a["plan_id"] == plan_b["plan_id"]
    assert any(item["action"] in ("archive_duplicate", "merge_near_duplicates") for item in plan_a["proposals"])
    assert store.get(first.id) is not None
    assert len(list(store.all())) == 2


def test_curator_evidence_omits_bodies(store):
    store.add(_mem("Contact policy", "Do not store personal emails in memory."))
    plan = curate(list(store.all()), namespace=NS, now="2026-01-01T00:00:00Z")
    blob = json.dumps(plan)
    assert "Do not store personal emails in memory." not in blob
    for proposal in plan["proposals"]:
        for evidence in proposal["evidence"]:
            assert "body" not in evidence


def test_session_summary_blocks_secrets_and_never_writes():
    blocked = summarize_session_events(
        [{"role": "user", "content": "token is ghp_abcdefghijklmnopqrstuvwxyz0123456789"}],
        session_id="s1",
    )
    assert blocked.secret_like_content is True
    assert blocked.durable_proposals == []
    assert "ghp_" not in blocked.redacted_summary

    ok = summarize_session_events(
        [{"role": "user", "content": "We decided refunds use the async worker."}],
        session_id="s2",
    )
    assert ok.secret_like_content is False
    assert ok.episodic_only is True
    assert ok.write_policy.startswith("propose-only")
    assert ok.durable_proposals


def test_cli_thread_and_hybrid_and_curate(tmp_path, capsys):
    home = str(tmp_path)
    assert cli_main([
        "--path", home, "write", "--tenant", "acme", "--project", "billing",
        "--title", "Project fact", "--body", "Refunds are async.",
        "--source", "docs/x.md", "--json",
    ]) == 0
    capsys.readouterr()
    assert cli_main([
        "--path", home, "write", "--tenant", "acme", "--project", "billing",
        "--thread", "ticket-a", "--title", "Thread fact",
        "--body", "Ticket A depends on Redis.", "--source", "docs/x.md", "--json",
    ]) == 0
    capsys.readouterr()
    assert cli_main([
        "--path", home, "recall", "--tenant", "acme", "--project", "billing",
        "--query", "redis", "--json",
    ]) == 0
    unnamed = json.loads(capsys.readouterr().out)
    assert unnamed["matches"] == []
    assert cli_main([
        "--path", home, "recall", "--tenant", "acme", "--project", "billing",
        "--thread", "ticket-a", "--query", "redis", "--mode", "hybrid", "--json",
    ]) == 0
    threaded = json.loads(capsys.readouterr().out)
    assert threaded["matches"][0]["title"] == "Thread fact"
    assert cli_main([
        "--path", home, "curate", "--tenant", "acme", "--project", "billing",
        "--now", "2026-01-01T00:00:00Z", "--json",
    ]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["writes_performed"] == 0


def test_mcp_rejects_model_controlled_scope_and_exposes_curate():
    names = {tool["name"] for tool in build_tools()}
    assert "memory_curate" in names
    store = MemoryStore(clock=lambda: "2026-01-01T00:00:00Z")
    server = MemoryMcpServer(store=store, namespace=NS, thread="ticket-a")
    denied = server.handle({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "memory_recall",
            "arguments": {"query": "x", "thread": "ticket-b"},
        },
    })
    assert denied["result"]["isError"] is True
    assert "scope" in denied["result"]["content"][0]["text"]
    assert FORBIDDEN_SCOPE_KEYS


def test_mcp_thread_binding_is_process_scoped():
    store = MemoryStore(clock=lambda: "2026-01-01T00:00:00Z")
    server = MemoryMcpServer(store=store, namespace=NS, thread="ticket-a")
    write = server.handle({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "memory_write",
            "arguments": {
                "title": "Bound thread",
                "body": "This fact belongs to ticket A.",
                "source": "docs/x.md",
                "status": "active",
            },
        },
    })
    assert write["result"]["structuredContent"]["thread"] == "ticket-a"
    other = MemoryMcpServer(store=store, namespace=NS, thread="ticket-b")
    listed = other.handle({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "memory_list", "arguments": {}},
    })
    assert listed["result"]["structuredContent"]["memories"] == []


def test_new_secret_kinds_are_rejected(store):
    with pytest.raises(PolicyError) as exc:
        store.add(_mem("key", "github_pat_" + ("a" * 22)))
    assert exc.value.reason == "secret_detected"
    with pytest.raises(PolicyError):
        store.add(_mem("dsn", "postgres://user:hunter2secret@db.example.com/app"))
