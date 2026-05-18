#!/usr/bin/env python3
"""Tests for lib.approve_nonce_cli (harness approve-nonce mint)."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import approve_nonce_cli
from lib import approval_nonce


def _make_args(audience: str = "phase.approve", ttl: int = 120) -> argparse.Namespace:
    return argparse.Namespace(audience=audience, ttl=ttl)


class TestRunMintHappyPath(unittest.TestCase):
    """Happy-path: TTY mock + custom nonce_dir."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.nonce_dir = Path(self._tmp.name) / "nonces"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_exit_0_and_stdout(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"HARNESS_TEST_FORCE_TTY": "1"}):
            rc = approve_nonce_cli.run_mint(
                _make_args(audience="phase.approve", ttl=120),
                nonce_dir=self.nonce_dir,
                stdout=stdout,
                stderr=stderr,
            )
        self.assertEqual(rc, 0, msg=f"stderr={stderr.getvalue()!r}")
        out = stdout.getvalue()
        self.assertIn("nonce_id=", out)
        self.assertIn("audience=phase.approve", out)
        self.assertIn("expires_in_s=120", out)

    def test_nonce_file_exists_with_correct_audience(self) -> None:
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {"HARNESS_TEST_FORCE_TTY": "1"}):
            rc = approve_nonce_cli.run_mint(
                _make_args(audience="phase.autopilot.start", ttl=60),
                nonce_dir=self.nonce_dir,
                stdout=stdout,
                stderr=io.StringIO(),
            )
        self.assertEqual(rc, 0)
        nonce_files = list(self.nonce_dir.glob("*.json"))
        self.assertEqual(len(nonce_files), 1, msg="Expected exactly one nonce file")
        body = json.loads(nonce_files[0].read_text(encoding="utf-8"))
        self.assertEqual(body["audience"], "phase.autopilot.start")

    def test_audit_row_has_minter_tty_kind_not_raw_tty(self) -> None:
        """Audit row must carry minter_tty_kind and NOT the raw tty path."""
        tmp_audit = Path(self._tmp.name) / "audit" / "audit.log"
        tmp_audit.parent.mkdir(parents=True, exist_ok=True)
        stdout = io.StringIO()
        # Patch audit_append to capture what gets written.
        captured: list[dict] = []

        def fake_audit_append(entry: dict, *, audit_path: Path) -> int:
            captured.append(dict(entry))
            return 0

        with mock.patch.dict(os.environ, {"HARNESS_TEST_FORCE_TTY": "1"}), \
             mock.patch.object(approve_nonce_cli._audit, "audit_append", side_effect=fake_audit_append):
            approve_nonce_cli.run_mint(
                _make_args(audience="phase.approve"),
                nonce_dir=self.nonce_dir,
                stdout=stdout,
                stderr=io.StringIO(),
            )

        self.assertEqual(len(captured), 1)
        row = captured[0]
        self.assertIn("minter_tty_kind", row)
        self.assertNotIn("minter_tty", row,
                         msg="Raw tty path must NOT appear in the audit row")
        self.assertIn(row["minter_tty_kind"],
                      {"posix-real", "posix-fallback", "win-synthetic"})
        self.assertEqual(row["verb"], "approve_nonce.mint")


class TestRunMintNonTtyRefusal(unittest.TestCase):
    """Non-TTY invocations must be refused with exit code 2."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.nonce_dir = Path(self._tmp.name) / "nonces"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_non_tty_exit_2(self) -> None:
        stderr = io.StringIO()
        # HARNESS_TEST_FORCE_TTY is absent/0 and stdin.isatty() returns False.
        env_patch = {k: v for k, v in os.environ.items() if k != "HARNESS_TEST_FORCE_TTY"}
        with mock.patch.dict(os.environ, env_patch, clear=True), \
             mock.patch.object(sys.stdin, "isatty", return_value=False):
            rc = approve_nonce_cli.run_mint(
                _make_args(),
                nonce_dir=self.nonce_dir,
                stdout=io.StringIO(),
                stderr=stderr,
            )
        self.assertEqual(rc, 2)
        self.assertIn("interactive TTY", stderr.getvalue())

    def test_force_tty_env_allows_pass(self) -> None:
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {"HARNESS_TEST_FORCE_TTY": "1"}), \
             mock.patch.object(sys.stdin, "isatty", return_value=False):
            rc = approve_nonce_cli.run_mint(
                _make_args(),
                nonce_dir=self.nonce_dir,
                stdout=stdout,
                stderr=io.StringIO(),
            )
        self.assertEqual(rc, 0, msg="HARNESS_TEST_FORCE_TTY=1 should bypass TTY gate")


class TestRunMintInvalidTtl(unittest.TestCase):
    """TTL range validation (done in harness.py dispatch before run_mint is called;
    but we also test at the argparse level via the harness entry point)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run_harness_mint(self, ttl: int) -> int:
        """Invoke harness.run() with approve-nonce mint and given TTL."""
        import harness
        with mock.patch.dict(os.environ, {"HARNESS_TEST_FORCE_TTY": "1",
                                          "HARNESS_NONCE_DIR": str(Path(self._tmp.name) / "n")}):
            try:
                rc = harness.run(["approve-nonce", "mint",
                                  "--audience", "phase.approve",
                                  "--ttl", str(ttl)])
                return rc
            except SystemExit as exc:
                return int(exc.code) if exc.code is not None else 1

    def test_ttl_minus_one_rejected(self) -> None:
        rc = self._run_harness_mint(-1)
        self.assertEqual(rc, 2, msg=f"Expected exit 2 for ttl=-1, got {rc}")

    def test_ttl_zero_rejected(self) -> None:
        rc = self._run_harness_mint(0)
        self.assertEqual(rc, 2, msg=f"Expected exit 2 for ttl=0, got {rc}")

    def test_ttl_3601_rejected(self) -> None:
        rc = self._run_harness_mint(3601)
        self.assertEqual(rc, 2, msg=f"Expected exit 2 for ttl=3601, got {rc}")

    def test_ttl_1_accepted(self) -> None:
        rc = self._run_harness_mint(1)
        self.assertEqual(rc, 0, msg=f"Expected exit 0 for ttl=1, got {rc}")

    def test_ttl_3600_accepted(self) -> None:
        rc = self._run_harness_mint(3600)
        self.assertEqual(rc, 0, msg=f"Expected exit 0 for ttl=3600, got {rc}")


