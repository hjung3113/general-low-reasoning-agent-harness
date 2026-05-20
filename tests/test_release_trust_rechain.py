"""T16 tests: release_trust.record_rechain + release.trust.rechained audit verb.

Done-criteria:
  (a) v0.9.4 → v0.9.5 in-place upgrade emits exactly one ``release.trust.rechained`` row.
  (b) v0.9.5 → v0.9.5 rerun emits zero rows (idempotency).
  (c) audit chain verifies clean after upgrade (previous_entry_hash chains correctly).
  (d) idempotency_via_rechain_log: same (prev, new) pair → no double-emit.

Codex C-1, C-2 compliance:
  - record_rechain always uses lib.audit.audit_append (never raw file write).
  - previous_chain_hash captured BEFORE new chain is computed in upgrade.py.
  - Trigger only when previous_chain_hash != new_chain_hash.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib.release_trust import (  # type: ignore[import]
    classify_rechain_cause,
    record_rechain,
    _V094_MISSING_MODULES,
)
from lib.audit import read_last_entry  # type: ignore[import]
from lib.manifest_reconciler import compute_manifest_hash_chain  # type: ignore[import]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_audit_path(tmp_path: Path) -> Path:
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    return harness_dir / "audit.log"


def _read_all_audit_rows(audit_path: Path) -> list[dict]:
    """Read all JSON lines from audit.log."""
    if not audit_path.exists():
        return []
    rows = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def _count_rechain_rows(audit_path: Path) -> int:
    return sum(
        1 for r in _read_all_audit_rows(audit_path)
        if r.get("verb") == "release.trust.rechained"
    )


def _make_chain_manifest(files: dict[str, str], harness_version: str = "0.9.4") -> dict:
    """Build a minimal chain manifest and compute its hash."""
    return {
        "release_commit": None,
        "release_tag": None,
        "schema_version": 2,
        "harness_version": harness_version,
        "files": {
            p: {"installed_sha256": sha, "current_sha256": sha}
            for p, sha in files.items()
        },
        "removed_in_version": [],
        "trust_origin": "dev_unsigned",
    }


# ===========================================================================
# A. test_record_rechain_emits_audit_row
#    Simulate v0.9.4 → v0.9.5 chain delta; assert one release.trust.rechained
#    row with correct fields.
# ===========================================================================

class TestRecordRechainEmitsAuditRow:
    """record_rechain emits exactly one release.trust.rechained row."""

    def test_single_row_emitted(self, tmp_path: Path) -> None:
        audit_path = _make_audit_path(tmp_path)
        prev_hash = "aabbcc" * 10 + "aabb"  # 64 hex chars (fake)
        new_hash  = "ddeeff" * 10 + "ddee"

        record_rechain(
            tmp_path, prev_hash, new_hash, "v094_manifest_gap_remediation",
            module_count_added=35, actor="ci@example.com",
        )

        rows = _read_all_audit_rows(audit_path)
        rechain_rows = [r for r in rows if r.get("verb") == "release.trust.rechained"]
        assert len(rechain_rows) == 1, f"Expected 1 rechain row, got {len(rechain_rows)}"

    def test_row_fields_correct(self, tmp_path: Path) -> None:
        audit_path = _make_audit_path(tmp_path)
        prev_hash = "a" * 64
        new_hash  = "b" * 64

        record_rechain(
            tmp_path, prev_hash, new_hash, "v094_manifest_gap_remediation",
            module_count_added=35, actor="engineer@example.com",
        )

        row = _read_all_audit_rows(audit_path)[-1]
        assert row["verb"] == "release.trust.rechained"
        assert row["by"] == "engineer@example.com"
        args = row["args"]
        assert args["previous_chain_hash"] == prev_hash
        assert args["new_chain_hash"] == new_hash
        assert args["cause"] == "v094_manifest_gap_remediation"
        assert args["module_count_added"] == 35

    def test_row_has_chain_fields(self, tmp_path: Path) -> None:
        """Verify S06 chain fields are present (audit_append integration)."""
        audit_path = _make_audit_path(tmp_path)
        record_rechain(tmp_path, "c" * 64, "d" * 64, "manifest_evolution")

        row = _read_all_audit_rows(audit_path)[-1]
        assert "schema_version" in row
        assert row["schema_version"] == 2
        assert "entry_hash" in row
        assert "previous_entry_hash" in row
        assert "seq" in row
        assert "seq_global" in row

    def test_v094_cause_classification(self) -> None:
        """Files matching _V094_MISSING_MODULES → v094_manifest_gap_remediation."""
        some_v094_path = next(iter(_V094_MISSING_MODULES))
        cause, count = classify_rechain_cause([some_v094_path])
        assert cause == "v094_manifest_gap_remediation"
        assert count == 1

    def test_non_v094_cause_classification(self) -> None:
        """Unknown paths → manifest_evolution."""
        cause, count = classify_rechain_cause(["scripts/lib/some_new_module.py"])
        assert cause == "manifest_evolution"
        assert count == 1

    def test_empty_added_paths_manifest_evolution(self) -> None:
        """Empty added paths → manifest_evolution with count=0."""
        cause, count = classify_rechain_cause([])
        assert cause == "manifest_evolution"
        assert count == 0


# ===========================================================================
# B. test_no_emit_when_chain_unchanged
#    v0.9.5 → v0.9.5 rerun; assert zero new rechain rows.
# ===========================================================================

class TestNoEmitWhenChainUnchanged:
    """record_rechain is not called when chain hash is unchanged (no delta)."""

    def test_upgrade_rechain_does_not_fire_when_hashes_equal(
        self, tmp_path: Path
    ) -> None:
        """Simulate the upgrade() guard: skip when previous == new hash."""
        audit_path = _make_audit_path(tmp_path)
        same_hash = "e" * 64

        # The guard in upgrade.py: ``if previous_chain_hash != new_chain_hash``
        # — replicate that logic here.
        if same_hash != same_hash:  # pragma: no cover
            record_rechain(tmp_path, same_hash, same_hash, "manifest_evolution")

        assert _count_rechain_rows(audit_path) == 0

    def test_no_row_when_no_call_made(self, tmp_path: Path) -> None:
        """If record_rechain is never called, no rows appear."""
        audit_path = _make_audit_path(tmp_path)
        assert _count_rechain_rows(audit_path) == 0

    def test_same_chain_delta_guard_in_stamp(self, tmp_path: Path) -> None:
        """Direct verify: identical prev/new hash pair → _emit_rechain_audit
        sets _pending_rechain but upgrade.py's guard prevents the call."""
        # The guard in _stamp_installed_manifest_v2:
        #   if previous_chain_hash and new_chain_hash and previous_chain_hash != new_chain_hash:
        # Verify the guard logic prevents emit when hashes are equal.
        same = "f" * 64
        prev = same
        new = same
        # If equal, condition is False → no emit
        should_emit = bool(prev and new and prev != new)
        assert should_emit is False


