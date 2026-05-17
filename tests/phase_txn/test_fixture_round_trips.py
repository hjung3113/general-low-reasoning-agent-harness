"""S01-D.2: each pinned §9.1 fixture dispatches to its documented row.

Copies the on-disk fixture into a `tmp_path` scratch, invokes
`phase_txn.recover()` with a fresh lock, and asserts the returned
(`row`, `exit_code`) tuple matches the design table. Differs from
`test_recovery_matrix.py` — that file builds the layout in-memory; this
file pins the on-disk fixture bytes (S06 and S13 will reuse them).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lib import phase_lock, phase_txn


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "crash"


@pytest.mark.parametrize(
    ("fixture_name", "expected_row", "expected_exit"),
    [
        ("01_quiescent", 1, 0),
        ("02_orphan_tmp", 2, 0),
        ("03_state_accepted_audit_durable", 3, 0),
        ("04_tmp_present_audit_durable", 4, 0),
        ("05_journal_only_before", 5, 0),
        ("06_journal_and_tmp_before", 6, 0),
        ("07_roll_forward", 7, 0),
        ("08a_finalize_no_tmp", 8, 0),
        ("08b_finalize_with_tmp", 8, 0),
        ("09_undecidable_state_hash", 9, 14),
        ("10_corrupt_journal_tmp", 10, 14),
        ("11_corrupt_journal_only", 11, 14),
        ("12_audit_partial_write", 12, 14),
        ("13_malformed_journal", 13, 14),
    ],
)
def test_fixture_dispatches_to_expected_row(
    fixture_name: str, expected_row: int, expected_exit: int, tmp_path: Path
):
    src = FIXTURES / fixture_name
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    audit_dir = tmp_path / ".harness"
    audit_dir.mkdir()
    audit_path = audit_dir / "audit.log"

    # Stage scratch artefacts from the fixture.
    for name in ("phase-state.json", "phase-state.json.tmp", "phase-state.json.journal"):
        if (src / name).exists():
            shutil.copy2(src / name, scratch / name)
    if (src / "audit.log").exists():
        shutil.copy2(src / "audit.log", audit_path)
    else:
        audit_path.write_text("", encoding="utf-8")

    handle = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        result = phase_txn.recover(scratch, audit_path=audit_path, lock=handle)
    finally:
        phase_lock.release_primary(handle)

    assert result.row == expected_row, f"{fixture_name} -> row {result.row}, decision={result.decision}"
    assert result.exit_code == expected_exit
