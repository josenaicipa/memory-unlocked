# Install & CLI

## Install

```bash
pipx install memory-unlocked
# or
uv tool install memory-unlocked
# or from source
python -m pip install -e '.[dev]'
```

Core dependencies: none beyond Python stdlib.

Every installation is local and starts empty. The package contains no memory
database and does not contact a hosted Memory Unlocked service.

## Store backends

JSONL is simple and append-only:

```bash
memory-unlocked --path ./.memory init
```

SQLite is recommended for single-machine production:

```bash
memory-unlocked --backend sqlite --path ./.memory init
# or
MEMORY_UNLOCKED_BACKEND=sqlite memory-unlocked --path ./.memory init
memory-unlocked --backend sqlite --path ./.memory doctor
```

## Core commands

```bash
memory-unlocked --path ./.memory write \
  --tenant acme --project demo \
  --title "Refund routing" \
  --body "Refunds route through the billing worker." \
  --source docs/runbook.md \
  --tags billing,refunds

memory-unlocked --path ./.memory context \
  --tenant acme --project demo \
  --query "refund worker" \
  --token-budget 200

memory-unlocked --path ./.memory list --tenant acme --project demo
memory-unlocked --path ./.memory stats --json
```

## Lifecycle/governance

```bash
memory-unlocked --path ./.memory write \
  --tenant acme --project demo \
  --title "Needs approval" \
  --body "Candidate memory pending review." \
  --source docs/review.md \
  --status candidate

memory-unlocked --path ./.memory review --tenant acme --project demo
memory-unlocked --path ./.memory status --id mem_xxx --status active
memory-unlocked --path ./.memory status --id mem_xxx --status archived
memory-unlocked --path ./.memory forget --id mem_xxx
memory-unlocked --path ./.memory audit --json
```

Governance output intentionally omits memory bodies.

## Export/import

```bash
memory-unlocked --path ./.memory export --out export.json
memory-unlocked --path ./.other-memory import --in export.json
```

Imports re-run the policy gate.

## Diagnose an installation

```bash
memory-unlocked --backend sqlite --path ./.memory doctor --json
```

`doctor` reports version, backend, local path, writability, and aggregate memory
count. It never prints memory bodies. A fresh student store should report
`"memories": 0`.

## Eval

```bash
memory-unlocked eval examples/evalset/basic.json
```

The eval harness is offline and checks recall, namespace isolation, and token budgets.
