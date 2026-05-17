"""Test fixtures for the audit-tip anchor suite.

Each test gets an isolated `~/.harness` directory under a tempdir so that
secret-key minting + anchor writes never touch the real user's home.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make scripts/ importable as a package root (the harness scripts use
# ``from lib.X import ...`` style imports; the layout matches scripts/harness.py).
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Redirect the harness home dir into *tmp_path*."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    # Force the module to recompute home_dir lazily; modules read os.environ
    # on every call to home_dir, so no reload is needed. Yield the path so
    # tests can inspect it.
    yield home


@pytest.fixture
def repo_root(tmp_path):
    """Provide a throwaway repo root for anchor binding."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".harness").mkdir()
    (root / ".scratch").mkdir()
    return root
