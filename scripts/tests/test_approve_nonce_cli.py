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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import approve_nonce_cli
from lib import approval_nonce


# C-1 (Cycle-2): HARNESS_TEST_FORCE_TTY removed from production code.
# Tests now monkeypatch sys.stdin.isatty directly.
_MOCK_TTY = mock.patch.object(sys.stdin, "isatty", return_value=True)


def _make_args(audience: str = "release.publish", ttl: int = 120) -> argparse.Namespace:
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
        with mock.patch.object(sys.stdin, "isatty", return_value=True):
            rc = approve_nonce_cli.run_mint(
                _make_args(audience="release.publish", ttl=120),
                nonce_dir=self.nonce_dir,
                stdout=stdout,
                stderr=stderr,
            )
        self.assertEqual(rc, 0, msg=f"stderr={stderr.getvalue()!r}")
        out = stdout.getvalue()
        self.assertIn("nonce_id=", out)
        self.assertIn("audience=release.publish", out)
        self.assertIn("expires_in_s=120", out)

    def test_nonce_file_exists_with_correct_audience(self) -> None:
        stdout = io.StringIO()
        with mock.patch.object(sys.stdin, "isatty", return_value=True):
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

        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
             mock.patch.object(approve_nonce_cli._audit, "audit_append", side_effect=fake_audit_append):
            approve_nonce_cli.run_mint(
                _make_args(audience="release.publish"),
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
        """Non-TTY stdin is refused with exit 2 — C-1 (Cycle-2): env vars no longer bypass."""
        stderr = io.StringIO()
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            rc = approve_nonce_cli.run_mint(
                _make_args(),
                nonce_dir=self.nonce_dir,
                stdout=io.StringIO(),
                stderr=stderr,
            )
        self.assertEqual(rc, 2)
        self.assertIn("interactive TTY", stderr.getvalue())

    def test_harness_test_force_tty_env_no_longer_bypasses(self) -> None:
        """C-1 (Cycle-2): HARNESS_TEST_FORCE_TTY env var no longer bypasses TTY gate."""
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"HARNESS_TEST_FORCE_TTY": "1", "HARNESS_DEV_BUILD": "1"}), \
             mock.patch.object(sys.stdin, "isatty", return_value=False):
            rc = approve_nonce_cli.run_mint(
                _make_args(),
                nonce_dir=self.nonce_dir,
                stdout=io.StringIO(),
                stderr=stderr,
            )
        # With C-1, env vars have no effect — only sys.stdin.isatty() matters.
        self.assertEqual(rc, 2, msg="HARNESS_TEST_FORCE_TTY env var must no longer bypass TTY gate")

    def test_real_isatty_true_allows_pass(self) -> None:
        """sys.stdin.isatty()=True allows the mint to proceed."""
        stdout = io.StringIO()
        with mock.patch.object(sys.stdin, "isatty", return_value=True):
            rc = approve_nonce_cli.run_mint(
                _make_args(),
                nonce_dir=self.nonce_dir,
                stdout=stdout,
                stderr=io.StringIO(),
            )
        self.assertEqual(rc, 0, msg="isatty=True should allow mint to proceed")


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
        # C-1 (Cycle-2): mock sys.stdin.isatty instead of HARNESS_TEST_FORCE_TTY.
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
             mock.patch.dict(os.environ, {"HARNESS_NONCE_DIR": str(Path(self._tmp.name) / "n")}):
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


