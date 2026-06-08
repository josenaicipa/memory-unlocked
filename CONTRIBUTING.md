# Contributing

Thanks for improving Memory Unlocked.

## Local setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

## Rules

1. Never commit `.env`, credentials, tokens, private customer data, internal domains, or realistic-looking secrets.
2. Add tests for policy, namespace isolation, persistence, and CLI/MCP behavior when touching those areas.
3. Keep core dependencies minimal; stdlib is preferred.
4. Public docs must use placeholders like `acme`, `billing`, `MEMORY_UNLOCKED_HOME`, and `[REDACTED]`.
5. Do not add telemetry or network calls to the core package without a clear opt-in.

## Pull request checklist

- [ ] `python -m pytest -q` passes
- [ ] `python -m compileall -q memory_unlocked` passes
- [ ] examples still use fake/public data only
- [ ] no generated caches or build artifacts committed
- [ ] changelog updated for user-visible changes
