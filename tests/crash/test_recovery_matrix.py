"""S06-audit-chain: crash recovery matrix tests (design §3.8 + §12.5 #2).

Exercises all 12 pinned crash fixtures from tests/fixtures/crash/01..12/
against phase_txn.recover() AND the new chain verifier.

The fixtures hold pre-crash artefacts at the top level of each directory
(phase-state.json, phase-state.json.tmp, phase-state.json.journal, audit.log).
This test copies them into a properly structured scratch + audit directory.

Each fixture has a known expected outcome:
  - row: design §3.8 table row id
  - decision: machine-readable decision string
  - exit_code: 0 or 14
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lib import phase_lock, phase_txn

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "crash"


def _setup_fixture(fixture_name: str, tmp_path: Path) -> tuple[Path, Path]:
    """Copy fixture into structured scratch + audit layout.

    Returns (scratch, audit_path).
    The fixture holds all files flat at top-level; we stage them into
    `tmp_path/.scratch/` (for state artefacts) and compute audit_path
    as `tmp_path/.scratch/audit.log`.
    """
    src = FIXTURE_DIR / fixture_name
    if not src.exists():
        pytest.skip(f"fixture missing: {fixture_name}")
    scratch = tmp_path / ".scratch"
    scratch.mkdir()

    # Copy state artefacts
    for name in ("phase-state.json", "phase-state.json.tmp", "phase-state.json.journal"):
        if (src / name).exists():
            shutil.copy2(src / name, scratch / name)

    # Audit log lives co-located with scratch artefacts for simplicity
    audit_path = scratch / "audit.log"
    if (src / "audit.log").exists():
        shutil.copy2(src / "audit.log", audit_path)
    else:
        audit_path.write_text("", encoding="utf-8")

    return scratch, audit_path


def _recover(scratch: Path, audit_path: Path) -> phase_txn.RecoveryResult:
    """Acquire lock, run recover(), release lock. Returns the RecoveryResult."""
    handle = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        return phase_txn.recover(scratch, audit_path=audit_path, lock=handle)
    finally:
        phase_lock.release_primary(handle)


# ---------------------------------------------------------------------------
# Row 1: quiescent (J=0, T=0, A=0)
# ---------------------------------------------------------------------------

class TestRow1Quiescent:
    def test_01_quiescent(self, tmp_path):
        scratch, audit_path = _setup_fixture("01_quiescent", tmp_path)
        result = _recover(scratch, audit_path)
        assert result.row == 1
        assert result.exit_code == 0
        assert result.decision == "quiescent"


# ---------------------------------------------------------------------------
# Row 2: orphan tmp (J=0, T=1, A=0)
# ---------------------------------------------------------------------------

class TestRow2OrphanTmp:
    def test_02_orphan_tmp(self, tmp_path):
        scratch, audit_path = _setup_fixture("02_orphan_tmp", tmp_path)
        result = _recover(scratch, audit_path)
        assert result.row == 2
        assert result.exit_code == 0
        assert "unlink" in result.decision or "orphan" in result.decision
        assert not (scratch / "phase-state.json.tmp").exists()


# ---------------------------------------------------------------------------
# Row 3: state accepted, audit durable (J=0, T=0, A=1 with after)
# ---------------------------------------------------------------------------

class TestRow3StateAccepted:
    def test_03_state_accepted(self, tmp_path):
        scratch, audit_path = _setup_fixture("03_state_accepted_audit_durable", tmp_path)
        result = _recover(scratch, audit_path)
        assert result.row == 3
        assert result.exit_code == 0
        assert "accept" in result.decision


# ---------------------------------------------------------------------------
# Row 4: tmp present + audit durable (J=0, T=1, A=1 with after)
# ---------------------------------------------------------------------------

class TestRow4TmpPresentAuditDurable:
    def test_04_tmp_present_audit_durable(self, tmp_path):
        scratch, audit_path = _setup_fixture("04_tmp_present_audit_durable", tmp_path)
        result = _recover(scratch, audit_path)
        assert result.row == 4
        assert result.exit_code == 0
        assert not (scratch / "phase-state.json.tmp").exists()


# ---------------------------------------------------------------------------
# Row 5: journal only, before state (J=1, T=0, A=0, state==before)
# ---------------------------------------------------------------------------

class TestRow5JournalOnlyBefore:
    def test_05_journal_only_before(self, tmp_path):
        scratch, audit_path = _setup_fixture("05_journal_only_before", tmp_path)
        result = _recover(scratch, audit_path)
        assert result.row == 5
        assert result.exit_code == 0
        assert "rollback" in result.decision
        assert not (scratch / "phase-state.json.journal").exists()


# ---------------------------------------------------------------------------
# Row 6: journal + tmp, no audit (J=1, T=1, A=0, state==before)
# ---------------------------------------------------------------------------

class TestRow6JournalAndTmpBefore:
    def test_06_journal_and_tmp_before(self, tmp_path):
        scratch, audit_path = _setup_fixture("06_journal_and_tmp_before", tmp_path)
        result = _recover(scratch, audit_path)
        assert result.row == 6
        assert result.exit_code == 0
        assert "rollback" in result.decision
        assert not (scratch / "phase-state.json.journal").exists()
        assert not (scratch / "phase-state.json.tmp").exists()


# ---------------------------------------------------------------------------
# Row 7: roll forward (J=1, T=1, A=1, state==before, sha(tmp)==after)
# ---------------------------------------------------------------------------

class TestRow7RollForward:
    def test_07_roll_forward(self, tmp_path):
        scratch, audit_path = _setup_fixture("07_roll_forward", tmp_path)
        result = _recover(scratch, audit_path)
        assert result.row == 7
        assert result.exit_code == 0
        assert "roll_forward" in result.decision or "forward" in result.decision
        assert not (scratch / "phase-state.json.journal").exists()


# ---------------------------------------------------------------------------
# Row 8a: finalize no tmp (J=1, T=0, A=1, state==after)
# ---------------------------------------------------------------------------

class TestRow8aFinalizeNoTmp:
    def test_08a_finalize_no_tmp(self, tmp_path):
        scratch, audit_path = _setup_fixture("08a_finalize_no_tmp", tmp_path)
        result = _recover(scratch, audit_path)
        assert result.row == 8
        assert result.exit_code == 0
        assert "finalize" in result.decision
        assert not (scratch / "phase-state.json.journal").exists()


# ---------------------------------------------------------------------------
# Row 8b: finalize with tmp (J=1, T=1, A=1, state==after)
# ---------------------------------------------------------------------------

class TestRow8bFinalizeWithTmp:
    def test_08b_finalize_with_tmp(self, tmp_path):
        scratch, audit_path = _setup_fixture("08b_finalize_with_tmp", tmp_path)
        result = _recover(scratch, audit_path)
        assert result.row == 8
        assert result.exit_code == 0
        assert not (scratch / "phase-state.json.tmp").exists()


# ---------------------------------------------------------------------------
# Row 9: undecidable (J=1, state not in {before, after})
# ---------------------------------------------------------------------------

class TestRow9Undecidable:
    def test_09_undecidable(self, tmp_path):
        scratch, audit_path = _setup_fixture("09_undecidable_state_hash", tmp_path)
        result = _recover(scratch, audit_path)
        assert result.row == 9
        assert result.exit_code == 14


# ---------------------------------------------------------------------------
# Row 10: corruption (J=1, T=1, A=0, state!=before)
# ---------------------------------------------------------------------------

class TestRow10Corrupt:
    def test_10_corrupt_journal_tmp(self, tmp_path):
        scratch, audit_path = _setup_fixture("10_corrupt_journal_tmp", tmp_path)
        result = _recover(scratch, audit_path)
        assert result.row == 10
        assert result.exit_code == 14


# ---------------------------------------------------------------------------
# Row 11: corruption (J=1, T=0, A=0, state!=before)
# ---------------------------------------------------------------------------

class TestRow11CorruptJournalOnly:
    def test_11_corrupt_journal_only(self, tmp_path):
        scratch, audit_path = _setup_fixture("11_corrupt_journal_only", tmp_path)
        result = _recover(scratch, audit_path)
        assert result.row == 11
        assert result.exit_code == 14


# ---------------------------------------------------------------------------
# Row 12: audit partial write (§12.5 #2)
# ---------------------------------------------------------------------------

class TestRow12AuditPartialWrite:
    def test_12_audit_partial_write(self, tmp_path):
        scratch, audit_path = _setup_fixture("12_audit_partial_write", tmp_path)
        result = _recover(scratch, audit_path)
        assert result.row == 12
        assert result.exit_code == 14


# ---------------------------------------------------------------------------
# Row 13: malformed journal (out-of-band)
# ---------------------------------------------------------------------------

class TestRow13MalformedJournal:
    def test_13_malformed_journal(self, tmp_path):
        scratch, audit_path = _setup_fixture("13_malformed_journal", tmp_path)
        result = _recover(scratch, audit_path)
        assert result.row == 13
        assert result.exit_code == 14

