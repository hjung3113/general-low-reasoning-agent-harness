"""Cycle-2 P2-A5: JTI store distinguishes missing vs corrupted (§12.4).

Before this fix, _check_and_record_jti caught ALL exceptions with a bare
`except Exception: return None` including json.JSONDecodeError.  A corrupted-
but-existent jti_seen.json silently reset replay protection, making it
indistinguishable from a fresh install.

Fix: FileNotFoundError → fresh install (return None as before).
     json.JSONDecodeError → WARNING to stderr + rotate file aside + return None.

Tests:
  A. Corrupted JTI file → WARNING on stderr + rotated .corrupted.<ts> file created.
  B. Corrupted JTI file → replay-protection reset (fresh start, not block).
  C. Missing JTI file → no WARNING, no rotation, fresh start (original behavior preserved).
  D. Valid JTI file with known JTI → replay rejected (regression).
  E. ci.oidc.jti.store_rotated verb appears in KNOWN_VERBS.
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib import phase_autopilot, audit as _audit
from lib.phase_autopilot import _check_and_record_jti  # type: ignore[import]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_harness(tmp_path: Path) -> tuple[Path, Path]:
    """Return (harness_dir, audit_path) with audit dir created."""
    harness = tmp_path / ".harness"
    harness.mkdir(parents=True, exist_ok=True)
    audit_path = harness / "audit.log"
    audit_path.write_text("", encoding="utf-8")
    return harness, audit_path


# ---------------------------------------------------------------------------
# A. Corrupted JTI file → WARNING on stderr + rotation file created
# ---------------------------------------------------------------------------


class TestCorruptedJtiStoreRotation:
    def test_corrupted_jti_emits_warning_to_stderr(
        self, tmp_path: Path, capsys
    ):
        """A corrupted oidc_jti_seen.json produces a WARNING on stderr."""
        harness, audit_path = _make_harness(tmp_path)
        jti_path = harness / "oidc_jti_seen.json"
        jti_path.write_text("{not valid json", encoding="utf-8")  # corrupt

        _check_and_record_jti("new-jti-1", harness_dir=harness, audit_path=audit_path)

        captured = capsys.readouterr()
        assert "WARNING" in captured.err or "corrupted" in captured.err.lower(), (
            f"Expected WARNING in stderr, got: {captured.err!r}"
        )

    def test_corrupted_jti_creates_rotation_backup(self, tmp_path: Path, capsys):
        """A corrupted oidc_jti_seen.json is renamed to *.corrupted.<ts>."""
        harness, audit_path = _make_harness(tmp_path)
        jti_path = harness / "oidc_jti_seen.json"
        jti_path.write_text("THIS IS NOT JSON ]]]]", encoding="utf-8")

        _check_and_record_jti("new-jti-2", harness_dir=harness, audit_path=audit_path)

        # Original file should be gone (renamed)
        # A .corrupted.<ts> file should exist in harness/
        corrupted_files = list(harness.glob("oidc_jti_seen.corrupted.*"))
        assert corrupted_files, (
            "Expected at least one oidc_jti_seen.corrupted.<ts> file after rotation, "
            "found none. harness dir contents: " + str(list(harness.iterdir()))
        )

    def test_corrupted_jti_audits_rotation_verb(self, tmp_path: Path, capsys):
        """Rotation event emits ci.oidc.jti.store_rotated to the audit log."""
        harness, audit_path = _make_harness(tmp_path)
        jti_path = harness / "oidc_jti_seen.json"
        jti_path.write_text("CORRUPTED", encoding="utf-8")

        _check_and_record_jti("new-jti-3", harness_dir=harness, audit_path=audit_path)

        # Read audit log
        lines = [
            l.strip() for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()
        ]
        verbs = []
        for line in lines:
            try:
                verbs.append(json.loads(line).get("verb", ""))
            except json.JSONDecodeError:
                pass
        assert "ci.oidc.jti.store_rotated" in verbs, (
            f"Expected ci.oidc.jti.store_rotated in audit verbs, got: {verbs!r}"
        )


# ---------------------------------------------------------------------------
# B. Corrupted JTI file → replay-protection reset (fresh start)
# ---------------------------------------------------------------------------


class TestCorruptedJtiResetsFresh:
    def test_corrupted_jti_allows_new_jti_after_rotation(
        self, tmp_path: Path, capsys
    ):
        """After rotating a corrupt file, the function returns None (fresh start)."""
        harness, audit_path = _make_harness(tmp_path)
        jti_path = harness / "oidc_jti_seen.json"
        jti_path.write_text("NOT JSON AT ALL", encoding="utf-8")

        result = _check_and_record_jti(
            "brand-new-jti", harness_dir=harness, audit_path=audit_path
        )
        assert result is None, (
            "Expected None (fresh start / accepted) after corrupt file rotation, "
            f"got {result!r}"
        )


# ---------------------------------------------------------------------------
# C. Missing JTI file → no WARNING, fresh start (original behavior)
# ---------------------------------------------------------------------------


class TestMissingJtiFileNoWarning:
    def test_missing_jti_file_no_warning(self, tmp_path: Path, capsys):
        """A missing oidc_jti_seen.json produces no WARNING — it's a fresh install."""
        harness, audit_path = _make_harness(tmp_path)
        # Do NOT create jti_path

        result = _check_and_record_jti(
            "first-jti", harness_dir=harness, audit_path=audit_path
        )
        captured = capsys.readouterr()
        assert "WARNING" not in captured.err, (
            f"Unexpected WARNING for missing (not corrupted) jti file: {captured.err!r}"
        )
        assert result is None, f"Expected None (fresh start), got {result!r}"