class TestWindowsSyntheticTtyBranch(unittest.TestCase):
    """Windows synthetic-tty branch tested via patching the internal _resolve_minter_tty helper.

    We cannot patch ``os.name = "nt"`` at the process level on POSIX because
    pathlib would refuse to instantiate WindowsPath objects (raises RuntimeError).
    Instead we patch the helper directly so only the tty-resolution logic runs
    in "nt" mode, while all POSIX file operations still use PosixPath.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.nonce_dir = Path(self._tmp.name) / "nonces"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _win_tty_resolver(self) -> tuple[str, str]:
        """Simulate the Windows branch of _resolve_minter_tty."""
        import secrets as _secrets
        tty_path = f"win:{os.getpid()}:{_secrets.token_hex(4)}"
        return tty_path, "win-synthetic"

    def test_win_synthetic_kind(self) -> None:
        captured: list[dict] = []

        def fake_audit_append(entry: dict, *, audit_path: Path) -> int:
            captured.append(dict(entry))
            return 0

        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {"HARNESS_TEST_FORCE_TTY": "1"}), \
             mock.patch.object(approve_nonce_cli, "_resolve_minter_tty", self._win_tty_resolver), \
             mock.patch.object(approve_nonce_cli._audit, "audit_append", side_effect=fake_audit_append):
            rc = approve_nonce_cli.run_mint(
                _make_args(audience="phase.approve"),
                nonce_dir=self.nonce_dir,
                stdout=stdout,
                stderr=io.StringIO(),
            )

        self.assertEqual(rc, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["minter_tty_kind"], "win-synthetic")

    def test_win_tty_path_starts_with_win(self) -> None:
        """The tty path stored in the nonce file should start with 'win:' on nt."""
        with mock.patch.dict(os.environ, {"HARNESS_TEST_FORCE_TTY": "1"}), \
             mock.patch.object(approve_nonce_cli, "_resolve_minter_tty", self._win_tty_resolver):
            rc = approve_nonce_cli.run_mint(
                _make_args(audience="phase.approve"),
                nonce_dir=self.nonce_dir,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
        self.assertEqual(rc, 0)
        nonce_files = list(self.nonce_dir.glob("*.json"))
        self.assertEqual(len(nonce_files), 1)
        body = json.loads(nonce_files[0].read_text(encoding="utf-8"))
        self.assertTrue(
            body["minter_tty"].startswith("win:"),
            msg=f"Expected minter_tty to start with 'win:', got {body['minter_tty']!r}",
        )


class TestAuditRowContent(unittest.TestCase):
    """Additional check: the nonce_id in the audit row matches the file."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.nonce_dir = Path(self._tmp.name) / "nonces"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_nonce_id_matches_file(self) -> None:
        captured: list[dict] = []

        def fake_audit_append(entry: dict, *, audit_path: Path) -> int:
            captured.append(dict(entry))
            return 0

        with mock.patch.dict(os.environ, {"HARNESS_TEST_FORCE_TTY": "1"}), \
             mock.patch.object(approve_nonce_cli._audit, "audit_append", side_effect=fake_audit_append):
            rc = approve_nonce_cli.run_mint(
                _make_args(audience="phase.approve"),
                nonce_dir=self.nonce_dir,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(rc, 0)
        nonce_files = list(self.nonce_dir.glob("*.json"))
        self.assertEqual(len(nonce_files), 1)
        body = json.loads(nonce_files[0].read_text(encoding="utf-8"))
        self.assertEqual(captured[0]["nonce_id"], body["nonce_id"])


if __name__ == "__main__":
    unittest.main()
