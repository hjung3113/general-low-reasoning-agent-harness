"""E2E: harness phase approve from a real pty runs the [y/N] prompt.

Two tests:
  1. Real pty — [y/N] prompt is displayed, 'y' advances phase to approved,
     audit.log contains 'soft_tty'.
  2. Non-TTY stdin — command exits with code 17 and prints 'terminal'/'tty'
     to stderr.

Bootstrap approach: `commit_transaction` seeds state + audit (consistent
plain JSONL — no state-trust preflight, ADR-0002).
"""
from __future__ import annotations

import json
import os
import pty
import select
import subprocess
import sys
from pathlib import Path

import pytest

# ── path setup ────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib import phase_lock, phase_txn  # noqa: E402


_TEST_EMAIL = "test@example.com"

_INSTALL_RECORD = {
    "harness_version": "v0.8.3",
    "installed_at": "2026-05-19T00:00:00Z",
    "adapters": ["roo"],
    "git_present_at_install": True,
}

_SEED_STATE = {
    "phase": "plan",
    "approved": False,
    "approved_at": None,
    "approved_by": None,
    "execution_mode": "manual",
    "state_schema_version": 2,
}


def _bootstrap_design_phase(harness_root: Path) -> None:
    """Set up a minimal harness directory for a real `phase approve` run.

    Steps:
      1. Write .harness/install-record.json with TEST_EMAIL as approver.
      2. Create .scratch/ and seed phase-state via commit_transaction.
    """
    harness_dir = harness_root / ".harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    scratch = harness_root / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)

    # Step 1 — install-record
    (harness_dir / "install-record.json").write_text(
        json.dumps(_INSTALL_RECORD, indent=2, sort_keys=True) + "\n"
    )

    # Step 2 — seed state + audit via commit_transaction (consistent plain JSONL)
    audit_path = harness_dir / "audit.log"
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        req = phase_txn.TxnRequest(
            action="phase.set",
            before_state=None,
            after_state=_SEED_STATE,
            audit_entry_draft={
                "verb": "phase.set",
                "by": "seed",
                "args": {"phase": "plan"},
            },
        )
        phase_txn.commit_transaction(
            scratch, lock=lock, request=req, audit_path=audit_path
        )
    finally:
        phase_lock.release_primary(lock)


# ── tests ─────────────────────────────────────────────────────────────────

@pytest.mark.skipif(os.name != "posix", reason="pty not available on Windows")
@pytest.mark.integration
def test_phase_approve_y_advances_under_real_pty(tmp_path):
    harness_root = tmp_path / "proj"
    harness_root.mkdir()
    _bootstrap_design_phase(harness_root)

    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "harness.py"),
            "phase", "approve",
            "--by", _TEST_EMAIL,
        ],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=harness_root,
        close_fds=True,
    )
    os.close(slave_fd)

    deadline = 5.0
    buf = b""
    while deadline > 0:
        r, _, _ = select.select([master_fd], [], [], 0.2)
        if r:
            try:
                buf += os.read(master_fd, 4096)
            except OSError:
                break
            if b"[y/N]" in buf:
                break
        deadline -= 0.2

    assert b"[y/N]" in buf, f"[y/N] prompt not seen; got: {buf!r}"

    os.write(master_fd, b"y\n")

    try:
        rc = proc.wait(timeout=5)
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass

    assert rc == 0, f"expected exit 0, got {rc}"

    audit = harness_root / ".harness" / "audit.log"
    assert audit.exists(), "audit.log not created"
    text = audit.read_text()
    assert "soft_tty" in text, f"'soft_tty' not found in audit.log; contents: {text!r}"


@pytest.mark.integration
def test_phase_approve_non_tty_halts_with_exit_17_e2e(tmp_path):
    harness_root = tmp_path / "proj"
    harness_root.mkdir()
    _bootstrap_design_phase(harness_root)

    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "harness.py"),
            "phase", "approve",
            "--by", _TEST_EMAIL,
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        cwd=harness_root,
        timeout=5,
    )
    assert proc.returncode == 17, (
        f"expected exit 17, got {proc.returncode}; "
        f"stderr: {proc.stderr!r}"
    )
    stderr_lower = proc.stderr.lower()
    assert b"terminal" in stderr_lower or b"tty" in stderr_lower, (
        f"expected 'terminal' or 'tty' in stderr; got: {proc.stderr!r}"
    )
