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
    AuditChainTruncationError,
    verify_chain,
)


def cmd_verify_audit(args: Any, root: Path) -> int:
    """Entry point for `harness verify --audit [--fixture <dir>]`.

    Returns exit code (0 = ok, 5 = BOM error, 10 = chain failure).

    P1-5: After a successful chain walk, compare the live audit tail's
    entry_hash to the out-of-repo anchor's recorded tip (if present).
    Mismatch → AuditChainTruncationError (exit 10 audit_chain_truncation).
    Anchor absent → warn but proceed (acceptable for fresh repos and all
    --fixture invocations).

    P2-4: If --fixture <dir> is given but the directory or audit.log does
    not exist, exit 10 immediately with a clear Fix: hint.
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

    # P1-5: anchor integration — compare live tail to out-of-repo anchor
    anchor_skipped = False
    if fixture_dir is None:
        # Live repo mode: attempt anchor check
        try:
            from .audit_anchor import (
                AnchorError,
                AnchorMissingError,
                read_anchor,
                anchor_path,
            )
            repo_root = root
            a_path = anchor_path(repo_root)
            if a_path.exists():
                anchor = read_anchor(repo_root)
                if result.final_tip_hash is not None:
                    if anchor.audit_tip_entry_hash != result.final_tip_hash:
                        raise AuditChainTruncationError(
                            f"Anchor tip mismatch: anchor.audit_tip_entry_hash="
                            f"{anchor.audit_tip_entry_hash!r} but live audit tail "
                            f"entry_hash={result.final_tip_hash!r}. "
                            f"The audit log may have been truncated or replayed. "
                            f"Fix: run 'harness anchor repair' to re-anchor the "
                            f"current state, or investigate the log history."
                        )
            else:
                # Anchor absent — warn but proceed (fresh repo)
                anchor_skipped = True
        except AuditChainTruncationError:
            raise
        except AnchorMissingError:
            anchor_skipped = True
        except Exception:
            # Anchor subsystem unavailable — degrade gracefully
            anchor_skipped = True
    else:
        # --fixture mode: anchor not expected
        anchor_skipped = True

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
    if anchor_skipped:
        lines.append(f"  anchor check:             skipped (anchor absent or fixture mode)")
    else:
        lines.append(f"  anchor check:             OK")
    print("\n".join(lines))
    return 0


__all__ = ["cmd_verify_audit"]
