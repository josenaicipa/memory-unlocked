"""Context assembler tests: ranking, capping, and rendering."""

from memory_unlocked import (
    AssemblerConfig,
    ContextAssembler,
    Memory,
    Namespace,
    Source,
)

NS = Namespace("acme", "billing")


def _mem(title: str, body: str, tags=None, confidence: float = 1.0) -> Memory:
    return Memory(
        namespace=NS,
        title=title,
        body=body,
        source=Source(kind="doc", ref="docs/x.md"),
        tags=tags or [],
        confidence=confidence,
    )


def test_assembled_block_has_header_and_facts(store):
    store.add(_mem("Refunds are async", "Processed by a worker.", ["refunds"]))
    block = ContextAssembler(store).assemble(NS, query="refunds")
    assert block.startswith("# Memory context — acme/billing")
    assert "Refunds are async" in block
    assert "source: doc:docs/x.md" in block


def test_query_overlap_ranks_higher(store):
    store.add(_mem("Unrelated", "talks about deployment pipelines"))
    store.add(_mem("Refund policy", "refund refund refund queue", ["refunds"]))

    selected = ContextAssembler(store).select(NS, query="refund")
    assert selected[0].title == "Refund policy"


def test_max_memories_cap_is_respected(store):
    for i in range(10):
        store.add(_mem(f"fact {i}", f"body number {i}", ["shared"]))

    assembler = ContextAssembler(store, AssemblerConfig(max_memories=3))
    selected = assembler.select(NS, query="body")
    assert len(selected) == 3


def test_char_budget_limits_rendered_block(store):
    long_body = "x" * 500
    for i in range(10):
        store.add(_mem(f"fact {i}", long_body, ["shared"]))

    assembler = ContextAssembler(store, AssemblerConfig(max_memories=10, max_chars=600))
    block = assembler.assemble(NS, query="x")
    # Header + at most one ~500-char fact fits in the 600-char budget.
    assert block.count("**fact") <= 1


def test_empty_query_falls_back_to_confidence(store):
    store.add(_mem("low", "body", confidence=0.2))
    store.add(_mem("high", "body", confidence=0.95))
    selected = ContextAssembler(store).select(NS, query="")
    assert selected[0].title == "high"


def test_recall_emits_event(store):
    store.add(_mem("a", "body about queues", ["q"]))
    ContextAssembler(store).assemble(NS, query="queues")
    recall_events = [e for e in store.events() if e.type == "memory.recall"]
    assert recall_events
    assert recall_events[-1].namespace == NS


def test_ops_recall_emits_one_recall_event(store):
    from memory_unlocked import ops

    store.add(Memory(
        namespace=NS,
        title="Queue retry policy",
        body="Retry jobs three times.",
        source=Source(kind="doc", ref="docs/jobs.md"),
    ))
    before = len([e for e in store.events() if e.type == "memory.recall"])
    result = ops.recall(store, NS, query="retry")
    after = len([e for e in store.events() if e.type == "memory.recall"])

    assert "Queue retry policy" in result["context"]
    assert after - before == 1
