"""S01-A.2 review-fix (P1): the production `scripts/migrate_state.py`
CLI must wire `audit_path` into `state_migrate.migrate_file` so that a
real `--forward` migration emits exactly one `verb=migrate.state_v2`
audit entry per design §1.2. `--dry-run` stays silent (no I/O).

Pre-fix: `migrate_state.py:74` invoked `migrate_file(target, direction=...)`
without `audit_path=...`, so the audit line was never written by the
production code path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _v0_state(automation_mode: str | None = "chain") -> dict:
    state = {
        "phase": "discuss",
        "approved": False,
        "auto_selected": [],
        "verification": [],
        "updated_at": "2026-05-15T00:00:00Z",
        "updated_by": "test",
    }
    if automation_mode is not None:
        state["automation_mode"] = automation_mode
    return state


def _make_repo(tmp_path: Path, *, automation_mode: str | None = "chain") -> tuple[Path, Path]:
    """Create a .scratch + .harness layout with a v0 state file. Return
    (target, audit_path)."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    (tmp_path / ".harness").mkdir()
    target = scratch / "phase-state.json"
    target.write_text(json.dumps(_v0_state(automation_mode)) + "\n", encoding="utf-8")
    audit_path = tmp_path / ".harness" / "audit.log"
    return target, audit_path


def test_cli_forward_emits_migrate_state_v2_audit_entry(tmp_path: Path, monkeypatch):
    import migrate_state

    target, audit_path = _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    rc = migrate_state.main(["--forward", "--target", str(target)])
    assert rc == 0
    assert audit_path.exists(), "production CLI did not write audit log"

    entries = [json.loads(ln) for ln in audit_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    migrate_entries = [e for e in entries if e.get("verb") == "migrate.state_v2"]
    assert len(migrate_entries) == 1
    entry = migrate_entries[0]
    assert "before_sha256" in entry and len(entry["before_sha256"]) == 64
    assert "after_sha256" in entry and len(entry["after_sha256"]) == 64
    assert entry["before_sha256"] != entry["after_sha256"]


def test_cli_dry_run_does_not_emit_audit_entry(tmp_path: Path, monkeypatch, capsys):
    """--dry-run prints to stdout but MUST NOT touch the audit log."""
    import migrate_state

    target, audit_path = _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    rc = migrate_state.main(["--forward", "--target", str(target), "--dry-run"])
    assert rc == 0
    assert not audit_path.exists(), "dry-run leaked an audit log entry"
    # stdout has the canonical v2 bytes.
    captured = capsys.readouterr()
    assert "\"execution_mode\": \"phase_autopilot\"" in captured.out


def test_cli_reverse_does_not_emit_migrate_state_v2(tmp_path: Path, monkeypatch):
    """`--reverse` is a v2→v0 transform, NOT the read-time migration that
    §1.2 audits. The verb is `migrate.state_v2`, not `migrate.state_v0`."""
    import migrate_state
    from lib import state_migrate

    target, audit_path = _make_repo(tmp_path, automation_mode="chain")
    monkeypatch.chdir(tmp_path)

    # First bring it to v2 (this WILL write an audit entry).
    migrate_state.main(["--forward", "--target", str(target)])

    # Then reverse it. Must not add another `verb=migrate.state_v2` entry.
    pre_lines = audit_path.read_text(encoding="utf-8").splitlines()
    rc = migrate_state.main(["--reverse", "--target", str(target)])
    assert rc == 0
    post_lines = audit_path.read_text(encoding="utf-8").splitlines()
    new_entries = [json.loads(ln) for ln in post_lines[len(pre_lines):] if ln.strip()]
    assert not any(e.get("verb") == "migrate.state_v2" for e in new_entries)


def test_cli_forward_noop_emits_no_duplicate_audit_entry(tmp_path: Path, monkeypatch):
    """Re-running --forward on an already-v2 target is a no-op and must
    NOT spuriously double-emit the migration audit entry."""
    import migrate_state

    target, audit_path = _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    migrate_state.main(["--forward", "--target", str(target)])
    first_count = len([
        ln for ln in audit_path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and json.loads(ln).get("verb") == "migrate.state_v2"
    ])

    migrate_state.main(["--forward", "--target", str(target)])
    second_count = len([
        ln for ln in audit_path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and json.loads(ln).get("verb") == "migrate.state_v2"
    ])
    assert first_count == 1
    assert second_count == 1, "no-op --forward double-emitted migrate.state_v2"
