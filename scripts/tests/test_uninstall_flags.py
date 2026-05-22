#!/usr/bin/env python3
"""Uninstall flag split: --remove-state/--remove-operational/--remove-install-state/--remove-all (T0-3 amendment #10)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
UNINSTALL = REPO / "scripts" / "uninstall_harness.py"


def run(args, cwd):
    return subprocess.run(
        [sys.executable, str(UNINSTALL), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _seed_target(tmp: Path) -> None:
    (tmp / ".scratch").mkdir()
    (tmp / ".harness").mkdir()
    (tmp / ".harness" / "backups").mkdir()
    (tmp / ".scratch" / "phase-state.json").write_text("{}")
    (tmp / ".harness" / "audit.log").write_text("{}\n")
    (tmp / ".harness" / "session.lock").write_text("{}")
    (tmp / ".harness" / "backups" / "x.bak").write_text("x")
    (tmp / ".harness" / "installed-manifest.json").write_text(
        json.dumps({"version": "0.0.0", "files": {}})
    )


class UninstallFlagSplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        _seed_target(self.tmp)

    def test_remove_state_only(self) -> None:
        r = run(["--target", str(self.tmp), "--remove-state"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.tmp / ".scratch" / "phase-state.json").exists())
        self.assertTrue((self.tmp / ".harness" / "audit.log").exists())
        self.assertTrue((self.tmp / ".harness" / "installed-manifest.json").exists())

    def test_remove_operational_only(self) -> None:
        r = run(["--target", str(self.tmp), "--remove-operational"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.tmp / ".harness" / "audit.log").exists())
        self.assertFalse((self.tmp / ".harness" / "session.lock").exists())
        self.assertFalse((self.tmp / ".harness" / "backups").exists())
        self.assertTrue((self.tmp / ".scratch" / "phase-state.json").exists())
        self.assertTrue((self.tmp / ".harness" / "installed-manifest.json").exists())

    def test_remove_install_state_only_standalone(self) -> None:
        r = run(
            ["--target", str(self.tmp), "--remove-install-state-only"],
            cwd=self.tmp,
        )
        # Backward-compat flag name `--remove-install-state` collides with the
        # pre-existing flag tied to --select. The new T0-3 flag is exposed
        # under a distinct name documented in the help text.
        # We test the standalone removal via --remove-all here; legacy flag
        # behaviour preserved by other tests.
        # (This test asserts the new --remove-install-state-only flag works
        # without requiring a --select.)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.tmp / ".harness" / "installed-manifest.json").exists())

    def test_remove_all(self) -> None:
        r = run(["--target", str(self.tmp), "--remove-all"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.tmp / ".scratch" / "phase-state.json").exists())
        self.assertFalse((self.tmp / ".harness" / "audit.log").exists())
        self.assertFalse((self.tmp / ".harness" / "session.lock").exists())
        self.assertFalse((self.tmp / ".harness" / "backups").exists())
        self.assertFalse((self.tmp / ".harness" / "installed-manifest.json").exists())

    def test_remove_all_idempotent_on_missing_paths(self) -> None:
        # Wipe everything first.
        run(["--target", str(self.tmp), "--remove-all"], cwd=self.tmp)
        r = run(["--target", str(self.tmp), "--remove-all"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
