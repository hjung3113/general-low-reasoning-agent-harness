"""Tests for upgrade.py wiring of SSH trust root (§6, Group δ).

Mocks verify_release_tag and file_sha256_at_commit so no real SSH keys needed.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

# Adjust sys.path so `lib.*` imports work when run from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.release_trust import UpgradeTrustError
from lib.exitcodes import EXIT_RELEASE_TRUST_INVALID


def _make_entry(path: str = "harness/manifest.json", policy: str = "harness-owned"):
    """Create a minimal manifest entry-like object."""
    class _Entry:
        def __init__(self, p: str, pol: str) -> None:
            self.path = Path(p)
            self.policy = pol
            self.owner = "harness"
    return _Entry(path, policy)


def _call_build(
    *,
    entries=None,
    harness_version: str = "0.7.0",
    root: Path,
    target: Path | None = None,
    env: dict[str, str] | None = None,
):
    """Import and call _build_release_manifest_v2 with optional env override."""
    # Re-import to get fresh module state
    import importlib
    import lib.upgrade as _upg
    importlib.reload(_upg)

    if entries is None:
        entries = []

    _env = dict(os.environ)
    if env:
        _env.update(env)

    with patch.dict(os.environ, _env, clear=True):
        return _upg._build_release_manifest_v2(
            root=root,
            entries=entries,
            harness_version=harness_version,
            target=target,
        )


class TestBuildReleaseManifestV2Trust(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name) / "source"
        self._root.mkdir()
        self._target = Path(self._tmp.name) / "target"
        self._target.mkdir()
        # Create a docs/trust/allowed-signers placeholder so the module path resolves
        (self._root / "docs" / "trust").mkdir(parents=True)
        (self._root / "docs" / "trust" / "allowed-signers").write_text(
            "# placeholder\n"
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ── Test 1: signed-tag happy path ────────────────────────────────────────

    def test_signed_tag_manifest_has_correct_fields(self) -> None:
        """On verified SSH tag: manifest has trust_origin=signed_tag and release_commit."""
        fake_sha = "abc123def456" * 3 + "abcd"

        def _fake_verify(repo_root, tag):
            return fake_sha

        def _fake_file_sha(repo_root, commit_sha, path):
            return "deadbeef" * 8

        entry = _make_entry("scripts/lib/upgrade.py")

        with (
            patch("lib.release_trust.verify_release_tag", side_effect=_fake_verify),
            patch("lib.release_trust.file_sha256_at_commit", side_effect=_fake_file_sha),
        ):
            manifest = _call_build(
                entries=[entry],
                harness_version="0.7.0",
                root=self._root,
                target=self._target,
            )

        self.assertEqual(manifest["trust_origin"], "signed_tag")
        self.assertEqual(manifest["release_tag"], "v0.7.0")
        self.assertEqual(manifest["release_commit"], fake_sha)
        self.assertIn("scripts/lib/upgrade.py", manifest["files"])

    # ── Test 2: env-gated dev bypass ────────────────────────────────────────

    def test_env_gated_dev_bypass_emits_warning_and_dev_unsigned(self) -> None:
        """HARNESS_ALLOW_UNSIGNED_DEV=1 bypasses tag check, sets trust_origin=dev_unsigned."""

        def _fake_verify(repo_root, tag):
            raise UpgradeTrustError("tag_signature_invalid", "no signature")

        # Use exclude-policy entries only so the dev-unsigned working-tree read is skipped.
        entry = _make_entry("scripts/lib/upgrade.py", policy="exclude")

        stderr_buf = StringIO()
        with (
            patch("lib.release_trust.verify_release_tag", side_effect=_fake_verify),
            patch("sys.stderr", stderr_buf),
        ):
            manifest = _call_build(
                entries=[entry],
                harness_version="0.7.0",
                root=self._root,
                target=self._target,
                env={"HARNESS_ALLOW_UNSIGNED_DEV": "1"},
            )

        self.assertEqual(manifest["trust_origin"], "dev_unsigned")
        self.assertIsNone(manifest["release_commit"])
        stderr_out = stderr_buf.getvalue()
        self.assertIn("WARNING", stderr_out)
        self.assertIn("HARNESS_ALLOW_UNSIGNED_DEV", stderr_out)

    # ── Test 3: trust-downgrade refused ─────────────────────────────────────

    def test_trust_downgrade_refused_when_target_already_signed(self) -> None:
        """If target manifest has trust_origin=signed_tag, dev bypass is refused."""
        # Write a fake existing installed manifest with signed_tag trust
        from lib.state import INSTALL_STATE
        installed_path = self._target / INSTALL_STATE
        installed_path.parent.mkdir(parents=True, exist_ok=True)
        installed_path.write_text(json.dumps({"trust_origin": "signed_tag", "schema_version": 2}))

        def _fake_verify(repo_root, tag):
            raise UpgradeTrustError("tag_signature_invalid", "no signature")

        with (
            patch("lib.release_trust.verify_release_tag", side_effect=_fake_verify),
            self.assertRaises(UpgradeTrustError) as ctx,
        ):
            _call_build(
                entries=[],
                harness_version="0.7.0",
                root=self._root,
                target=self._target,
                env={"HARNESS_ALLOW_UNSIGNED_DEV": "1"},
            )

        self.assertEqual(ctx.exception.sub_reason, "trust_downgrade_refused")

    # ── Test 4: no env, no target manifest → SystemExit(17) ──────────────────

    def test_no_env_no_bypass_raises_system_exit_17(self) -> None:
        """Without HARNESS_ALLOW_UNSIGNED_DEV, tag_signature_invalid causes SystemExit(17)."""

        def _fake_verify(repo_root, tag):
            raise UpgradeTrustError("tag_signature_invalid", "no signature")

        with (
            patch("lib.release_trust.verify_release_tag", side_effect=_fake_verify),
        ):
            env_without_bypass = {
                k: v for k, v in os.environ.items()
                if k != "HARNESS_ALLOW_UNSIGNED_DEV"
            }
            with self.assertRaises(SystemExit) as ctx:
                _call_build(
                    entries=[],
                    harness_version="0.7.0",
                    root=self._root,
                    target=self._target,
                    env=env_without_bypass,
                )

        self.assertEqual(ctx.exception.code, EXIT_RELEASE_TRUST_INVALID)

    # ── Test 5: dev version is always dev_unsigned ───────────────────────────

    def test_dev_version_skips_verification(self) -> None:
        """Dev versions (0.0.0-dev+...) skip verification entirely."""
        with patch("lib.release_trust.verify_release_tag") as mock_verify:
            manifest = _call_build(
                entries=[],
                harness_version="0.0.0-dev+abc123",
                root=self._root,
                target=self._target,
            )
            mock_verify.assert_not_called()

        self.assertEqual(manifest["trust_origin"], "dev_unsigned")
        self.assertIsNone(manifest["release_tag"])
        self.assertIsNone(manifest["release_commit"])


if __name__ == "__main__":
    unittest.main()
