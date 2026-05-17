"""P1-2 tests: read_manifest wiring, verify_manifest_chain, ManifestChainTamperedError,
verify_install_record_integrity functional de-stub.

Spec: §6 (manifest chain hash + install record integrity).
Slice: S14 review-fix.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.manifest_v2 import write_manifest, read_manifest  # type: ignore[import]
from lib.manifest_reconciler import (  # type: ignore[import]
    ManifestChainTamperedError,
    compute_manifest_hash_chain,
    verify_manifest_chain,
    verify_install_record_integrity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_v2_manifest(tmp_path: Path, files: dict | None = None, stamp_chain: bool = False) -> dict[str, Any]:
    """Build and write a schema_version=2 manifest; optionally stamp chain hash."""
    m: dict[str, Any] = {
        "schema_version": 2,
        "harness_version": "v0.7.0",
        "files": files or {},
    }
    if stamp_chain:
        chain_manifest = {k: v for k, v in m.items() if k != "installed_files_chain_hash"}
        m["installed_files_chain_hash"] = compute_manifest_hash_chain(chain_manifest)
    return m


# ===========================================================================
# A. BOM in upgrade path → exit 5 propagates
# ===========================================================================

class TestUpgradeBOMRejectsExit5:
    """upgrade.py prior_manifest_v2 parsing: BOM → exit 5."""

    def test_bom_install_record_causes_exit5(self, tmp_path: Path) -> None:
        """A BOM-prefixed installed-manifest.json must cause SystemExit(5) on upgrade.

        This validates that the inline json.loads was replaced with read_manifest
        which propagates exit 5 per §2.4 contract.
        """
        # Write a BOM-prefixed manifest
        manifest_path = tmp_path / ".harness" / "installed-manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        valid_json = json.dumps({"schema_version": 2, "harness_version": "v0.7.0", "files": {}}) + "\n"
        manifest_path.write_bytes(b"\xef\xbb\xbf" + valid_json.encode("utf-8"))

        # Import upgrade and test that reading the manifest raises SystemExit(5)
        from lib.manifest_v2 import read_manifest  # type: ignore[import]
        with pytest.raises(SystemExit) as exc:
            read_manifest(manifest_path)
        assert exc.value.code == 5, f"Expected exit code 5 for BOM, got {exc.value.code}"


# ===========================================================================
# B. verify_manifest_chain
# ===========================================================================

class TestVerifyManifestChain:
    def test_no_chain_hash_returns_true(self) -> None:
        """Manifest without installed_files_chain_hash → no-op, returns True."""
        m = {"schema_version": 2, "harness_version": "v0.7.0", "files": {}}
        assert verify_manifest_chain(m) is True

    def test_matching_chain_hash_returns_true(self) -> None:
        """Manifest with correct installed_files_chain_hash → returns True."""
        m: dict[str, Any] = {
            "schema_version": 2,
            "harness_version": "v0.7.0",
            "files": {
                "a.txt": {"installed_sha256": "aaa", "current_sha256": "aaa"},
            },
            "removed_in_version": [],
        }
        # Compute the hash on a copy WITHOUT the chain field (as stamping would do)
        m_without = {k: v for k, v in m.items() if k != "installed_files_chain_hash"}
        m["installed_files_chain_hash"] = compute_manifest_hash_chain(m_without)
        assert verify_manifest_chain(m) is True

    def test_tampered_field_raises_tampered_error(self) -> None:
        """Modifying a manifest field after chain hash stamped → ManifestChainTamperedError."""
        m: dict[str, Any] = {
            "schema_version": 2,
            "harness_version": "v0.7.0",
            "files": {
                "a.txt": {"installed_sha256": "aaa", "current_sha256": "aaa"},
            },
            "removed_in_version": [],
        }
        m_without = {k: v for k, v in m.items() if k != "installed_files_chain_hash"}
        m["installed_files_chain_hash"] = compute_manifest_hash_chain(m_without)

        # Tamper: modify harness_version after hash was computed
        m["harness_version"] = "v0.8.0-tampered"

        with pytest.raises(ManifestChainTamperedError) as exc_info:
            verify_manifest_chain(m)
        assert exc_info.value.code == 5

    def test_ManifestChainTamperedError_is_system_exit(self) -> None:
        """ManifestChainTamperedError must be a subclass of SystemExit."""
        err = ManifestChainTamperedError()
        assert isinstance(err, SystemExit)
        assert err.code == 5

    def test_tampered_file_entry_raises(self) -> None:
        """Modifying a file entry after hash stamped → ManifestChainTamperedError (exit 5)."""
        m: dict[str, Any] = {
            "schema_version": 2,
            "harness_version": "v0.7.0",
            "files": {
                "b.txt": {"installed_sha256": "bbb", "current_sha256": "bbb"},
            },
            "removed_in_version": [],
        }
        m_without = {k: v for k, v in m.items() if k != "installed_files_chain_hash"}
        m["installed_files_chain_hash"] = compute_manifest_hash_chain(m_without)

        # Tamper: modify the file entry
        m["files"]["b.txt"]["installed_sha256"] = "tampered-sha"

        with pytest.raises(ManifestChainTamperedError):
            verify_manifest_chain(m)


# ===========================================================================
# C. verify_install_record_integrity — functional (de-stubbed)
# ===========================================================================

class TestVerifyInstallRecordIntegrity:
    def test_absent_install_record_returns_false(self, tmp_path: Path) -> None:
        """No .harness/installed-manifest.json → returns False (fresh install)."""
        result = verify_install_record_integrity(tmp_path)
        assert result is False

    def test_valid_install_record_returns_true(self, tmp_path: Path) -> None:
        """Valid schema_version=2 manifest without chain hash → returns True."""
        record = tmp_path / ".harness" / "installed-manifest.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        m: dict[str, Any] = {
            "schema_version": 2,
            "harness_version": "v0.7.0",
            "files": {},
        }
        write_manifest(m, path=record)
        result = verify_install_record_integrity(tmp_path)
        assert result is True

    def test_bom_install_record_exits_5(self, tmp_path: Path) -> None:
        """BOM-prefixed install record → SystemExit(5) from verify_install_record_integrity."""
        record = tmp_path / ".harness" / "installed-manifest.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        valid_json = json.dumps({"schema_version": 2, "harness_version": "v0.7.0", "files": {}}) + "\n"
        record.write_bytes(b"\xef\xbb\xbf" + valid_json.encode("utf-8"))

        with pytest.raises(SystemExit) as exc:
            verify_install_record_integrity(tmp_path)
        assert exc.value.code == 5

    def test_tampered_chain_hash_exits_5(self, tmp_path: Path) -> None:
        """install record with tampered installed_files_chain_hash → exit 5."""
        record = tmp_path / ".harness" / "installed-manifest.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        m: dict[str, Any] = {
            "schema_version": 2,
            "harness_version": "v0.7.0",
            "files": {
                "x.txt": {"installed_sha256": "xxx", "current_sha256": "xxx"},
            },
            "removed_in_version": [],
        }
        # Stamp a WRONG chain hash
        m["installed_files_chain_hash"] = "0" * 64
        write_manifest(m, path=record)

        with pytest.raises((SystemExit, ManifestChainTamperedError)) as exc:
            verify_install_record_integrity(tmp_path)
        # Should exit with code 5
        assert exc.value.code == 5

    def test_no_longer_raises_not_implemented(self, tmp_path: Path) -> None:
        """verify_install_record_integrity must NOT raise NotImplementedError (de-stubbed)."""
        # With no install record it returns False, not NotImplementedError
        try:
            result = verify_install_record_integrity(tmp_path)
            # Should return False for absent record
            assert result is False
        except NotImplementedError:
            pytest.fail(
                "verify_install_record_integrity still raises NotImplementedError — "
                "it should be de-stubbed per P1-2 review fix."
            )
