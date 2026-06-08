# Roadmap

Memory Unlocked is built as a safe, portable memory layer for MCP-compatible AI agents.

## v0.3 - Productization Preview

- [x] CLI + MCP installable package surface
- [x] JSONL and SQLite local backends
- [x] Lifecycle/governance commands
- [x] Offline eval harness
- [x] Hermes quickstart and examples
- [x] Threat model and release checklist

## v0.4 - Production Teams

- [ ] Postgres backend with migrations
- [ ] pluggable embedding/ranking providers with offline default
- [ ] encrypted-at-rest local option
- [ ] signed export/import bundles
- [ ] visual graph UI on top of the deterministic semantic graph
- [ ] richer duplicate merge workflow
- [ ] docs site with screenshots/video

## v0.5 - Managed/Commercial Layer

- [ ] hosted dashboard option
- [ ] team approvals and RBAC
- [ ] organization-wide governance reports
- [ ] SaaS billing and license tiers
- [ ] marketplace recipes for popular agent runners

## Non-goals

- Storing raw conversations by default.
- Becoming a generic vector DB.
- Depending on paid embedding APIs for the core package.
- Shipping private deployment details in the public repo.
