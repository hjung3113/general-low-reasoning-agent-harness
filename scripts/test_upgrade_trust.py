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
from unittest.mock import MagicMock, patch

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


def _call_build_patched(
    *,
    entries=None,
    harness_version: str = "0.7.0",
    root: Path,
    target: Path | None = None,
    env: dict[str, str] | None = None,
    patch_verify=None,
    patch_file_sha=None,
):
    """Like _call_build but accepts callables for verify/file_sha mocks.

    Patches are applied BEFORE reload so the fresh imports pick up the mocked functions
    (since upgrade.py uses ``from lib.release_trust import verify_release_tag`` which
    binds the name at import/reload time).
    """
    import importlib
    import lib.upgrade as _upg
    import lib.release_trust as _rt

    if entries is None:
        entries = []

    _env = dict(os.environ)
    if env is not None:
        _env = dict(env)

    patches = []
    if patch_verify is not None:
        patches.append(patch.object(_rt, "verify_release_tag", side_effect=patch_verify))
    if patch_file_sha is not None:
        patches.append(patch.object(_rt, "file_sha256_at_commit", side_effect=patch_file_sha))

    # Apply patches first, then reload — so the reload picks up patched refs.
    import contextlib
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        # Reload INSIDE the patch context so from-imports pick up mocked functions.
        importlib.reload(_upg)
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

        # B3-Fix-2: trust_downgrade_refused now raises SystemExit(EXIT_RELEASE_TRUST_INVALID)
        # rather than a bare UpgradeTrustError, so the caller gets a clean exit code.
        with (
            patch("lib.release_trust.verify_release_tag", side_effect=_fake_verify),
            self.assertRaises(SystemExit) as ctx,
        ):
            _call_build(
                entries=[],
                harness_version="0.7.0",
                root=self._root,
                target=self._target,
                env={"HARNESS_ALLOW_UNSIGNED_DEV": "1"},
            )

        self.assertEqual(ctx.exception.code, EXIT_RELEASE_TRUST_INVALID)

    # ── Test 4: no env, no target manifest → SystemExit(15) ──────────────────

    def test_no_env_no_bypass_raises_system_exit_17(self) -> None:
        """Without HARNESS_ALLOW_UNSIGNED_DEV, tag_signature_invalid causes SystemExit(15)."""

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


