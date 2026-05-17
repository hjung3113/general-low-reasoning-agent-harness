"""harness verify --audit CLI verb implementation (design §12.7, §12.9, S06).

Runs the full audit chain verification against the live repo or a fixture
directory. Exits 0 on success, 10 on chain failure, 5 on BOM error.

Grammar (§12.9):
  harness verify --audit [--fixture <dir>]

  --fixture <dir>: override source to <dir>/audit.log + <dir>/audit.log.N
    State file read from <dir>/state.json if present (audit-only otherwise).
    Anchor file read from <dir>/.audit-tip.json if present; otherwise
    anchor checks are skipped (anchor_skipped=true in report).
    Implies no-network; refuses --release.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .audit_chain import (
    AuditBomError,
    AuditChainError,
    verify_chain,
)


def cmd_verify_audit(args: Any, root: Path) -> int:
    """Entry point for `harness verify --audit [--fixture <dir>]`.

    Returns exit code (0 = ok, 5 = BOM error, 10 = chain failure).
    """
    fixture_dir: Path | None = None
    if args.verify_fixture is not None:
        fixture_dir = Path(args.verify_fixture).resolve()
        audit_path = fixture_dir / "audit.log"
        rotation_dir: Path | None = fixture_dir
    else:
        # Live repo: default to .harness/audit.log
        audit_path = root / ".harness" / "audit.log"
        rotation_dir = audit_path.parent if audit_path.parent.exists() else None

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
            f"Fix: run 'harness verify --audit --fixture <dir>' to diagnose.",
            file=sys.stderr,
        )
        return 10

    if result.ok:
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
    else:
        # Chain failure
        err = result.error
        err_msg = str(err) if err else "unknown chain error"
        print(
            f"Error (exit 10): audit chain verification failed.\n"
            f"{err_msg}\n"
            f"Fix: run 'harness verify --audit --fixture <dir>' to diagnose the "
            f"tampered entry. Check entries walked={result.entries_walked}.",
            file=sys.stderr,
        )
        return 10


__all__ = ["cmd_verify_audit"]
