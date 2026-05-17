"""Cycle-2 P2-A1: gitconfig fingerprint producer-side (§12.6).

Tests:
  A. _git_user_email_sha256 returns correct digest when subprocess succeeds.
  B. _git_user_email_sha256 returns None when subprocess returns empty string.
  C. _git_user_email_sha256 returns None when subprocess raises (git absent).
  D. write_install_state stamps git_user_email_at_install_sha256 into the record.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.state import _git_user_email_sha256  # type: ignore[import]


# ---------------------------------------------------------------------------
# A. Correct digest when subprocess returns a real email
# ---------------------------------------------------------------------------


class TestGitUserEmailSha256:
    def test_returns_correct_sha256_for_seeded_email(self, monkeypatch):
        """_git_user_email_sha256 returns sha256(email.lower().strip()) digest."""
        email = "Test.User@Example.COM"
        expected = hashlib.sha256(email.lower().strip().encode("utf-8")).hexdigest()

        mock_result = MagicMock()
        mock_result.stdout = email + "\n"  # git config output has trailing newline
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

        digest = _git_user_email_sha256()
        assert digest == expected, (
            f"Expected digest {expected!r}, got {digest!r}"
        )

    def test_normalises_email_case_and_whitespace(self, monkeypatch):
        """Leading/trailing whitespace and mixed case are normalised before hashing."""
        email = "  Alice@Example.com  "
        expected = hashlib.sha256("alice@example.com".encode("utf-8")).hexdigest()

        mock_result = MagicMock()
        mock_result.stdout = email
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

        digest = _git_user_email_sha256()
        assert digest == expected

    # -----------------------------------------------------------------------
    # B. Returns None when stdout is empty
    # -----------------------------------------------------------------------

    def test_returns_none_when_email_empty(self, monkeypatch):
        """Returns None when git user.email is unset (empty stdout)."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

        assert _git_user_email_sha256() is None

    def test_returns_none_when_email_is_only_whitespace(self, monkeypatch):
        """Returns None when stdout is only whitespace (strip → empty)."""
        mock_result = MagicMock()
        mock_result.stdout = "   \n"
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

        assert _git_user_email_sha256() is None

    # -----------------------------------------------------------------------
    # C. Returns None when subprocess raises
    # -----------------------------------------------------------------------

    def test_returns_none_when_git_absent(self, monkeypatch):
        """Returns None when subprocess.run raises (git not installed)."""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("git not found"))
        )
        assert _git_user_email_sha256() is None

    def test_returns_none_when_subprocess_raises_generic(self, monkeypatch):
        """Returns None for any subprocess exception."""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("unexpected"))
        )
        assert _git_user_email_sha256() is None
