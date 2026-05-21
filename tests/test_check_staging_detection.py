"""T5 — harness check staging detection (age-gated, dedupe'd).

Test cases:
1. No staging -> no warning
2. Fresh staging (age < 600s, no .aborted) -> no warning (live-install false-positive guard)
3. Stale staging + journal -> warning emitted with runid + age
4. .aborted marker present -> warning regardless of age
5. Multiple stale dirs -> one warning per dir; output has all runids
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.check import _scan_stale_staging_dirs  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    harness = target / ".harness"
    harness.mkdir()
    return target


def _make_staging_dir(harness: Path, runid: str, age_secs: float | None = None, aborted: bool = False) -> Path:
    """Create a staging dir with journal. Optionally backdate and/or add .aborted."""
    staging_dir = harness / f".staging-{runid}"
    staging_dir.mkdir()
    journal = harness / f".staging-{runid}.journal.jsonl"
    journal.write_text("", encoding="utf-8")

    if aborted:
        import json
        (staging_dir / ".aborted").write_text(
            json.dumps({"failed_rel": "test", "error": "simulated"}),
            encoding="utf-8",
        )

    if age_secs is not None:
        old_mtime = time.time() - age_secs
        os.utime(str(staging_dir), (old_mtime, old_mtime))

    return staging_dir


# ---------------------------------------------------------------------------
# Test 1: No staging -> no warning
# ---------------------------------------------------------------------------


def test_no_staging_no_warning(tmp_path):
    """T5-1: no staging dirs -> _scan_stale_staging_dirs returns empty list."""
    target = _make_target(tmp_path)
    result = _scan_stale_staging_dirs(target)
    assert result == [], f"Expected empty list, got {result}"


# ---------------------------------------------------------------------------
# Test 2: Fresh staging (age < 600s, no .aborted) -> no warning
# ---------------------------------------------------------------------------


def test_fresh_staging_no_warning(tmp_path):
    """T5-2: fresh staging dir (age < 600s, no .aborted) -> not stale -> no warning."""
    target = _make_target(tmp_path)
    harness = target / ".harness"

    # Create staging dir with very recent mtime (age = 1 second)
    _make_staging_dir(harness, "fresh-runid-001", age_secs=1)

    result = _scan_stale_staging_dirs(target)
    assert result == [], f"Fresh staging should not trigger warning: {result}"


# ---------------------------------------------------------------------------
# Test 3: Stale staging + journal -> warning with runid + age
# ---------------------------------------------------------------------------


def test_stale_staging_emits_warning(tmp_path):
    """T5-3: stale staging dir (age >= 600s) + journal -> warning emitted with runid."""
    target = _make_target(tmp_path)
    harness = target / ".harness"

    runid = "99999-20260521T000000Z-stale01"
    _make_staging_dir(harness, runid, age_secs=700)  # 700s > 600s threshold

    result = _scan_stale_staging_dirs(target)
    assert len(result) == 1, f"Expected 1 stale dir, got {len(result)}: {result}"
    found_path, found_runid, found_age = result[0]
    assert found_runid == runid
    assert found_age is not None and found_age >= 600


# ---------------------------------------------------------------------------
# Test 4: .aborted marker -> warning regardless of age
# ---------------------------------------------------------------------------


def test_aborted_marker_emits_warning_regardless_of_age(tmp_path):
    """T5-4: .aborted marker -> stale (regardless of age) -> warning emitted."""
    target = _make_target(tmp_path)
    harness = target / ".harness"

    runid = "99999-20260521T000001Z-aborted"
    # Very fresh dir (age=1s) but has .aborted marker
    _make_staging_dir(harness, runid, age_secs=1, aborted=True)

    result = _scan_stale_staging_dirs(target)
    assert len(result) == 1, f"Expected 1 result (aborted marker), got {result}"
    assert result[0][1] == runid


# ---------------------------------------------------------------------------
# Test 5: Multiple stale dirs -> one warning per dir
# ---------------------------------------------------------------------------


def test_multiple_stale_dirs_one_warning_each(tmp_path, capsys):
    """T5-5 (FIX-B v0.9.7): two stale dirs -> one summary warning with N count + oldest runid."""
    from lib.check import _print_stale_staging_warnings

    target = _make_target(tmp_path)
    harness = target / ".harness"

    runid1 = "11111-20260521T000000Z-stale01"
    runid2 = "22222-20260521T000001Z-stale02"
    _make_staging_dir(harness, runid1, age_secs=700)
    _make_staging_dir(harness, runid2, age_secs=800)  # older

    result = _scan_stale_staging_dirs(target)
    assert len(result) == 2, f"Expected 2 stale dirs, got {len(result)}: {result}"

    found_runids = {r[1] for r in result}
    assert runid1 in found_runids
    assert runid2 in found_runids

    # FIX-B: N>=2 prints single summary line with "{N}개" + "oldest runid=...".
    n = _print_stale_staging_warnings(target)
    assert n == 2
    captured = capsys.readouterr()
    out = captured.out
    assert "2개 중단된 설치 감지" in out, out
    # The oldest (age=800) is runid2.
    assert f"oldest runid={runid2}" in out, out
    assert out.count("중단된 설치 감지") == 1, "expected single summary line"


# ---------------------------------------------------------------------------
# Integration: staging without journal -> not detected (no journal = not harness staging)
# ---------------------------------------------------------------------------


def test_staging_without_journal_ignored(tmp_path):
    """T5-extra: staging dir without journal sibling -> not detected as harness staging."""
    target = _make_target(tmp_path)
    harness = target / ".harness"

    runid = "99999-20260521T000002Z-nojrnl"
    staging_dir = harness / f".staging-{runid}"
    staging_dir.mkdir()
    # No journal file!

    # Backdate
    old_mtime = time.time() - 700
    os.utime(str(staging_dir), (old_mtime, old_mtime))

    result = _scan_stale_staging_dirs(target)
    assert result == [], "Staging without journal should be ignored"
