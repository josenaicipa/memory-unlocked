# Student Quickstart: one private memory per computer

Memory Unlocked v1.1 is a **local MCP package**. Each student installs it on their own computer and receives a fresh store with **0 memories**. It does not contact a shared server, the instructor's store, or other students. v1.1 optional flags (thread, TTL, retrieval mode) default off so a v1.0 workflow is unchanged.

## 1. Install

```bash
uv tool install memory-unlocked
```

Check the installation and create a default empty store with `memory-unlocked doctor`,
or use the explicit SQLite path below:

```bash
memory-unlocked --version
```

## 2. Create your local store

Choose a local folder and a scope name that belongs only to you:

```bash
export MEMORY_UNLOCKED_HOME="$HOME/.memory-unlocked/student"
export MEMORY_UNLOCKED_BACKEND="sqlite"
export MEMORY_UNLOCKED_TENANT="student-local"
export MEMORY_UNLOCKED_PROJECT="course-project"

memory-unlocked --backend sqlite --path "$MEMORY_UNLOCKED_HOME" init
memory-unlocked --backend sqlite --path "$MEMORY_UNLOCKED_HOME" doctor \
  --tenant "$MEMORY_UNLOCKED_TENANT" \
  --project "$MEMORY_UNLOCKED_PROJECT"
```

A new installation must report `memories: 0`.

## 3. Connect the MCP server

Configure your MCP client to launch this local command:

```text
memory-unlocked-mcp
```

Bind these environment variables in the MCP client configuration:

```text
MEMORY_UNLOCKED_HOME=<your local store folder>
MEMORY_UNLOCKED_BACKEND=sqlite
MEMORY_UNLOCKED_TENANT=student-local
MEMORY_UNLOCKED_PROJECT=course-project
```

The tenant and project are fixed by the process. The model cannot change them through a tool call.

## 4. Verify isolation

After connecting, call `memory_stats`. It must return zero on a new installation. Write one harmless test memory, then confirm it can be recalled only from the same tenant/project.

Your store is independent:

```text
Your AI client
    -> your local Memory Unlocked MCP
        -> your local SQLite file
```

There is no route to the instructor's memory or to other students. Other students cannot read your memories, and you cannot read theirs.

## 5. Backup, restore, and delete

Export your own data:

```bash
memory-unlocked --backend sqlite --path "$MEMORY_UNLOCKED_HOME" export \
  --tenant "$MEMORY_UNLOCKED_TENANT" \
  --project "$MEMORY_UNLOCKED_PROJECT" \
  --out memory-backup.json
```

Restore into a different empty folder:

```bash
memory-unlocked --backend sqlite --path "$HOME/.memory-unlocked/restored" import \
  --in memory-backup.json
```

To remove everything, disconnect the MCP server and delete only the local folder you selected in `MEMORY_UNLOCKED_HOME`.

## Privacy rules

Do not store passwords, API keys, private tokens, personal contact data, raw customer records, or full private conversations. Memory Unlocked rejects common secret shapes, but the student remains responsible for deciding what should become durable memory.
