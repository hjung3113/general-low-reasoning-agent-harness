"""Enforce that docs/ARTIFACTS.md is current — runs generate_artifacts_doc.py --check.

This test is the CI gate for issue #14 (M6-1).  The generator is deterministic
and emits no wall-clock timestamps, so the check is stable across machines.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GENERATOR = _REPO_ROOT / "scripts" / "generate_artifacts_doc.py"
_ARTIFACTS_MD = _REPO_ROOT / "docs" / "ARTIFACTS.md"


def test_artifacts_md_is_current():
    """docs/ARTIFACTS.md must match what the generator would produce.

    Gate after #14: `python3 scripts/generate_artifacts_doc.py --check` exits 0;
    deterministic re-run produces byte-identical output.
    """
    result = subprocess.run(
        [sys.executable, str(_GENERATOR), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"docs/ARTIFACTS.md is stale. Run: python3 scripts/generate_artifacts_doc.py\n"
        f"stderr:\n{result.stderr}"
    )


def test_artifacts_md_no_timestamp():
    """Generated doc must not contain wall-clock timestamps."""
    import re
    content = _ARTIFACTS_MD.read_text(encoding="utf-8")
    # ISO datetime pattern like 2026-05-23T12:34:56 would be a timestamp.
    pattern = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
    matches = pattern.findall(content)
    assert matches == [], f"Found wall-clock timestamps in ARTIFACTS.md: {matches}"


def test_artifacts_md_file_count_matches_manifest():
    """File count in header matches actual manifest."""
    import json
    manifest = json.loads((_REPO_ROOT / "harness" / "manifest.json").read_text(encoding="utf-8"))
    expected = len(manifest["files"])
    content = _ARTIFACTS_MD.read_text(encoding="utf-8")
    assert f"Total files: **{expected}**" in content, (
        f"Expected 'Total files: **{expected}**' in ARTIFACTS.md"
    )
