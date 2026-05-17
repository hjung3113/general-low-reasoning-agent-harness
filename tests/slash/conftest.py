"""Shared pytest fixtures for tests/slash/.

Extracted from per-test-file boilerplate shared by test_roo_fsd_run_phase.py,
test_opencode_fsd_run_phase.py, and test_roo_fsd_run_all.py. S09b (and beyond)
should consume these rather than re-defining REPO_ROOT or the helper fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def read_slash_file(repo_root):
    def _read(relpath: str) -> str:
        return (repo_root / relpath).read_text(encoding="utf-8")
    return _read


@pytest.fixture
def assert_no_forbidden_literals():
    FORBIDDEN = ("--allow-network", "set -eu", "sed ", "awk ", "$(")

    def _check(body: str, exempt: tuple[str, ...] = ()):
        for lit in FORBIDDEN:
            if lit in exempt:
                continue
            assert lit not in body, (
                f"forbidden literal {lit!r} present in slash body"
            )

    return _check
