"""S12 — installed-manifest v2 + reconciler tests (§6, §6.1).

Tests cover:
- MANIFEST_SCHEMA_VERSION == 2 constant
- write_manifest canonical JSON (sorted-keys, LF, schema_version=2)
- read_manifest: BOM → exit 5, CRLF → exit 5, wrong schema_version → error
- reconcile_file 3-way decision matrix
- reconcile_install mixed-path iteration
- compute_manifest_hash_chain determinism + sensitivity
- Idempotency: second reconcile is UNCHANGED for everything
- Fixture round-trips
"""
from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


# ---------------------------------------------------------------------------
# Import modules under test
# ---------------------------------------------------------------------------

from lib.manifest_v2 import (  # type: ignore[import]
    MANIFEST_SCHEMA_VERSION,
    write_manifest,
    read_manifest,
)
from lib.manifest_reconciler import (  # type: ignore[import]
    ReconcileDecision,
    ReconcileResult,
    reconcile_file,
    reconcile_install,
    compute_manifest_hash_chain,
)


# ===========================================================================
# A. Schema version constant
# ===========================================================================

class TestSchemaVersionConstant:
    def test_schema_version_is_2(self) -> None:
        assert MANIFEST_SCHEMA_VERSION == 2


# ===========================================================================
# B. write_manifest
# ===========================================================================

