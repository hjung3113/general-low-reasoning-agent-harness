"""FIX-1 — state_cli.run_repair exit-code contract.

Test cases:
1. No-op (nothing to repair) → rc=0
2. Sentinel-present finalization → rc=0 (clean recovery, no quarantine)
3. Orphan-pending quarantine → rc=1
4. Catastrophic: repair() raises unexpected exception → rc=2
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.state_cli import run_repair  # noqa: E402
from lib.state_repair import RepairReport  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    (target / ".harness").mkdir()
    # Minimal planning structure so repair() doesn't bail early
    planning = target / ".planning"
    planning.mkdir()
    (planning / "ROADMAP.md").write_text("# Roadmap\n", encoding="utf-8")
    (planning / "STATE.md").write_text("# State\n", encoding="utf-8")
    return target


def _make_stream() -> io.StringIO:
    return io.StringIO()


# ---------------------------------------------------------------------------
# Test 1: no-op → rc=0
# ---------------------------------------------------------------------------


def test_run_repair_noop_returns_0(tmp_path):
    """FIX-1-1: no staging artifacts, canonical files → rc=0."""
    target = _make_target(tmp_path)
    stream = _make_stream()
    rc = run_repair(root=target, stream=stream)
    assert rc == 0, f"Expected rc=0 on no-op, got rc={rc}"
    output = stream.getvalue()
    assert "nothing to repair" in output or "warnings" in output or "updated" in output or output.strip() == "" or "nothing to repair" in output


# ---------------------------------------------------------------------------
# Test 2: sentinel-present finalization → rc=0
# ---------------------------------------------------------------------------


def test_run_repair_clean_finalize_returns_0(tmp_path):
    """FIX-1-2: sentinel present, no quarantine → rc=0."""
    target = _make_target(tmp_path)
    harness = target / ".harness"
    runid = "11111-20260521T000000Z-aaa111"

    # Write pending sidecar + sentinel (clean finalize scenario)
    pending_path = harness / f"installed-manifest.json.pending-{runid}"
    pending_path.write_text(
        json.dumps({"version": "0.9.7-test", "schema_version": 2, "files": {}}),
        encoding="utf-8",
    )
    sentinel = harness / f".staging-{runid}.complete"
    sentinel.write_bytes(b"")

    stream = _make_stream()
    rc = run_repair(root=target, stream=stream)
    assert rc == 0, f"Expected rc=0 on clean finalize, got rc={rc}"


# ---------------------------------------------------------------------------
# Test 3: orphan-pending quarantine → rc=1
# ---------------------------------------------------------------------------


def test_run_repair_quarantine_returns_1(tmp_path):
    """FIX-1-3: orphan pending sidecar (no journal/staging/sentinel) → rc=1."""
    target = _make_target(tmp_path)
    harness = target / ".harness"
    runid = "22222-20260521T000001Z-bbb222"

    # Write orphan pending sidecar only (no staging dir, no sentinel)
    pending_path = harness / f"installed-manifest.json.pending-{runid}"
    pending_path.write_text(
        json.dumps({"version": "0.9.7-test", "schema_version": 2, "files": {}}),
        encoding="utf-8",
    )

    stream = _make_stream()
    rc = run_repair(root=target, stream=stream)
    assert rc == 1, f"Expected rc=1 on quarantine, got rc={rc}\nOutput: {stream.getvalue()}"


# ---------------------------------------------------------------------------
# Test 4: catastrophic exception → rc=2
# ---------------------------------------------------------------------------


def test_run_repair_catastrophic_returns_2(tmp_path):
    """FIX-1-4: repair() raises unexpected exception → rc=2."""
    target = _make_target(tmp_path)

    stream = _make_stream()
    with patch("lib.state_repair.repair", side_effect=RuntimeError("catastrophic test error")):
        rc = run_repair(root=target, stream=stream)

    assert rc == 2, f"Expected rc=2 on catastrophic error, got rc={rc}"
    output = stream.getvalue()
    assert "catastrophic" in output.lower()
