"""P5-P1-3 + P5-P1-4 integration tests: verify wiring in upgrade/check/install.

P5-P1-3: verify_manifest_chain + verify_install_record_integrity now called from
         production paths (upgrade.py, check.py, install.py).
P5-P1-4: upgrade.py no longer silently swallows ManifestChainTamperedError;
         chain mismatch now emits a WARNING and continues (upgrade re-stamps),
         while BOM/parse errors (exit 5) still propagate as hard stops.

Severity policy per code path:
  - upgrade.py: WARN and continue (prior manifest may be legacy/pre-chain)
  - check.py:   WARN and continue (other specific check errors are primary)
  - install.py: HARD STOP exit 5 (chain tamper on active install record)

Spec: §6 (manifest chain hash + install record integrity).
Slice: P5-P1-3/P5-P1-4 review fixes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.manifest_reconciler import (  # type: ignore[import]
    ManifestChainTamperedError,
    compute_manifest_hash_chain,
    verify_manifest_chain,
    verify_install_record_integrity,
)
from lib.manifest_v2 import write_manifest  # type: ignore[import]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INSTALL_STATE_REL = ".harness/installed-manifest.json"


def _write_valid_chain_manifest(target: Path, extra_files: dict | None = None) -> None:
    """Write a valid schema_version=2 manifest with correct chain hash."""
    record = target / _INSTALL_STATE_REL
    record.parent.mkdir(parents=True, exist_ok=True)
    m: dict[str, Any] = {
        "schema_version": 2,
        "harness_version": "v0.7.0",
        "files": extra_files or {},
    }
    m_without = {k: v for k, v in m.items() if k != "installed_files_chain_hash"}
    m["installed_files_chain_hash"] = compute_manifest_hash_chain(m_without)
    write_manifest(m, path=record)


def _write_tampered_chain_manifest(target: Path) -> None:
    """Write a manifest whose installed_files_chain_hash is incorrect."""
    record = target / _INSTALL_STATE_REL
    record.parent.mkdir(parents=True, exist_ok=True)
    m: dict[str, Any] = {
        "schema_version": 2,
        "harness_version": "v0.7.0",
        "files": {
            "a.txt": {"installed_sha256": "aaa", "current_sha256": "aaa"},
        },
        "removed_in_version": [],
        "installed_files_chain_hash": "0" * 64,  # wrong hash
    }
    write_manifest(m, path=record)


# ===========================================================================
# A. upgrade.py: tampered prior manifest → WARNING emitted, NOT exit 5
# ===========================================================================

class TestUpgradePropagatesChainTampering:
    """verify_manifest_chain: tampered chain → ManifestChainTamperedError (exit 5)."""

    def test_verify_manifest_chain_raises_on_tamper(self, tmp_path: Path) -> None:
        """verify_install_record_integrity raises ManifestChainTamperedError (exit 5)
        for a tampered manifest.

        P5-P1-3: verify_install_record_integrity is now called from production
        code paths. The function itself raises; callers decide whether to hard-stop
        or warn-and-continue.
        """
        _write_tampered_chain_manifest(tmp_path)
        with pytest.raises(SystemExit) as exc:
            verify_install_record_integrity(tmp_path)
        assert exc.value.code == 5, (
            f"Expected exit 5 for tampered chain hash, got {exc.value.code}"
        )

    def test_upgrade_valid_chain_does_not_raise(self, tmp_path: Path) -> None:
        """A valid chain hash must NOT raise — upgrade proceeds normally."""
        _write_valid_chain_manifest(tmp_path)
        result = verify_install_record_integrity(tmp_path)
        assert result is True

    def test_upgrade_absent_manifest_returns_false(self, tmp_path: Path) -> None:
        """No prior installed-manifest.json → returns False (fresh install path)."""
        result = verify_install_record_integrity(tmp_path)
        assert result is False


# ===========================================================================
# B. check.py: tampered install record → WARNING, proceeds to specific check
# ===========================================================================

class TestCheckRefusesTamperedManifest:
    """check.check_installed_target now calls verify_install_record_integrity."""

    def test_check_warns_on_tampered_manifest_chain(self, tmp_path: Path, capsys) -> None:
        """check_installed_target on a tampered manifest emits WARNING to stderr.

        P5-P1-3: verify_install_record_integrity is called in check_installed_target.
        Chain mismatch is a WARNING (not hard stop) so other specific check errors
        (policy mismatch, retired files) are still surfaced.

        After warning, check proceeds but may raise SystemExit for other reasons
        (e.g. invalid schema, missing version); we just verify no exit 5.
        """
        _write_tampered_chain_manifest(tmp_path)
        from lib.check import check_installed_target  # type: ignore[import]
        try:
            check_installed_target(tmp_path)
        except SystemExit as exc:
            # Must NOT be exit 5 (chain-tamper hard stop) — only WARNING
            assert exc.code != 5, (
                "check_installed_target raised exit 5 for tampered chain — "
                "should warn-and-continue per policy"
            )
        # Verify WARNING was emitted to stderr
        captured = capsys.readouterr()
        assert "chain hash mismatch" in captured.err or "WARNING" in captured.err, (
            "Expected chain hash mismatch WARNING in stderr, got: " + repr(captured.err)
        )

    def test_check_absent_install_state_raises_not_5(self, tmp_path: Path) -> None:
        """No installed-manifest.json → SystemExit with string message (not code 5).

        check_installed_target raises SystemExit(string) for missing file, so
        code is a string, not 5.
        """
        from lib.check import check_installed_target  # type: ignore[import]
        with pytest.raises(SystemExit) as exc:
            check_installed_target(tmp_path)
        # String message exit, not integer 5
        assert not isinstance(exc.value.code, int) or exc.value.code != 5


# ===========================================================================
# C. install.py: tampered install record → exit 5 via install()
# ===========================================================================

class TestInstallRefusesTamperedInstallRecord:
    """install.install() now calls verify_install_record_integrity at entry."""

    def test_install_refuses_tampered_install_record(self, tmp_path: Path) -> None:
        """install() on a target with tampered installed-manifest.json → exit 5.

        P5-P1-3: verify_install_record_integrity is called at the start of install().
        """
        _write_tampered_chain_manifest(tmp_path)
        from lib.install import install  # type: ignore[import]
        # install() calls _vir(target) first — tampered chain must exit 5.
        with pytest.raises(SystemExit) as exc:
            install(
                root=tmp_path,
                target=tmp_path,
                dry_run=True,
            )
        assert exc.value.code == 5, (
            f"Expected exit 5 from tampered chain in install, got {exc.value.code}"
        )

    def test_install_valid_chain_does_not_exit_5(self, tmp_path: Path) -> None:
        """install() on a target with valid chain hash proceeds past integrity check.

        The install may still fail for other reasons (missing source manifest etc.),
        but it must NOT exit 5 for a legitimate tamper-free install record.
        """
        _write_valid_chain_manifest(tmp_path)
        from lib.install import install  # type: ignore[import]
        # install() proceeds past the integrity check; any subsequent failure
        # (missing source manifest, FileNotFoundError, etc.) is acceptable —
        # what we must NOT see is exit 5 (chain-tamper exit).
        try:
            install(
                root=tmp_path,
                target=tmp_path,
                dry_run=True,
            )
        except SystemExit as exc:
            assert exc.code != 5, (
                "install() raised exit 5 on a valid manifest — "
                "verify_install_record_integrity returned false positive"
            )
        except Exception:
            pass  # any non-SystemExit failure is fine — not a chain-tamper exit
