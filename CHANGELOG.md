# Changelog

## 1.0.0 - Stable Local MCP for Students

### Added

- Stable local-per-installation contract: every new store starts with zero memories and has no connection to any maintainer or other student store.
- `memory-unlocked doctor` for version, backend, writability, scope, and aggregate-count diagnostics without exposing memory bodies.
- Student quickstart covering isolated SQLite setup, MCP binding, backup, restore, and deletion.
- Release-artifact smoke that verifies an empty initial store, nine MCP tools, same-scope recall, and cross-project isolation.
- MCP protocol negotiation through the official `2025-11-25` version while retaining support for `2024-11-05`, `2025-03-26`, and `2025-06-18` clients.
- Fail-closed JSON-RPC validation for malformed messages, invalid params, and notifications that must never receive responses.
- Linux Python 3.9-3.13, macOS Python 3.11, and Windows Python 3.11 CI coverage.
- Verified wheel/sdist publication workflow with checksums, GitHub release assets, and PyPI trusted publishing.
- Split, least-privilege release jobs with SHA-pinned GitHub Actions and a PyPI job that receives only verified wheel/sdist artifacts.

### Security

- The public package ships no database, memory export, environment file, private namespace, or hosted-service connection.
- Tenant/project remain process-bound MCP configuration and are never model-controlled tool arguments.

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
