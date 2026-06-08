# Semantic Graph

Memory Unlocked v0.3.1 adds a small, deterministic semantic graph layer over stored memories.

It is **not** a visual graph UI yet. It is an agent-facing backend feature: turn stable memory prose into compact, typed relations that can be recalled safely.

## What it extracts

Semantic relation vocabulary:

- `owns`
- `routes_to`
- `separate_from`
- `uses_provider`
- `fallback_provider`
- `deploys_to`
- `source_of_truth_for`
- `sensitive_write`
- `depends_on`
- `supersedes`

Low-priority fallback:

- `co_occurs`

Entity kinds:

- `project`
- `channel`
- `repo`
- `url`
- `provider`
- `service`
- `workflow`
- `decision`
- `source_of_truth`
- `module`
- `topic`

## Examples

```text
Billing service owns refunds.
Worker depends on Redis.
Landing AI usa Gemini. CallCenter usa OpenAI. fallback a local_ollama.
CRM es la fuente de verdad de revenue.
No mezclar ventas con soporte.
```

The fallback example binds `fallback_provider` to the nearest preceding subject (`callcenter`), not to the first subject in the memory.

## CLI

```bash
memory-unlocked --path ./.memory write \
  --tenant acme --project demo \
  --title "Graph demo" \
  --body "Billing service owns refunds. Worker depends on Redis." \
  --source docs/graph.md

memory-unlocked --path ./.memory graph \
  --tenant acme --project demo --json

memory-unlocked --path ./.memory graph-context \
  --tenant acme --project demo --token-budget 200
```

## MCP

The MCP server exposes:

- `memory_graph_context`

It returns a compact, token-budgeted semantic graph context block for the runtime-bound namespace.

## Safety model

- Extraction is deterministic regex only: no LLM extraction, no network calls.
- Graph extraction receives already scope-filtered memories and re-checks namespace.
- Entity/relation names pass the secret/PII detectors; unsafe fragments are dropped.
- Reports and context never include raw memory bodies.
- Generic aliasing only; the public package has no private channel/project/domain map.

## Governance

`graph` reports include warnings for:

- no semantic relations found;
- many low-priority co-occurrence edges;
- duplicate/noisy entity names.

Use those warnings to rewrite memories into clearer relation phrasing like `X owns Y`, `X uses_provider Y`, or `X source_of_truth_for Y`.