class TestRunMintTtlDirectValidation(unittest.TestCase):
    """Fix 4: run_mint self-validates TTL even when called directly (bypasses argparse)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.nonce_dir = Path(self._tmp.name) / "nonces"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_ttl_zero_direct_call_exit_2(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(sys.stdin, "isatty", return_value=True):
            rc = approve_nonce_cli.run_mint(
                _make_args(ttl=0),
                nonce_dir=self.nonce_dir,
                stdout=io.StringIO(),
                stderr=stderr,
            )
        self.assertEqual(rc, 2, msg=f"Expected exit 2 for ttl=0 direct call, got {rc}")
        self.assertIn("--ttl", stderr.getvalue())

    def test_ttl_too_large_direct_call_exit_2(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(sys.stdin, "isatty", return_value=True):
            rc = approve_nonce_cli.run_mint(
                _make_args(ttl=10**9),
                nonce_dir=self.nonce_dir,
                stdout=io.StringIO(),
                stderr=stderr,
            )
        self.assertEqual(rc, 2, msg=f"Expected exit 2 for ttl=10**9 direct call, got {rc}")
        self.assertIn("--ttl", stderr.getvalue())


class TestRunMintAudienceValidation(unittest.TestCase):
    """Fix 5: audience must match [a-z][a-z0-9._]{0,63}."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.nonce_dir = Path(self._tmp.name) / "nonces"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _mint(self, audience: str) -> tuple[int, str]:
        stderr = io.StringIO()
        with mock.patch.object(sys.stdin, "isatty", return_value=True):
            rc = approve_nonce_cli.run_mint(
                _make_args(audience=audience),
                nonce_dir=self.nonce_dir,
                stdout=io.StringIO(),
                stderr=stderr,
            )
        return rc, stderr.getvalue()

    def test_valid_audience_accepted(self) -> None:
        rc, _ = self._mint("phase.approve")
        self.assertEqual(rc, 0)

    def test_audience_uppercase_rejected(self) -> None:
        rc, err = self._mint("Phase.Approve")
        self.assertEqual(rc, 2)
        self.assertIn("--audience", err)

    def test_audience_starts_with_digit_rejected(self) -> None:
        rc, err = self._mint("1phase")
        self.assertEqual(rc, 2)
        self.assertIn("--audience", err)

    def test_audience_too_long_rejected(self) -> None:
        # 65-char audience (1 + 64 additional) exceeds [0,63] for the suffix part.
        long_aud = "a" + "b" * 64
        rc, err = self._mint(long_aud)
        self.assertEqual(rc, 2)
        self.assertIn("--audience", err)

    def test_audience_special_chars_rejected(self) -> None:
        rc, err = self._mint("phase approve")
        self.assertEqual(rc, 2)
        self.assertIn("--audience", err)


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
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
             mock.patch.object(approve_nonce_cli, "_resolve_minter_tty", self._win_tty_resolver), \
             mock.patch.object(approve_nonce_cli._audit, "audit_append", side_effect=fake_audit_append):
            rc = approve_nonce_cli.run_mint(
                _make_args(audience="release.publish"),
                nonce_dir=self.nonce_dir,
                stdout=stdout,
                stderr=io.StringIO(),
            )

        self.assertEqual(rc, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["minter_tty_kind"], "win-synthetic")

    def test_win_tty_path_starts_with_win(self) -> None:
        """The tty path stored in the nonce file should start with 'win:' on nt."""
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
             mock.patch.object(approve_nonce_cli, "_resolve_minter_tty", self._win_tty_resolver):
            rc = approve_nonce_cli.run_mint(
                _make_args(audience="release.publish"),
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

        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
             mock.patch.object(approve_nonce_cli._audit, "audit_append", side_effect=fake_audit_append):
            rc = approve_nonce_cli.run_mint(
                _make_args(audience="release.publish"),
                nonce_dir=self.nonce_dir,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(rc, 0)
        nonce_files = list(self.nonce_dir.glob("*.json"))
        self.assertEqual(len(nonce_files), 1)
        body = json.loads(nonce_files[0].read_text(encoding="utf-8"))
        self.assertEqual(captured[0]["nonce_id"], body["nonce_id"])


class TestMintConsumeRoundTrip(unittest.TestCase):
    """Fix 6: end-to-end round-trip test pinning cross-module contract."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.nonce_dir = Path(self._tmp.name) / "nonces"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_mint_then_consume_different_tty(self) -> None:
        """Mint a nonce via run_mint, then consume it with a different consumer_tty."""
        # Use a shared secret key so both sides agree.
        import secrets as _secrets
        key = _secrets.token_bytes(32)

        stdout = io.StringIO()
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
             mock.patch.object(approve_nonce_cli, "_resolve_minter_tty",
                               return_value=("posix:/dev/pts/99", "posix-real")), \
             mock.patch.object(approval_nonce, "_load_or_create_secret_key", return_value=key):
            rc = approve_nonce_cli.run_mint(
                _make_args(audience="release.publish", ttl=120),
                nonce_dir=self.nonce_dir,
                stdout=stdout,
                stderr=io.StringIO(),
            )
        self.assertEqual(rc, 0, msg="mint should succeed")

        # Extract nonce_id from stdout.
        out = stdout.getvalue()
        nonce_id_part = [p for p in out.split() if p.startswith("nonce_id=")]
        self.assertEqual(len(nonce_id_part), 1, msg=f"Unexpected stdout: {out!r}")
        minted_nonce_id = nonce_id_part[0].split("=", 1)[1]

        # Consume with a different consumer_tty.
        result = approval_nonce.consume_newest_valid(
            self.nonce_dir,
            audience="release.publish",
            consumer_tty="/dev/pts/42",
            secret_key=key,
        )
        self.assertEqual(result.outcome, "consumed",
                         msg=f"Expected consumed, got {result.outcome!r}")
        self.assertIsNotNone(result.nonce)
        self.assertEqual(result.nonce.nonce_id, minted_nonce_id,
                         msg="Consumed nonce_id must match minted nonce_id")


class TestLoadOrCreateSecretKeyAudit(unittest.TestCase):
    """A-2 (Cycle-2): corrupt key rotation emits audit.secret_key.rotated row."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.key_dir = Path(self._tmp.name) / "harness"
        self.key_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_corrupt_key_creates_fresh_key(self) -> None:
        """Write a corrupt (wrong-length) key, call _load_or_create_secret_key,
        then assert a fresh 32-byte key is returned and old content is gone."""
        secret_path = self.key_dir / "secret.key"
        secret_path.write_bytes(b"tooshort")

        audit_path = self.key_dir / "audit.log"
        # Capture emit call without recursion by patching at the boundary.
        emitted: list[dict] = []

        def _fake_emit(*, backup_path, reason, audit_path=None):
            emitted.append({"backup_path": backup_path, "reason": reason})

        with mock.patch.object(approval_nonce, "_emit_secret_key_rotated_audit",
                               side_effect=_fake_emit):
            key = approval_nonce._load_or_create_secret_key(
                secret_path, audit_path=audit_path
            )

        self.assertEqual(len(key), 32, msg="Should return a fresh 32-byte key")
        self.assertEqual(len(emitted), 1, msg="Exactly one emit call expected")
        self.assertIn(emitted[0]["reason"], ("corrupt_length", "corrupt_unreadable"))

    def test_corrupt_key_audit_row_has_correct_verb(self) -> None:
        """Audit row emitted for corrupt key must have verb=audit.secret_key.rotated."""
        secret_path = self.key_dir / "secret.key2"
        secret_path.write_bytes(b"x" * 10)  # corrupt

        audit_path = self.key_dir / "audit2.log"
        captured: list[dict] = []

        from lib import audit as _audit_mod

        def fake_audit_append(entry: dict, *, audit_path: Path) -> int:
            captured.append(dict(entry))
            return 0

        with mock.patch.object(_audit_mod, "audit_append", side_effect=fake_audit_append):
            approval_nonce._load_or_create_secret_key(
                secret_path, audit_path=audit_path
            )

        verbs = [e.get("verb") for e in captured]
        self.assertIn("audit.secret_key.rotated", verbs,
                      msg=f"Expected audit.secret_key.rotated in {verbs!r}")
        rot_rows = [e for e in captured if e.get("verb") == "audit.secret_key.rotated"]
        self.assertTrue(rot_rows)
        row = rot_rows[0]
        self.assertIn(row.get("reason"), ("corrupt_length", "corrupt_unreadable"),
                      msg=f"Unexpected reason: {row.get('reason')!r}")
        self.assertIn("backup_path", row)

    def test_valid_key_no_audit_row(self) -> None:
        """No audit row emitted when key is already valid."""
        import secrets as _sec
        secret_path = self.key_dir / "secret.valid"
        secret_path.write_bytes(_sec.token_bytes(32))
        secret_path.chmod(0o600)

        audit_path = self.key_dir / "audit_valid.log"
        emitted: list[dict] = []

        def _fake_emit(*, backup_path, reason, audit_path=None):
            emitted.append({"reason": reason})

        with mock.patch.object(approval_nonce, "_emit_secret_key_rotated_audit",
                               side_effect=_fake_emit):
            key = approval_nonce._load_or_create_secret_key(
                secret_path, audit_path=audit_path
            )

        self.assertEqual(len(key), 32)
        self.assertEqual(emitted, [], msg="No rotation emit for valid key")


if __name__ == "__main__":
    unittest.main()
