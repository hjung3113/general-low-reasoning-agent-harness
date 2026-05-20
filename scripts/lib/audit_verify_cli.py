"""harness verify --audit CLI verb implementation (design §12.7, §12.9, S06).

Runs the full audit chain verification against the live repo or a fixture
directory. Exits 0 on success, 10 on chain failure, 5 on BOM error,
14 on crash-artefact (0-byte state file).

Grammar (§12.9):
  harness verify --audit [--fixture <dir>]

  --fixture <dir>: override source to <dir>/audit.log + <dir>/audit.log.N
    State file read from <dir>/state.json if present (audit-only otherwise).
    Implies no-network; refuses --release.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .audit_chain import (
    AuditBomError,
    AuditChainError,
    verify_chain,
)
from .state_trust import StateEmptyError, _is_baseline_state


_SCRATCH_ROOT = ".scratch"
_STATE_NAME = "phase-state.json"


def cmd_verify_audit(args: Any, root: Path) -> int:
    """Entry point for `harness verify --audit [--fixture <dir>]`.

    Returns exit code (0 = ok, 5 = BOM error, 10 = chain failure,
    14 = crash-artefact state file).

    P2-4: If --fixture <dir> is given but the directory or audit.log does
    not exist, exit 10 immediately with a clear Fix: hint.

    BUG-1 fix: live-repo only — if .harness/audit.log is missing AND the
    state file shows progression beyond baseline, exit 10 with
    sub_reason=audit_log_missing (mirrors state_trust
    state_advanced_without_audit_evidence).

    BUG-2 fix: live-repo only — if .scratch/phase-state.json is 0 bytes,
    exit 14 (crash artefact, run recover).  Mirrors the StateEmptyError
    path in next/status.
    """
    fixture_dir: Path | None = None
    if args.verify_fixture is not None:
        fixture_dir = Path(args.verify_fixture).resolve()
        # P2-4: validate --fixture path exists
        if not fixture_dir.exists():
            print(
                f"Error (exit 10): --fixture path does not exist: {fixture_dir}\n"
                f"Fix: check the path spelling and re-run "
                f"'harness verify --audit --fixture {fixture_dir}'.",
                file=sys.stderr,
            )
            return 10
        audit_path = fixture_dir / "audit.log"
        if not audit_path.exists():
            print(
                f"Error (exit 10): no audit.log found in --fixture dir {fixture_dir}\n"
                f"Fix: ensure the fixture directory contains audit.log.",
                file=sys.stderr,
            )
            return 10
        rotation_dir: Path | None = fixture_dir
    else:
        # Live repo: default to .harness/audit.log
        audit_path = root / ".harness" / "audit.log"
        rotation_dir = audit_path.parent if audit_path.parent.exists() else None

        # BUG-2 fix: detect 0-byte state file before running chain check.
        state_path = root / _SCRATCH_ROOT / _STATE_NAME
        if state_path.exists():
            if state_path.stat().st_size == 0:
                print(
                    "Error (exit 14): state file is present but empty "
                    "(likely crash artefact).\n"
                    "Fix: run 'harness recover' before any state-mutating verb.",
                    file=sys.stderr,
                )
                return 14

        # BUG-1 fix: if .harness/ is entirely absent, check whether the
        # state file has progressed beyond baseline.  A genuinely fresh
        # install (state missing or at baseline) is fine; advanced state
        # without an audit log is an operator error.
        if rotation_dir is None and state_path.exists():
            try:
                raw = state_path.read_bytes()
                if len(raw) > 0:
                    try:
                        parsed_state = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        parsed_state = None
                    if parsed_state is not None and not _is_baseline_state(parsed_state):
                        print(
                            "Error (exit 10): state file shows progression beyond "
                            "the fresh-install baseline but .harness/audit.log does "
                            "not exist; sub_reason=audit_log_missing.\n"
                            "Fix: run 'harness verify --audit' after restoring "
                            ".harness/audit.log, or run 'harness install' to "
                            "re-initialise from scratch.",
                            file=sys.stderr,
                        )
                        return 10
            except OSError:
                pass  # state file unreadable — let chain check handle it

    try:
        result = verify_chain(audit_path, rotation_dir=rotation_dir)
    except AuditBomError as exc:
        print(
            f"Error (exit 5): BOM detected in audit log.\n"
            f"Fix: run 'harness repair --strip-bom {audit_path}'",
            file=sys.stderr,
        )
        return 5
    except AuditChainError as exc:
        print(
            f"Error (exit 10): audit chain verification failed.\n"
            f"Fix: run 'harness verify --audit --fixture {audit_path.parent}' to diagnose.",
            file=sys.stderr,
        )
        return 10

    if not result.ok:
        # Chain failure
        err = result.error
        err_msg = str(err) if err else "unknown chain error"
        print(
            f"Error (exit 10): audit chain verification failed.\n"
            f"{err_msg}\n"
            f"Fix: run 'harness verify --audit --fixture {audit_path.parent}' to diagnose the "
            f"tampered entry at seq_global around walked={result.entries_walked}.",
            file=sys.stderr,
        )
        return 10

    # Human-readable summary on stdout
    lines = [
        f"audit chain: OK",
        f"  entries walked:           {result.entries_walked}",
        f"  rotation files traversed: {result.rotation_files_traversed}",
    ]
    if result.final_tip_hash:
        lines.append(f"  final tip hash:           {result.final_tip_hash}")
    else:
        lines.append(f"  final tip hash:           (empty log)")
    print("\n".join(lines))
    return 0


__all__ = ["cmd_verify_audit"]