# ---------------------------------------------------------------------------
# D. Valid JTI file with known JTI → replay rejected (regression)
# ---------------------------------------------------------------------------


class TestValidJtiFileReplayRejected:
    def test_replay_rejected_for_known_jti(self, tmp_path: Path):
        """A valid JTI file with a known JTI returns CiOidcJtiReplayed (regression)."""
        harness, audit_path = _make_harness(tmp_path)
        jti_path = harness / "oidc_jti_seen.json"
        jti_path.write_text(
            json.dumps({"seen": ["already-consumed-jti"]}) + "\n",
            encoding="utf-8",
        )

        from lib.ci_provenance import CiOidcJtiReplayed  # type: ignore[import]
        result = _check_and_record_jti(
            "already-consumed-jti", harness_dir=harness, audit_path=audit_path
        )
        assert isinstance(result, CiOidcJtiReplayed), (
            f"Expected CiOidcJtiReplayed for replayed JTI, got {result!r}"
        )

    def test_new_jti_in_valid_file_returns_none(self, tmp_path: Path):
        """A valid JTI file that does NOT contain the new JTI → returns None (accepted)."""
        harness, audit_path = _make_harness(tmp_path)
        jti_path = harness / "oidc_jti_seen.json"
        jti_path.write_text(
            json.dumps({"seen": ["other-jti"]}) + "\n",
            encoding="utf-8",
        )

        result = _check_and_record_jti(
            "fresh-jti", harness_dir=harness, audit_path=audit_path
        )
        assert result is None, (
            f"Expected None (fresh jti accepted), got {result!r}"
        )


# ---------------------------------------------------------------------------
# E. ci.oidc.jti.store_rotated in KNOWN_VERBS
# ---------------------------------------------------------------------------


class TestStoreRotatedInKnownVerbs:
    def test_store_rotated_verb_in_known_verbs(self):
        """ci.oidc.jti.store_rotated must be in KNOWN_VERBS (§12.7 registry)."""
        from lib.audit import KNOWN_VERBS  # type: ignore[import]
        assert "ci.oidc.jti.store_rotated" in KNOWN_VERBS, (
            "ci.oidc.jti.store_rotated missing from KNOWN_VERBS in audit.py. "
            "P2-A5 requires this verb to be registered so strict mode "
            "(HARNESS_STRICT_VERB_REGISTRY=1) does not reject it."
        )
