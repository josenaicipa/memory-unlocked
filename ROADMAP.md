# Roadmap

Memory Unlocked is a safe, portable local memory layer for MCP-compatible AI agents.

## v1.0 - Stable Local MCP

- [x] Dependency-free CLI and MCP package
- [x] JSONL and SQLite local backends
- [x] Empty-by-default, local-per-installation student model
- [x] Process-bound tenant/project isolation
- [x] Lifecycle, review, audit, export, import, and forgetting
- [x] Offline recall/privacy eval harness
- [x] Deterministic public-safe semantic graph
- [x] Current MCP protocol negotiation with backward compatibility
- [x] Cross-platform CI and exact release-artifact smoke
- [x] Student quickstart, threat model, and privacy documentation

## v1.x - Optional Local Enhancements

- [ ] encrypted-at-rest local option
- [ ] signed export/import bundles
- [ ] richer duplicate merge workflow
- [ ] visual graph UI on top of the deterministic semantic graph
- [ ] additional MCP-client setup recipes

## Future Team/Hosted Layer

These are separate products and are not implied by the local v1 contract:

- [ ] Postgres backend with migrations
- [ ] authenticated multi-user service
- [ ] tenant authorization, RBAC, quotas, and deletion controls
- [ ] hosted dashboard and organization governance reports

## Non-goals

- Storing raw conversations by default.
- Becoming a generic vector database.
- Depending on paid embedding APIs for the core package.
- Connecting student installations to a maintainer/private database.
- Shipping private deployment details in the public repository.