class TestCorruptedTargetManifest(unittest.TestCase):
    """δ-P1-1: corrupted install-state.json must raise trust error, not bypass downgrade guard."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name) / "source"
        self._root.mkdir()
        self._target = Path(self._tmp.name) / "target"
        self._target.mkdir()
        (self._root / "docs" / "trust").mkdir(parents=True)
        (self._root / "docs" / "trust" / "allowed-signers").write_text("# placeholder\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_install_state(self, content: str | bytes) -> None:
        from lib.state import INSTALL_STATE
        p = self._target / INSTALL_STATE
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")

    def test_corrupted_json_raises_trust_error(self) -> None:
        """install-state.json with invalid JSON raises UpgradeTrustError(target_manifest_corrupted)."""
        self._write_install_state("{not valid json}")
        import lib.upgrade as _upg
        with self.assertRaises(UpgradeTrustError) as ctx:
            _upg._read_target_trust_origin(self._target)
        self.assertEqual(ctx.exception.sub_reason, "target_manifest_corrupted")

    def test_non_object_json_raises_trust_error(self) -> None:
        """install-state.json that is a JSON array (not object) raises target_manifest_corrupted."""
        self._write_install_state("[1, 2, 3]")
        import lib.upgrade as _upg
        with self.assertRaises(UpgradeTrustError) as ctx:
            _upg._read_target_trust_origin(self._target)
        self.assertEqual(ctx.exception.sub_reason, "target_manifest_corrupted")

    def test_absent_file_returns_none(self) -> None:
        """Absent install-state.json returns None (not an error)."""
        import lib.upgrade as _upg
        result = _upg._read_target_trust_origin(self._target)
        self.assertIsNone(result)

    def test_build_release_manifest_propagates_corrupted_manifest(self) -> None:
        """_build_release_manifest_v2 propagates UpgradeTrustError for corrupted manifest."""
        self._write_install_state("{bad json!")

        def _fake_verify(repo_root, tag):
            raise UpgradeTrustError("tag_signature_invalid", "no sig")

        with self.assertRaises(UpgradeTrustError) as ctx:
            _call_build_patched(
                entries=[],
                harness_version="0.7.0",
                root=self._root,
                target=self._target,
                env={"HARNESS_ALLOW_UNSIGNED_DEV": "1"},
                patch_verify=_fake_verify,
            )
        self.assertEqual(ctx.exception.sub_reason, "target_manifest_corrupted")


class TestReleaseTrustAuditVerbs(unittest.TestCase):
    """δ-P1-2: audit rows are emitted for verified / bypassed / refused paths."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name) / "source"
        self._root.mkdir()
        self._target = Path(self._tmp.name) / "target"
        self._target.mkdir()
        (self._root / "docs" / "trust").mkdir(parents=True)
        (self._root / "docs" / "trust" / "allowed-signers").write_text("# placeholder\n")
        # Ensure target .harness dir exists for audit log.
        (self._target / ".harness").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _read_audit_verbs(self) -> list[str]:
        audit_path = self._target / ".harness" / "audit.log"
        if not audit_path.exists():
            return []
        verbs = []
        for line in audit_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                verbs.append(entry.get("verb", ""))
            except json.JSONDecodeError:
                pass
        return verbs

    def _fake_verify_fail(self, repo_root, tag):
        raise UpgradeTrustError("tag_signature_invalid", "no sig")

    def test_verified_emits_audit_row(self) -> None:
        """release.trust.verified is emitted on successful SSH tag verification."""
        fake_sha = "abc123" * 6 + "ab"

        _call_build_patched(
            entries=[],
            harness_version="0.7.0",
            root=self._root,
            target=self._target,
            env={},
            patch_verify=lambda repo_root, tag: fake_sha,
            patch_file_sha=lambda repo_root, commit_sha, path: "dead" * 16,
        )

        verbs = self._read_audit_verbs()
        self.assertIn("release.trust.verified", verbs,
                      f"Expected release.trust.verified in audit; got verbs={verbs}")

    def test_bypassed_emits_audit_row(self) -> None:
        """release.trust.bypassed is emitted when HARNESS_ALLOW_UNSIGNED_DEV bypass taken."""
        _call_build_patched(
            entries=[],
            harness_version="0.7.0",
            root=self._root,
            target=self._target,
            env={"HARNESS_ALLOW_UNSIGNED_DEV": "1", "HARNESS_BYPASS_TTY_CONFIRM": "1"},
            patch_verify=self._fake_verify_fail,
        )

        verbs = self._read_audit_verbs()
        self.assertIn("release.trust.bypassed", verbs,
                      f"Expected release.trust.bypassed in audit; got verbs={verbs}")

    def test_refused_emits_audit_row_on_exit15(self) -> None:
        """release.trust.refused is emitted when bypass denied (no HARNESS_ALLOW_UNSIGNED_DEV)."""
        env_without_bypass = {
            k: v for k, v in os.environ.items()
            if k not in ("HARNESS_ALLOW_UNSIGNED_DEV", "HARNESS_BYPASS_TTY_CONFIRM")
        }

        with self.assertRaises(SystemExit) as ctx:
            _call_build_patched(
                entries=[],
                harness_version="0.7.0",
                root=self._root,
                target=self._target,
                env=env_without_bypass,
                patch_verify=self._fake_verify_fail,
            )
        self.assertEqual(ctx.exception.code, EXIT_RELEASE_TRUST_INVALID)
        verbs = self._read_audit_verbs()
        self.assertIn("release.trust.refused", verbs,
                      f"Expected release.trust.refused in audit; got verbs={verbs}")


