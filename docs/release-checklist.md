# Release Checklist

Use this before publishing a public release.

## 1. Version and release notes

- Update `memory_unlocked/__init__.py` and `pyproject.toml` to the same version.
- Update `CHANGELOG.md`.
- Confirm the release tag will point to the exact reviewed commit.

## 2. Clean verification

```bash
uv run --isolated --with pytest python -m pytest -q
python -m compileall -q memory_unlocked scripts
rm -rf dist build *.egg-info
uv run --with build --with twine python -m build
uv run --with twine twine check dist/*
```

Install the wheel into a fresh environment and run the exact student smoke:

```bash
python -m venv /tmp/memory-unlocked-release
/tmp/memory-unlocked-release/bin/python -m pip install dist/*.whl
PATH="/tmp/memory-unlocked-release/bin:$PATH" python scripts/smoke_release.py
```

The smoke must report version `1.0.0`, current MCP protocol, nine tools, zero initial memories, and zero cross-scope memories.

## 3. Public-safety sweep

Scan all tracked files, the full Git history, and both built artifacts. The gate must find no:

- maintainer/customer identities or private project names;
- private filesystem paths, hostnames, network addresses, or channel/account IDs;
- credentials, tokens, environment files, databases, JSONL memory payloads, or exports;
- release artifact whose embedded version differs from the tag.

Synthetic security fixtures are allowed only inside tests and must not be valid credentials or real private identifiers.

## 4. CI and independent gate

- Open a pull request and wait for every Linux/macOS/Windows CI job.
- Run an independent public-readiness review against the exact diff/commit.
- Resolve all blockers before merging.
- Keep build, GitHub asset upload, and PyPI OIDC publishing in separate jobs.
- Pin every third-party GitHub Action to a full commit SHA.

## 5. Publish

1. Merge the reviewed pull request.
2. Create the signed/annotated `vX.Y.Z` tag on the merge commit.
3. Publish the GitHub release.
4. The release workflow builds, smokes, adds checksums/assets, and publishes to PyPI through trusted publishing.
5. Verify the release workflow and PyPI project page.

## 6. Post-publish student smoke

From a clean environment, install from the real registry—not the checkout or wheel cache:

```bash
uv tool install --no-cache memory-unlocked==X.Y.Z
memory-unlocked --version
```

Run `memory-unlocked doctor`, MCP `initialize`, `tools/list`, and `memory_stats`; confirm the fresh installation starts with zero memories. Only then announce the release to students.