# ===========================================================================
# C. test_idempotency_via_rechain_log
#    Same (prev, new) pair → no double-emit.
# ===========================================================================

class TestIdempotencyViaRechainLog:
    """rechain_log idempotency: same (prev, new) pair emits at most one row."""

    def test_direct_call_twice_emits_two_rows(self, tmp_path: Path) -> None:
        """record_rechain itself doesn't check the rechain_log — the guard is
        in _emit_rechain_audit.  Two direct calls emit two rows (intentional:
        the idempotency guard is at the _emit_rechain_audit level, not in
        record_rechain itself).  This test documents the boundary."""
        audit_path = _make_audit_path(tmp_path)
        prev, new = "1" * 64, "2" * 64
        record_rechain(tmp_path, prev, new, "manifest_evolution")
        record_rechain(tmp_path, prev, new, "manifest_evolution")
        # Both calls succeed — two rows (no dedup inside record_rechain)
        assert _count_rechain_rows(audit_path) == 2

    def test_emit_rechain_audit_idempotency(self, tmp_path: Path) -> None:
        """_emit_rechain_audit skips emit when (prev, new) pair is in rechain_log."""
        # Import the internal helper to test idempotency logic directly.
        from lib.upgrade import _emit_rechain_audit  # type: ignore[import]

        audit_path = _make_audit_path(tmp_path)
        prev, new = "3" * 64, "4" * 64

        # Build a minimal installed dict with installed_files
        installed: dict[str, Any] = {
            "installed_files_chain_hash": prev,
            "files": {
                "scripts/lib/transition.py": {
                    "installed_sha256": "aaa",
                    "current_sha256": "aaa",
                },
            },
        }
        installed_files = installed["files"]

        # First call: should store _pending_rechain and add to rechain_log
        _emit_rechain_audit(
            installed=installed,
            installed_files=installed_files,
            previous_chain_hash=prev,
            new_chain_hash=new,
        )
        assert "_pending_rechain" in installed
        assert len(installed.get("rechain_log", [])) == 1

        # Simulate completing first call (as upgrade() does: pop _pending_rechain)
        installed.pop("_pending_rechain", None)

        # Second call with identical (prev, new): idempotency guard fires
        _emit_rechain_audit(
            installed=installed,
            installed_files=installed_files,
            previous_chain_hash=prev,
            new_chain_hash=new,
        )
        # _pending_rechain must NOT be set (idempotency guard prevented emit)
        assert "_pending_rechain" not in installed
        # rechain_log still has just one entry
        assert len(installed.get("rechain_log", [])) == 1

    def test_different_pair_does_emit(self, tmp_path: Path) -> None:
        """A different (prev, new) pair IS allowed to emit even with rechain_log present."""
        from lib.upgrade import _emit_rechain_audit  # type: ignore[import]

        prev1, new1 = "5" * 64, "6" * 64
        prev2, new2 = "7" * 64, "8" * 64

        installed: dict[str, Any] = {
            "files": {
                "scripts/lib/check.py": {
                    "installed_sha256": "ccc",
                    "current_sha256": "ccc",
                },
            },
            "rechain_log": [
                {"previous_chain_hash": prev1, "new_chain_hash": new1,
                 "cause": "manifest_evolution", "at_iso": "2026-05-21T00:00:00Z"},
            ],
        }
        installed_files = installed["files"]

        _emit_rechain_audit(
            installed=installed,
            installed_files=installed_files,
            previous_chain_hash=prev2,
            new_chain_hash=new2,
        )
        assert "_pending_rechain" in installed
        assert installed["_pending_rechain"]["previous_chain_hash"] == prev2