class TestBypassTTYConfirm(unittest.TestCase):
    """δ-P1-4: HARNESS_ALLOW_UNSIGNED_DEV bypass requires TTY confirmation when manifest exists."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name) / "source"
        self._root.mkdir()
        self._target = Path(self._tmp.name) / "target"
        self._target.mkdir()
        (self._root / "docs" / "trust").mkdir(parents=True)
        (self._root / "docs" / "trust" / "allowed-signers").write_text("# placeholder\n")
        (self._target / ".harness").mkdir(parents=True, exist_ok=True)
        # Write an existing manifest with dev_unsigned trust (not signed_tag — that's downgrade).
        from lib.state import INSTALL_STATE
        p = self._target / INSTALL_STATE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"trust_origin": "dev_unsigned", "schema_version": 2}))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _fake_verify_fail(self, repo_root, tag):
        raise UpgradeTrustError("tag_signature_invalid", "no sig")

    def _run_build(self, *, monkeypatch_env: dict | None = None):
        env = {"HARNESS_ALLOW_UNSIGNED_DEV": "1"}
        if monkeypatch_env:
            env.update(monkeypatch_env)
        return _call_build_patched(
            entries=[],
            harness_version="0.7.0",
            root=self._root,
            target=self._target,
            env=env,
            patch_verify=self._fake_verify_fail,
        )

    def test_non_tty_stdin_refused(self) -> None:
        """Non-TTY stdin + bypass + existing manifest → SystemExit(15)."""
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = False
        with patch("sys.stdin", fake_stdin):
            with self.assertRaises(SystemExit) as ctx:
                self._run_build()
        self.assertEqual(ctx.exception.code, EXIT_RELEASE_TRUST_INVALID)

    def test_tty_y_answer_allowed(self) -> None:
        """TTY + 'y' answer → bypass allowed, manifest has trust_origin=dev_unsigned."""
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = True
        with (
            patch("sys.stdin", fake_stdin),
            patch("builtins.input", return_value="y"),
        ):
            manifest = self._run_build()
        self.assertEqual(manifest["trust_origin"], "dev_unsigned")

    def test_tty_n_answer_refused(self) -> None:
        """TTY + 'n' answer → SystemExit(15)."""
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = True
        with (
            patch("sys.stdin", fake_stdin),
            patch("builtins.input", return_value="n"),
        ):
            with self.assertRaises(SystemExit) as ctx:
                self._run_build()
        self.assertEqual(ctx.exception.code, EXIT_RELEASE_TRUST_INVALID)

    def test_bypass_tty_confirm_env_skips_prompt(self) -> None:
        """HARNESS_BYPASS_TTY_CONFIRM=1 skips the TTY prompt even on non-TTY stdin."""
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = False
        with patch("sys.stdin", fake_stdin):
            manifest = self._run_build(monkeypatch_env={"HARNESS_BYPASS_TTY_CONFIRM": "1"})
        self.assertEqual(manifest["trust_origin"], "dev_unsigned")


class TestTamperDetectedViaChainHash(unittest.TestCase):
    """B-3 (Cycle-2): round-trip tamper integration test.

    Verifies that B-1 + B-2 together close the trust-field deletion bypass:
    - Chain hash covers trust_origin (B-1).
    - Chain hash is ALWAYS verified when present, regardless of trust fields (B-2).
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._target = Path(self._tmp.name) / "target"
        self._target.mkdir()
        (self._target / ".harness").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_install_state(self, data: dict) -> None:
        from lib.state import INSTALL_STATE
        p = self._target / INSTALL_STATE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")

    def _make_stamped_manifest(self, trust_origin: str = "signed_tag") -> dict:
        """Build and stamp a minimal installed manifest with chain hash covering trust fields."""
        from lib.manifest_reconciler import compute_manifest_hash_chain
        files = {
            "scripts/harness.py": {
                "installed_sha256": "aabbcc" * 10 + "aabb",
                "current_sha256": "aabbcc" * 10 + "aabb",
            }
        }
        chain_manifest: dict = {
            "schema_version": 2,
            "harness_version": "0.7.0",
            "trust_origin": trust_origin,
            "release_tag": "v0.7.0" if trust_origin == "signed_tag" else None,
            "release_commit": "deadbeef" * 8 if trust_origin == "signed_tag" else None,
            "files": files,
            "removed_in_version": [],
        }
        chain_hash = compute_manifest_hash_chain(chain_manifest)
        manifest = dict(chain_manifest)
        manifest["installed_files_chain_hash"] = chain_hash
        return manifest

    def test_valid_manifest_read_succeeds(self) -> None:
        """Round-trip: stamp a manifest with trust fields, read back, assert no error."""
        import lib.upgrade as _upg
        manifest = self._make_stamped_manifest(trust_origin="signed_tag")
        self._write_install_state(manifest)
        result = _upg._read_target_trust_origin(self._target)
        self.assertEqual(result, "signed_tag")

    def test_tamper_trust_origin_detected(self) -> None:
        """B-1+B-2: flipping trust_origin in the manifest raises target_manifest_corrupted."""
        import importlib
        import lib.upgrade as _upg
        importlib.reload(_upg)
        manifest = self._make_stamped_manifest(trust_origin="signed_tag")
        # Tamper: flip trust_origin to dev_unsigned without re-stamping the chain hash.
        manifest["trust_origin"] = "dev_unsigned"
        self._write_install_state(manifest)
        with self.assertRaises(UpgradeTrustError) as ctx:
            _upg._read_target_trust_origin(self._target)
        self.assertEqual(ctx.exception.sub_reason, "target_manifest_corrupted",
                         msg="Tampered trust_origin must be detected via chain hash")

    def test_delete_trust_origin_still_rejected(self) -> None:
        """B-2: deleting trust_origin no longer bypasses chain verification."""
        import importlib
        import lib.upgrade as _upg
        importlib.reload(_upg)
        manifest = self._make_stamped_manifest(trust_origin="signed_tag")
        # Tamper: delete trust fields — old B3-Fix-1 would skip chain verification here.
        del manifest["trust_origin"]
        del manifest["release_tag"]
        del manifest["release_commit"]
        self._write_install_state(manifest)
        with self.assertRaises(UpgradeTrustError) as ctx:
            _upg._read_target_trust_origin(self._target)
        self.assertEqual(ctx.exception.sub_reason, "target_manifest_corrupted",
                         msg="Deleted trust fields must still be rejected via chain hash")

    def test_absent_chain_hash_old_manifest_accepted(self) -> None:
        """Backward compat: old v1 manifest without chain hash is accepted (returns trust_origin)."""
        import importlib
        import lib.upgrade as _upg
        importlib.reload(_upg)
        # Old manifest: has trust_origin but no chain hash.
        old_manifest = {
            "schema_version": 1,
            "harness_version": "0.6.0",
            "trust_origin": "signed_tag",
        }
        self._write_install_state(old_manifest)
        result = _upg._read_target_trust_origin(self._target)
        self.assertEqual(result, "signed_tag",
                         msg="Old v1 manifests without chain hash must be accepted")


if __name__ == "__main__":
    unittest.main()
