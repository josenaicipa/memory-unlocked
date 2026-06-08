# Hermes Basic Example

A minimal Memory Unlocked MCP setup for a single Hermes project scope.

```bash
uv tool install memory-unlocked
mkdir -p ~/.memory-unlocked/hermes-basic

MEMORY_UNLOCKED_HOME=~/.memory-unlocked/hermes-basic \
MEMORY_UNLOCKED_TENANT=acme \
MEMORY_UNLOCKED_PROJECT=demo \
memory-unlocked-mcp
```

Example Hermes MCP command shape:

```bash
hermes mcp add memory-unlocked \
  --env MEMORY_UNLOCKED_HOME="$HOME/.memory-unlocked/hermes-basic" \
  --env MEMORY_UNLOCKED_TENANT="acme" \
  --env MEMORY_UNLOCKED_PROJECT="demo" \
  -- memory-unlocked-mcp
```

Smoke through CLI:

```bash
memory-unlocked --path ~/.memory-unlocked/hermes-basic write \
  --tenant acme --project demo \
  --title "Public install works" \
  --body "Memory Unlocked can store scoped public-safe facts." \
  --source examples/hermes-basic/README.md

memory-unlocked --path ~/.memory-unlocked/hermes-basic context \
  --tenant acme --project demo --query install --token-budget 200
```
