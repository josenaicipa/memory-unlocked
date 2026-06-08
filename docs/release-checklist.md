# Release Checklist

Use this before publishing a public release.

1. Update `memory_unlocked/__init__.py` and `pyproject.toml` versions.
2. Update `CHANGELOG.md` with user-visible changes.
3. Run:

```bash
python -m pip install build twine
python -m pytest -q
python -m compileall -q memory_unlocked
python -m build
```

4. Run a public-safety sweep:

```bash
git grep -nE '(AKIA|gh[pousr]_|xox[baprs]-|sk-[A-Za-z0-9]{20,}|BEGIN .*PRIVATE KEY|Bearer [A-Za-z0-9._~+/-]{20,})' -- . ':!tests'
```

5. Verify CLI smoke:

```bash
TMP=$(mktemp -d)
memory-unlocked --path "$TMP" init
memory-unlocked --path "$TMP" write --tenant acme --project demo --title "Install works" --body "Smoke fact." --source docs/smoke.md
memory-unlocked --path "$TMP" context --tenant acme --project demo --query smoke --token-budget 120
```

6. Tag and publish:

```bash
git tag vX.Y.Z
git push origin main --tags
python -m twine upload dist/*
```

Use TestPyPI first for new packaging changes.
