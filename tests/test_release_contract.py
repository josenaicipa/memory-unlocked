"""Public v1 release contract."""

import re
from pathlib import Path

import memory_unlocked


ROOT = Path(__file__).resolve().parents[1]


def test_v1_version_is_consistent():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert memory_unlocked.__version__ == "1.0.0"
    assert 'version = "1.0.0"' in pyproject


def test_student_quickstart_states_local_isolation_and_zero_initial_memories():
    guide = (ROOT / "docs" / "student-quickstart.md").read_text(encoding="utf-8").lower()
    assert "0 memories" in guide
    assert "local" in guide
    assert "other students" in guide
    assert "memory-unlocked doctor" in guide


def test_github_actions_are_pinned_to_full_commit_shas():
    workflow_dir = ROOT / ".github" / "workflows"
    for workflow in workflow_dir.glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        action_refs = re.findall(r"uses:\s+([^\s#]+)", text)
        assert action_refs, workflow
        for ref in action_refs:
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref), (workflow, ref)


def test_publish_job_receives_only_python_distributions():
    publish = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    pypi_job = publish.split("  publish-pypi:", 1)[1]

    assert "sha256sum dist/*.whl dist/*.tar.gz > SHA256SUMS.txt" in publish
    assert "dist/SHA256SUMS.txt" not in publish
    assert "packages-dir: dist/" in pypi_job
    assert "actions/checkout@" not in pypi_job
    assert "pip install" not in pypi_job
    assert publish.count("id-token: write") == 1
    assert publish.count("contents: write") == 1
