# Memory Unlocked

A **privacy-first, scoped memory fabric** for AI agents. Memory Unlocked is an
open-source skeleton you can use to give your agents durable, project-scoped
memory without leaking secrets or letting one project's context bleed into
another.

It is deliberately small and dependency-free at the core, so you can read the
whole thing, understand it, and adapt it to your stack.

---

## Why this exists

Long-running agents need to remember things between sessions — decisions,
conventions, gotchas, references. But naive "just dump everything into a vector
store" memory has two failure modes:

1. **Secret leakage** — credentials, tokens, customer data, and PII end up
   persisted and later surfaced in unrelated contexts.
2. **Scope bleed** — memory from Project A contaminates answers about Project B.

Memory Unlocked treats both as first-class concerns. Every memory is scoped to a
namespace, every write passes a redaction/policy gate, and recall is filtered by
scope before anything reaches the model.

---

## Who it is for

- Builders of multi-project agent systems who need **isolated** memory per scope.
- Teams that want **auditable, reviewable** writes instead of a black-box store.
- Anyone who wants a **readable reference architecture** they can port to their
  own database, vector index, or MCP server.

---

## Quickstart

```bash
# clone, then from the repo root:
python -m pytest -q          # run the test suite (no external deps required)
```

Use the core package directly:

```python
from memory_unlocked import (
    Memory, Source, Namespace, MemoryStore, ContextAssembler, PolicyError,
)

store = MemoryStore()

store.add(Memory(
    namespace=Namespace("acme", "billing"),
    title="Refunds run through the async queue",
    body="Refund requests are enqueued and processed by a worker, not inline.",
    source=Source(kind="doc", ref="docs/refunds.md"),
    tags=["billing", "architecture"],
))

# Recall is scope-filtered: only memories in the requested namespace come back.
assembler = ContextAssembler(store)
context = assembler.assemble(Namespace("acme", "billing"), query="refund")
print(context)
```

Writes that contain obvious secrets, or that lack a verifiable source, are
rejected at the gate:

```python
store.add(Memory(
    namespace=Namespace("acme", "billing"),
    title="API key",
    body="AWS_SECRET_ACCESS_KEY=AKIA...",   # raises PolicyError
    source=Source(kind="doc", ref="notes.md"),
))
```

---

## Core concepts

| Concept | What it is |
| --- | --- |
| **Memory** | One atomic fact, with a title, body, tags, and a required source. |
| **Source** | Provenance for a memory (a file, URL, ticket, or run id). No source → no write. |
| **Namespace** | A `tenant / project` scope. Recall never crosses namespaces. |
| **Policy / redaction** | A gate every write passes before it is stored. |
| **Context assembler** | Builds a scope-filtered, ranked context block for the agent. |
| **Event** | An append-only record of writes and recalls for auditability. |

---

## Privacy-first guardrails

These are the defaults, not opt-ins:

- **Never store secrets.** Writes are scanned for credential-shaped content and
  rejected. See [`docs/privacy-and-redaction.md`](docs/privacy-and-redaction.md).
- **Every memory needs a source.** Unattributed claims are rejected so memory
  stays verifiable.
- **Scope isolation by default.** A recall in `tenant/project` cannot return a
  memory written under any other scope.
- **No raw transcripts, no PII, no customer/lead data.** Store durable, stable
  facts — not transient progress or personal information.
- **Writes are reviewable.** Every write and recall emits an event so you can
  audit what the memory fabric learned and surfaced.

---

## Documentation

- [Architecture](docs/architecture.md) — components, data flow, scope policy.
- [Privacy & redaction](docs/privacy-and-redaction.md) — what never to store and
  the write-review flow.
- [Schema](docs/schema.md) — the canonical memory, source, link, and event shapes.
- [Integrations](docs/integrations.md) — MCP / HTTP / CLI patterns for agent runners.

---

## License

MIT — see [LICENSE](LICENSE).
