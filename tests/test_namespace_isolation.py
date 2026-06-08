"""Namespace isolation tests: recall must never cross scope."""

from memory_unlocked import ContextAssembler, Memory, Namespace, Source

ACME_BILLING = Namespace("acme", "billing")
ACME_WEB = Namespace("acme", "web")
GLOBEX_DOCS = Namespace("globex", "docs")


def _mem(ns: Namespace, title: str, body: str) -> Memory:
    return Memory(namespace=ns, title=title, body=body,
                  source=Source(kind="doc", ref="docs/x.md"))


def test_recall_is_scoped_to_exact_namespace(store):
    store.add(_mem(ACME_BILLING, "billing fact", "refunds are async"))
    store.add(_mem(ACME_WEB, "web fact", "flags are server-side"))
    store.add(_mem(GLOBEX_DOCS, "docs fact", "versioned per branch"))

    billing = store.query(ACME_BILLING)
    assert len(billing) == 1
    assert billing[0].title == "billing fact"


def test_different_project_same_tenant_is_isolated(store):
    store.add(_mem(ACME_BILLING, "billing fact", "refunds are async"))
    assert store.query(ACME_WEB) == []


def test_cross_tenant_is_isolated(store):
    store.add(_mem(ACME_BILLING, "secret-free acme fact", "internal acme convention"))
    globex = store.query(GLOBEX_DOCS)
    assert globex == []


def test_assembler_never_leaks_other_scope(store):
    store.add(_mem(ACME_WEB, "acme web", "acme only content"))
    store.add(_mem(GLOBEX_DOCS, "globex docs", "globex only content"))

    block = ContextAssembler(store).assemble(GLOBEX_DOCS, query="content")
    assert "globex only content" in block
    assert "acme only content" not in block


def test_empty_scope_returns_empty(store):
    assert store.query(ACME_BILLING) == []
    assert ContextAssembler(store).assemble(ACME_BILLING, "anything") == ""