class TestWriteManifest:
    def test_writes_schema_version_2(self, tmp_path: Path) -> None:
        out = tmp_path / "installed-manifest.json"
        manifest: dict[str, Any] = {
            "harness_version": "v0.7.0",
            "files": {},
        }
        write_manifest(manifest, path=out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["schema_version"] == 2

    def test_writes_sorted_keys_json(self, tmp_path: Path) -> None:
        out = tmp_path / "installed-manifest.json"
        manifest: dict[str, Any] = {
            "harness_version": "v0.7.0",
            "zebra": 1,
            "alpha": 2,
            "files": {},
        }
        write_manifest(manifest, path=out)
        raw = out.read_bytes().decode("utf-8")
        # sorted-keys: "alpha" must appear before "zebra"
        assert raw.index('"alpha"') < raw.index('"zebra"')

    def test_writes_lf_line_endings(self, tmp_path: Path) -> None:
        out = tmp_path / "installed-manifest.json"
        manifest: dict[str, Any] = {"harness_version": "v0.7.0", "files": {}}
        write_manifest(manifest, path=out)
        raw = out.read_bytes()
        assert b"\r\n" not in raw, "CRLF line endings must not be present"
        assert b"\n" in raw

    def test_no_bom_written(self, tmp_path: Path) -> None:
        out = tmp_path / "installed-manifest.json"
        manifest: dict[str, Any] = {"harness_version": "v0.7.0", "files": {}}
        write_manifest(manifest, path=out)
        raw = out.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), "BOM must not be written"

    def test_stamps_harness_version(self, tmp_path: Path) -> None:
        out = tmp_path / "installed-manifest.json"
        manifest: dict[str, Any] = {"harness_version": "v1.2.3", "files": {}}
        write_manifest(manifest, path=out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["harness_version"] == "v1.2.3"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "dir" / "installed-manifest.json"
        manifest: dict[str, Any] = {"harness_version": "v0.7.0", "files": {}}
        write_manifest(manifest, path=out)
        assert out.exists()


# ===========================================================================
# C. read_manifest
# ===========================================================================

class TestReadManifest:
    def _valid_manifest(self, version: int = 2) -> bytes:
        data = {"schema_version": version, "harness_version": "v0.7.0", "files": {}}
        return (json.dumps(data, sort_keys=True) + "\n").encode("utf-8")

    def test_reads_valid_manifest(self, tmp_path: Path) -> None:
        p = tmp_path / "m.json"
        p.write_bytes(self._valid_manifest())
        data = read_manifest(p)
        assert data["schema_version"] == 2

    def test_rejects_bom_exit5(self, tmp_path: Path) -> None:
        p = tmp_path / "m.json"
        p.write_bytes(b"\xef\xbb\xbf" + self._valid_manifest())
        with pytest.raises(SystemExit) as exc:
            read_manifest(p)
        assert exc.value.code == 5

    def test_canonicalizes_crlf_to_lf(self, tmp_path: Path) -> None:
        """CRLF in manifest → normalized to LF before JSON parse (no error)."""
        raw = self._valid_manifest().replace(b"\n", b"\r\n")
        p = tmp_path / "m.json"
        p.write_bytes(raw)
        # Should succeed after CRLF normalization
        data = read_manifest(p)
        assert data["schema_version"] == 2

    def test_rejects_schema_version_1(self, tmp_path: Path) -> None:
        p = tmp_path / "m.json"
        p.write_bytes(self._valid_manifest(version=1))
        with pytest.raises(SystemExit):
            read_manifest(p)

    def test_rejects_missing_schema_version(self, tmp_path: Path) -> None:
        data = {"harness_version": "v0.7.0", "files": {}}
        p = tmp_path / "m.json"
        p.write_bytes((json.dumps(data) + "\n").encode("utf-8"))
        with pytest.raises(SystemExit):
            read_manifest(p)

    def test_rejects_malformed_json(self, tmp_path: Path) -> None:
        p = tmp_path / "m.json"
        p.write_bytes(b"{bad json")
        with pytest.raises(SystemExit):
            read_manifest(p)


# ===========================================================================
# D. reconcile_file — 3-way decision matrix
# ===========================================================================

class TestReconcileFile:
    def _write(self, path: Path, content: str) -> str:
        """Write content to path, return sha256 of content bytes."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
        return sha256_text(content)

    def test_disk_matches_release_unchanged_safe_replace(self, tmp_path: Path) -> None:
        """disk hash == release installed_sha256 → UNCHANGED_SAFE_REPLACE."""
        disk = tmp_path / "disk" / "file.txt"
        q_dir = tmp_path / ".harness" / "conflicts"
        content = "hello world\n"
        inst_sha = self._write(disk, content)

        result = reconcile_file(
            disk,
            release_installed_sha256=inst_sha,
            prior_current_sha256=None,
            repo_root=tmp_path,
            quarantine_dir=q_dir,
            now_iso="2026-01-01T00:00:00Z",
        )
        assert result.decision == ReconcileDecision.UNCHANGED_SAFE_REPLACE
        assert result.quarantine_path is None
        assert result.disk_sha256 == inst_sha

    def test_disk_matches_prior_current_upgraded_safe_replace(self, tmp_path: Path) -> None:
        """disk hash == prior_current_sha256 → UPGRADED_SAFE_REPLACE."""
        disk = tmp_path / "disk" / "file.txt"
        q_dir = tmp_path / ".harness" / "conflicts"
        content = "user modified but harness also modified\n"
        current_sha = self._write(disk, content)
        release_sha = sha256_text("different release content\n")

        result = reconcile_file(
            disk,
            release_installed_sha256=release_sha,
            prior_current_sha256=current_sha,
            repo_root=tmp_path,
            quarantine_dir=q_dir,
            now_iso="2026-01-01T00:00:00Z",
        )
        assert result.decision == ReconcileDecision.UPGRADED_SAFE_REPLACE
        assert result.quarantine_path is None

    def test_disk_diverged_user_modified_quarantine(self, tmp_path: Path) -> None:
        """disk hash diverged from both → USER_MODIFIED_QUARANTINE + file moved."""
        disk = tmp_path / "project" / "file.txt"
        q_dir = tmp_path / ".harness" / "conflicts"
        user_content = "user modified content\n"
        self._write(disk, user_content)
        release_sha = sha256_text("original release\n")
        prior_sha = sha256_text("prior upgrade version\n")

        result = reconcile_file(
            disk,
            release_installed_sha256=release_sha,
            prior_current_sha256=prior_sha,
            repo_root=tmp_path,
            quarantine_dir=q_dir,
            now_iso="2026-01-01T00:00:00Z",
        )
        assert result.decision == ReconcileDecision.USER_MODIFIED_QUARANTINE
        assert result.quarantine_path is not None
        q = Path(result.quarantine_path)
        assert q.exists(), "Quarantine file must exist on disk"
        assert not disk.exists(), "Original diverged file must have been moved"

    def test_file_not_on_disk_unchanged_safe_replace(self, tmp_path: Path) -> None:
        """File not on disk → fresh install treated as UNCHANGED_SAFE_REPLACE."""
        disk = tmp_path / "nonexistent" / "file.txt"
        q_dir = tmp_path / ".harness" / "conflicts"

        result = reconcile_file(
            disk,
            release_installed_sha256=sha256_text("some content\n"),
            prior_current_sha256=None,
            repo_root=tmp_path,
            quarantine_dir=q_dir,
            now_iso="2026-01-01T00:00:00Z",
        )
        assert result.decision == ReconcileDecision.UNCHANGED_SAFE_REPLACE
        assert result.quarantine_path is None

    def test_quarantine_path_contains_timestamp(self, tmp_path: Path) -> None:
        disk = tmp_path / "project" / "file.txt"
        q_dir = tmp_path / ".harness" / "conflicts"
        self._write(disk, "diverged content\n")
        ts = "2026-05-17T12:00:00Z"

        result = reconcile_file(
            disk,
            release_installed_sha256=sha256_text("original\n"),
            prior_current_sha256=sha256_text("prior\n"),
            repo_root=tmp_path,
            quarantine_dir=q_dir,
            now_iso=ts,
        )
        assert ts.replace(":", "-") in result.quarantine_path or "2026" in result.quarantine_path


# ===========================================================================
# E. reconcile_install — mixed paths
# ===========================================================================

class TestReconcileInstall:
    def test_fresh_install_all_unchanged(self, tmp_path: Path) -> None:
        """No on-disk files → all UNCHANGED_SAFE_REPLACE."""
        release_manifest: dict[str, Any] = {
            "schema_version": 2,
            "harness_version": "v0.7.0",
            "files": {
                "a.txt": {"installed_sha256": sha256_text("a\n"), "current_sha256": sha256_text("a\n")},
                "b.txt": {"installed_sha256": sha256_text("b\n"), "current_sha256": sha256_text("b\n")},
            },
        }
        results = reconcile_install(
            release_manifest=release_manifest,
            prior_manifest=None,
            repo_root=tmp_path,
            now_iso="2026-01-01T00:00:00Z",
        )
        assert len(results) == 2
        assert all(r.decision == ReconcileDecision.UNCHANGED_SAFE_REPLACE for r in results)

    def test_mixed_decisions(self, tmp_path: Path) -> None:
        """One file unchanged, one diverged → mixed decisions."""
        safe_content = "safe content\n"
        safe_sha = sha256_text(safe_content)
        (tmp_path / "safe.txt").write_bytes(safe_content.encode("utf-8"))
        (tmp_path / "diverged.txt").write_bytes(b"user modified content\n")

        release_manifest: dict[str, Any] = {
            "schema_version": 2,
            "harness_version": "v0.7.0",
            "files": {
                "safe.txt": {"installed_sha256": safe_sha, "current_sha256": safe_sha},
                "diverged.txt": {
                    "installed_sha256": sha256_text("original release\n"),
                    "current_sha256": sha256_text("original release\n"),
                },
            },
        }
        results = reconcile_install(
            release_manifest=release_manifest,
            prior_manifest=None,
            repo_root=tmp_path,
            now_iso="2026-01-01T00:00:00Z",
        )
        decisions = {r.path: r.decision for r in results}
        assert decisions["safe.txt"] == ReconcileDecision.UNCHANGED_SAFE_REPLACE
        assert decisions["diverged.txt"] == ReconcileDecision.USER_MODIFIED_QUARANTINE

    def test_schema_v1_prior_treats_as_fresh(self, tmp_path: Path) -> None:
        """Prior manifest schema_version < 2 → treat all as fresh (no prior_current_sha256)."""
        prior_manifest = {"state_schema_version": 1, "files": {"x.txt": {"sha256": "abc"}}}
        release_manifest: dict[str, Any] = {
            "schema_version": 2,
            "harness_version": "v0.7.0",
            "files": {
                "x.txt": {"installed_sha256": sha256_text("x content\n"), "current_sha256": sha256_text("x content\n")},
            },
        }
        results = reconcile_install(
            release_manifest=release_manifest,
            prior_manifest=prior_manifest,
            repo_root=tmp_path,
            now_iso="2026-01-01T00:00:00Z",
        )
        # All UNCHANGED since file not on disk → fresh install
        assert all(r.decision == ReconcileDecision.UNCHANGED_SAFE_REPLACE for r in results)


# ===========================================================================
# F. compute_manifest_hash_chain
# ===========================================================================

class TestComputeManifestHashChain:
    def _base_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "harness_version": "v0.7.0",
            "files": {
                "a.txt": {"installed_sha256": "aaa", "current_sha256": "aaa"},
                "b.txt": {"installed_sha256": "bbb", "current_sha256": "bbb"},
            },
            "removed_in_version": [{"path": "old.txt", "removed_in": "v0.7.0"}],
        }

    def test_deterministic_same_input(self) -> None:
        m = self._base_manifest()
        h1 = compute_manifest_hash_chain(m)
        h2 = compute_manifest_hash_chain(m)
        assert h1 == h2

    def test_changes_when_version_changes(self) -> None:
        m1 = self._base_manifest()
        m2 = dict(m1, harness_version="v0.8.0")
        assert compute_manifest_hash_chain(m1) != compute_manifest_hash_chain(m2)

    def test_changes_when_file_entry_changes(self) -> None:
        m1 = self._base_manifest()
        m2 = dict(m1)
        m2["files"] = dict(m1["files"])
        m2["files"]["a.txt"] = {"installed_sha256": "zzz", "current_sha256": "zzz"}
        assert compute_manifest_hash_chain(m1) != compute_manifest_hash_chain(m2)

    def test_changes_when_removed_in_version_changes(self) -> None:
        m1 = self._base_manifest()
        m2 = dict(m1)
        m2["removed_in_version"] = []
        assert compute_manifest_hash_chain(m1) != compute_manifest_hash_chain(m2)

    def test_returns_64_char_hex(self) -> None:
        m = self._base_manifest()
        h = compute_manifest_hash_chain(m)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_stable_across_file_order(self) -> None:
        """Hash must be stable regardless of dict insertion order of files."""
        m1 = {
            "schema_version": 2,
            "harness_version": "v0.7.0",
            "files": {
                "a.txt": {"installed_sha256": "aaa", "current_sha256": "aaa"},
                "b.txt": {"installed_sha256": "bbb", "current_sha256": "bbb"},
            },
            "removed_in_version": [],
        }
        m2 = {
            "schema_version": 2,
            "harness_version": "v0.7.0",
            "files": {
                "b.txt": {"installed_sha256": "bbb", "current_sha256": "bbb"},
                "a.txt": {"installed_sha256": "aaa", "current_sha256": "aaa"},
            },
            "removed_in_version": [],
        }
        assert compute_manifest_hash_chain(m1) == compute_manifest_hash_chain(m2)


# ===========================================================================
# G. Idempotency
# ===========================================================================

class TestIdempotency:
    def test_second_reconcile_is_unchanged(self, tmp_path: Path) -> None:
        """Run reconcile_install twice: second run all UNCHANGED_SAFE_REPLACE."""
        content = "stable content\n"
        sha = sha256_text(content)
        (tmp_path / "stable.txt").write_bytes(content.encode("utf-8"))

        release_manifest: dict[str, Any] = {
            "schema_version": 2,
            "harness_version": "v0.7.0",
            "files": {
                "stable.txt": {"installed_sha256": sha, "current_sha256": sha},
            },
        }
        # First pass
        results1 = reconcile_install(
            release_manifest=release_manifest,
            prior_manifest=None,
            repo_root=tmp_path,
            now_iso="2026-01-01T00:00:00Z",
        )
        assert results1[0].decision == ReconcileDecision.UNCHANGED_SAFE_REPLACE

        # Second pass - same state
        results2 = reconcile_install(
            release_manifest=release_manifest,
            prior_manifest=None,
            repo_root=tmp_path,
            now_iso="2026-01-01T00:01:00Z",
        )
        assert results2[0].decision == ReconcileDecision.UNCHANGED_SAFE_REPLACE


# ===========================================================================
# H. Fixture round-trips
# ===========================================================================

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "manifest"


class TestFixtureRoundTrips:
    def test_disk_hash_diverged_fixture_triggers_quarantine(self, tmp_path: Path) -> None:
        """Load disk_hash_diverged fixture → reconcile_file → QUARANTINE decision."""
        fixture_dir = FIXTURES_DIR / "disk_hash_diverged_from_release"
        manifest_path = fixture_dir / "installed-manifest.json"
        disk_file = fixture_dir / "disk-file.txt"

        assert manifest_path.exists(), f"Fixture missing: {manifest_path}"
        assert disk_file.exists(), f"Fixture missing: {disk_file}"

        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        file_entry = manifest_data["files"]["disk-file.txt"]
        release_sha = file_entry["installed_sha256"]

        # Copy disk file to tmp_path (reconcile_file moves it)
        target_file = tmp_path / "disk-file.txt"
        target_file.write_bytes(disk_file.read_bytes())
        q_dir = tmp_path / ".harness" / "conflicts"

        result = reconcile_file(
            target_file,
            release_installed_sha256=release_sha,
            prior_current_sha256=file_entry.get("current_sha256"),
            repo_root=tmp_path,
            quarantine_dir=q_dir,
            now_iso="2026-01-01T00:00:00Z",
        )
        assert result.decision == ReconcileDecision.USER_MODIFIED_QUARANTINE

    def test_install_record_bom_fixture_exits_5(self, tmp_path: Path) -> None:
        """Load install_record_bom fixture → read_manifest exits 5."""
        fixture_path = FIXTURES_DIR / "install_record_bom" / "install-record.json"
        assert fixture_path.exists(), f"Fixture missing: {fixture_path}"

        # Copy to tmp so read_manifest can read it
        target = tmp_path / "m.json"
        target.write_bytes(fixture_path.read_bytes())

        with pytest.raises(SystemExit) as exc:
            read_manifest(target)
        assert exc.value.code == 5

    def test_install_record_tampered_approvers_fixture_exists(self) -> None:
        """install_record_tampered_approvers fixture must be present."""
        fixture_path = FIXTURES_DIR / "install_record_tampered_approvers" / "install-record.json"
        assert fixture_path.exists(), f"Fixture missing: {fixture_path}"
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        # The tampered approvers field must be a list
        assert isinstance(data.get("approvers"), list)


# ===========================================================================
# I. verify_install_record_integrity stub
# ===========================================================================

class TestVerifyInstallRecordIntegrityStub:
    def test_stub_exists(self) -> None:
        """verify_install_record_integrity must exist as a stub (TODO anchor integration deferred)."""
        from lib.manifest_reconciler import verify_install_record_integrity  # type: ignore[import]
        import inspect
        src = inspect.getsource(verify_install_record_integrity)
        assert "TODO" in src or "NotImplementedError" in src or "anchor" in src.lower()