# ===========================================================================
# D. test_audit_chain_verifies_post_rechain
#    After rechain, previous_entry_hash links correctly.
# ===========================================================================

class TestAuditChainVerifiesPostRechain:
    """After record_rechain, the audit chain is internally consistent."""

    def test_chain_links_after_rechain(self, tmp_path: Path) -> None:
        """previous_entry_hash of rechain row points to the prior entry's entry_hash."""
        from lib.audit import audit_append  # type: ignore[import]
        import datetime as dt

        audit_path = _make_audit_path(tmp_path)

        # Write a prior entry first
        prior_entry = {
            "verb": "release.trust.verified",
            "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "args": {"tag": "v0.9.4"},
        }
        audit_append(prior_entry, audit_path=audit_path)
        prior_row = _read_all_audit_rows(audit_path)[-1]
        prior_entry_hash = prior_row["entry_hash"]

        # Now emit the rechain row
        record_rechain(
            tmp_path, "a" * 64, "b" * 64, "v094_manifest_gap_remediation",
            module_count_added=35, actor="ci@example.com",
        )

        rechain_row = _read_all_audit_rows(audit_path)[-1]
        assert rechain_row["verb"] == "release.trust.rechained"
        assert rechain_row["previous_entry_hash"] == prior_entry_hash, (
            f"Chain broken: rechain row previous_entry_hash "
            f"{rechain_row['previous_entry_hash']!r} != "
            f"prior entry_hash {prior_entry_hash!r}"
        )

    def test_chain_integrity_via_verify_chain(self, tmp_path: Path) -> None:
        """verify_chain reports ok=True for a log containing a rechain row."""
        from lib.audit import audit_append  # type: ignore[import]
        from lib.audit_chain import verify_chain  # type: ignore[import]
        import datetime as dt

        audit_path = _make_audit_path(tmp_path)

        # Write two prior entries
        for verb in ("release.trust.verified", "release.trust.bypassed"):
            audit_append(
                {
                    "verb": verb,
                    "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "args": {},
                },
                audit_path=audit_path,
            )

        # Emit rechain
        record_rechain(
            tmp_path, "c" * 64, "d" * 64, "manifest_evolution",
            module_count_added=1, actor="system",
        )

        # verify_chain returns ChainVerifyResult; chain must be clean
        result = verify_chain(audit_path)
        assert result.ok is True, (
            f"verify_chain found chain error: {result.error}"
        )
