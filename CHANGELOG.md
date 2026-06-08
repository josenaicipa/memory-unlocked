# Changelog

## 0.3.1 - Semantic Graph Layer

### Added

- Deterministic public-safe semantic graph extraction.
- Relation vocabulary: `owns`, `routes_to`, `separate_from`, `uses_provider`, `fallback_provider`, `deploys_to`, `source_of_truth_for`, `sensitive_write`, `depends_on`, `supersedes`.
- Spanish/Spanglish extraction patterns including `usa`, `depende de`, `fuente de verdad`, `no mezclar`, `fallback a`.
- Nearest-subject fallback binding for `fallback_provider`.
- CLI commands: `graph` and `graph-context`.
- MCP tool: `memory_graph_context`.
- Graph docs and public example.

### Security

- Graph reports/context omit memory bodies.
- Entity/relation names pass secret/PII filters before emission.
- Graph extraction remains namespace-scoped and deterministic.

## 0.3.0 - Productization Preview

Memory Unlocked moves from an installable skeleton to a product-grade local agent memory toolkit.

### Added

- SQLite backend via `--backend sqlite` / `MEMORY_UNLOCKED_BACKEND=sqlite`.
- Lifecycle states: `candidate`, `active`, `archived`, `rejected`.
- Governance commands: `audit`, `review`, `status`, `forget`.
- Token-budgeted context assembly via CLI `context --token-budget` and MCP `memory_context`.
- Offline eval harness: `memory-unlocked eval examples/evalset/basic.json`.
- Safer context rendering that treats memories as data, not instructions.
- Size limits and PII handling policy knobs.
- Public examples for Hermes, team memory, SQLite production, and evalsets.

### Security

- Recall logs redact secret-shaped queries.
- Rejected writes never persist the rejected content.
- Memory bodies are omitted from governance reports.

## 0.2.0

- CLI and MCP server.
- Durable JSONL storage.
- Secret policy gate and public docs.

## 0.1.0

- Public architecture skeleton, schema, examples, and tests.
