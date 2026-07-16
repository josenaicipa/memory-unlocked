"""Public v1 release contract."""

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
