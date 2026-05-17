"""
Shared fixtures for tests/safe_open/.
"""
import os
import tempfile
import pytest


@pytest.fixture
def anchor_dir(tmp_path):
    """A real, non-symlinked directory to use as anchor."""
    d = tmp_path / "anchor"
    d.mkdir()
    return d


@pytest.fixture
def symlinked_anchor(tmp_path):
    """A symlink that points to a real directory — anchor is itself a symlink."""
    real_dir = tmp_path / "real_anchor"
    real_dir.mkdir()
    link = tmp_path / "link_anchor"
    link.symlink_to(real_dir)
    return link
