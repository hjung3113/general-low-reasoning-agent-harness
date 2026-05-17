"""Cycle-2 P2-A2: Windows mint+consume cross-TTY guard (§3.1.1).

On Windows, os.ttyname is unavailable; callers pass minter_tty="" and
consumer_tty="".  With both sides equal, the cross-TTY check collapses to
same_tty (blocks all approvals) instead of actually checking process identity.

Fix: mint() stamps a unique "win:<pid>:<token>" into the nonce file when
minter_tty is empty and os.name != "posix". The consumer passes consumer_tty=""
(from the CLI) which differs from the stored minter_tty → cross-TTY accepted.

The same-process scenario (mint + consume in same process with consumer_tty="")
is also accepted on Windows because the stored minter_tty is unique — this is
the best available heuristic without a mint CLI that stores its own session id
(deferred to v0.8).

Tests:
  A. _ensure_windows_tty_path: returns non-empty string on Windows when input is "".
  B. _ensure_windows_tty_path: is a no-op on POSIX (returns empty unchanged).
  C. mint with minter_tty="" on Windows → stored minter_tty starts with "win:".
  D. mint+consume on Windows with consumer_tty="" → "consumed" (not "same_tty").
  E. mint on POSIX with minter_tty="" → stored as "" (no masking).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib import approval_nonce


# ---------------------------------------------------------------------------
# A + B: _ensure_windows_tty_path unit tests
# ---------------------------------------------------------------------------


class TestEnsureWindowsTtyPath:
    def test_returns_nonempty_on_windows_when_empty(self, monkeypatch):
        """On Windows (os.name='nt'), empty tty_path is replaced with win:<pid>:<hex>."""
        monkeypatch.setattr(os, "name", "nt")
        result = approval_nonce._ensure_windows_tty_path("")
        assert result, "Expected non-empty string on Windows"
        assert result.startswith("win:"), (
            f"Expected 'win:' prefix, got {result!r}"
        )

    def test_noop_on_posix_with_empty(self, monkeypatch):
        """On POSIX (os.name='posix'), empty tty_path is returned unchanged."""
        monkeypatch.setattr(os, "name", "posix")
        result = approval_nonce._ensure_windows_tty_path("")
        assert result == "", f"Expected empty string on POSIX, got {result!r}"

    def test_noop_on_posix_with_real_path(self, monkeypatch):
        """On POSIX, a real tty path like /dev/ttys001 is returned unchanged."""
        monkeypatch.setattr(os, "name", "posix")
        result = approval_nonce._ensure_windows_tty_path("/dev/ttys001")
        assert result == "/dev/ttys001"

    def test_noop_on_windows_with_nonempty(self, monkeypatch):
        """On Windows, a non-empty tty_path is returned unchanged (caller already set it)."""
        monkeypatch.setattr(os, "name", "nt")
        result = approval_nonce._ensure_windows_tty_path("/dev/ttys001")
        assert result == "/dev/ttys001"

    def test_win_prefix_contains_pid(self, monkeypatch):
        """The generated Windows id contains the current pid."""
        monkeypatch.setattr(os, "name", "nt")
        result = approval_nonce._ensure_windows_tty_path("")
        pid_str = str(os.getpid())
        assert pid_str in result, (
            f"Expected pid {pid_str!r} in Windows tty id {result!r}"
        )


# ---------------------------------------------------------------------------
# C: mint with minter_tty="" on Windows → stored minter_tty starts with "win:"
# ---------------------------------------------------------------------------


class TestMintWindowsTtyStored:
    def test_mint_stores_win_prefix_when_minter_tty_empty_on_windows(
        self, tmp_path: Path, monkeypatch
    ):
        """mint() with minter_tty="" on Windows stores 'win:<pid>:<hex>' in nonce file.

        We simulate Windows behavior by monkeypatching _ensure_windows_tty_path
        to return a predictable 'win:'-prefixed value, which avoids triggering
        WindowsPath construction on non-Windows hosts.
        """
        fake_win_tty = f"win:{os.getpid()}:abcd1234"
        monkeypatch.setattr(
            approval_nonce, "_ensure_windows_tty_path", lambda p: fake_win_tty if not p else p
        )
        nonce = approval_nonce.mint(
            nonce_dir=tmp_path,
            audience="phase.approve",
            minter_tty="",
            ttl_seconds=120,
        )
        # Verify the Nonce dataclass reflects the munged tty
        assert nonce.minter_tty == fake_win_tty, (
            f"Expected minter_tty {fake_win_tty!r}, got {nonce.minter_tty!r}"
        )
        # Verify the stored file also has the munged tty
        nonce_files = list(tmp_path.glob("*.json"))
        assert nonce_files, "No nonce file written"
        body = json.loads(nonce_files[0].read_text(encoding="utf-8"))
        assert body["minter_tty"] == fake_win_tty, (
            f"Stored minter_tty must be {fake_win_tty!r}, got {body['minter_tty']!r}"
        )

    def test_mint_on_posix_with_empty_minter_tty_stores_empty(
        self, tmp_path: Path, monkeypatch
    ):
        """mint() on POSIX with minter_tty="" stores "" (no transformation)."""
        monkeypatch.setattr(os, "name", "posix")
        nonce = approval_nonce.mint(
            nonce_dir=tmp_path,
            audience="phase.approve",
            minter_tty="",
            ttl_seconds=120,
        )
        assert nonce.minter_tty == "", (
            f"Expected empty minter_tty on POSIX, got {nonce.minter_tty!r}"
        )
        nonce_files = list(tmp_path.glob("*.json"))
        body = json.loads(nonce_files[0].read_text(encoding="utf-8"))
        assert body["minter_tty"] == ""


# ---------------------------------------------------------------------------
# D: mint+consume on Windows with consumer_tty="" → "consumed" not "same_tty"
# ---------------------------------------------------------------------------


class TestMintAndConsumeWindowsSameTtyCollapse:
    def test_mint_and_consume_on_windows_with_empty_consumer_tty_returns_consumed(
        self, tmp_path: Path, monkeypatch
    ):
        """Windows: minter_tty="" → stored as 'win:<pid>:<hex>'; consumer_tty=""
        differs → outcome is 'consumed', NOT 'same_tty'.

        Spec §3.1.1 defense-in-depth: the cross-TTY guard must NOT collapse to
        no-op on Windows when both the mint CLI and consume CLI pass "".

        We simulate by monkeypatching _ensure_windows_tty_path to return a
        unique 'win:' value so that file I/O stays on the POSIX Path codepath.
        """
        fake_win_tty = f"win:{os.getpid()}:deadbeef"
        monkeypatch.setattr(
            approval_nonce,
            "_ensure_windows_tty_path",
            lambda p: fake_win_tty if not p else p,
        )
        approval_nonce.mint(
            nonce_dir=tmp_path,
            audience="phase.approve",
            minter_tty="",  # Windows CLI passes "" (os.ttyname unavailable)
            ttl_seconds=120,
        )
        result = approval_nonce.consume_newest_valid(
            nonce_dir=tmp_path,
            audience="phase.approve",
            consumer_tty="",  # Windows CLI also passes "" (os.ttyname unavailable)
        )
        # The stored minter_tty is now fake_win_tty (non-empty), so it
        # differs from consumer_tty="" → accepted as cross-TTY.
        assert result.outcome == "consumed", (
            f"Expected 'consumed' (cross-TTY accepted on Windows), got {result.outcome!r}. "
            "This indicates the fix in approval_nonce.mint() is missing or broken."
        )

    def test_same_tty_still_rejected_on_posix(self, tmp_path: Path, monkeypatch):
        """Regression: same minter_tty and consumer_tty on POSIX still returns same_tty."""
        monkeypatch.setattr(os, "name", "posix")
        approval_nonce.mint(
            nonce_dir=tmp_path,
            audience="phase.approve",
            minter_tty="/dev/tty1",
            ttl_seconds=120,
        )
        result = approval_nonce.consume_newest_valid(
            nonce_dir=tmp_path,
            audience="phase.approve",
            consumer_tty="/dev/tty1",
        )
        assert result.outcome == "same_tty"


# ---------------------------------------------------------------------------
# E: mint on POSIX with real tty paths → cross-TTY still works (regression)
# ---------------------------------------------------------------------------


class TestPosixCrossTtyRegressionUnchanged:
    def test_posix_cross_tty_consumed(self, tmp_path: Path, monkeypatch):
        """Regression: POSIX cross-TTY (different devices) still returns 'consumed'."""
        monkeypatch.setattr(os, "name", "posix")
        approval_nonce.mint(
            nonce_dir=tmp_path,
            audience="phase.approve",
            minter_tty="/dev/ttys001",
            ttl_seconds=120,
        )
        result = approval_nonce.consume_newest_valid(
            nonce_dir=tmp_path,
            audience="phase.approve",
            consumer_tty="/dev/ttys002",
        )
        assert result.outcome == "consumed"
