"""Shared fixtures for the test suite."""

import itertools

import pytest

from memory_unlocked import MemoryStore


@pytest.fixture
def store():
    """A fresh store with a deterministic, monotonic clock (no wall-clock)."""
    counter = itertools.count(0)

    def clock() -> str:
        n = next(counter)
        return f"2026-01-01T00:00:{n:02d}Z"

    return MemoryStore(clock=clock)
