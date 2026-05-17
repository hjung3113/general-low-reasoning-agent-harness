"""CLI handler for `harness halt-diary clear` (design §5.3 + §12.7).

Wired from ``scripts/harness.py`` argparse dispatch. Follows the standard
pattern from ``scripts/lib/phase_autopilot_cli.py``:

  1. Walk-up for repo root.
  2. Verify audit-tip anchor (fail-closed §12.1).
  3. State-trust preflight.
  4. Acquire primary lock.
  5. Call `halt_diary.run_clear`.
  6. Release lock.
  7. Print result + sys.exit.

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md
Sections: §5.3, §12.7, §1.1
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Paths (CWD-relative, following phase_autopilot_cli.py convention)
# ---------------------------------------------------------------------------

SCRATCH_ROOT = Path(".scratch")
AUDIT_PATH = Path(".harness") / "audit.log"
HARNESS_DIR = Path(".harness")


# ---------------------------------------------------------------------------
# Re-use walk-up + anchor helpers from phase_autopilot_cli
# ---------------------------------------------------------------------------


def _cwd_repo_root() -> Path:
    """Walk up from CWD to the first .git/.harness ancestor."""
    from .phase_autopilot_cli import _walk_up_for_repo_root
    return _walk_up_for_repo_root(Path.cwd())


def _verify_anchor(cwd: Path) -> tuple[bool, int, str]:
    """Verify the out-of-repo audit-tip anchor. Returns (ok, exit_code, sub_reason)."""
    from . import audit_anchor as _audit_anchor

    try:
        _audit_anchor.verify_existing_anchor_for_repo(cwd)
        return True, 0, ""
    except _audit_anchor.AnchorMissingError as exc:
        print(
            f"error: halt-diary clear refused: audit-tip anchor not found ({exc}). "
            "Fix: run 'harness anchor repair' to rebuild the anchor from current state.",
            file=sys.stderr,
        )
        return False, 6, "anchor_missing"
    except _audit_anchor.AnchorMismatchError as exc:
        sub = exc.sub_reason or "anchor_verification_failed"
        print(
            f"error: halt-diary clear refused: audit-tip anchor verification failed "
            f"({sub}: {exc}). "
            "Fix: run 'harness verify --audit' and 'harness anchor repair'.",
            file=sys.stderr,
        )
        return False, 6, sub
    except Exception as exc:
        sub = getattr(exc, "sub_reason", None) or "anchor_error"
        print(
            f"error: halt-diary clear refused: audit-tip anchor unreadable "
            f"({sub}: {exc}). "
            "Fix: run 'harness verify --audit' and 'harness anchor repair'.",
            file=sys.stderr,
        )
        return False, 6, sub


# ---------------------------------------------------------------------------
# cmd_halt_diary_clear
# ---------------------------------------------------------------------------


def cmd_halt_diary_clear(args) -> int:  # type: ignore[no-untyped-def]
    """Handle `harness halt-diary clear` (§5.3 + §12.7).

    TTY-required admin verb: acknowledge + rotate the current last_halt diary
    to last_halt_history (cap=5) and set last_halt=None.
    """
    from . import halt_diary as _halt_diary
    from . import phase_lock as _phase_lock
    from . import phase_preflight as _phase_preflight

    try:
        cwd = _cwd_repo_root()
    except FileNotFoundError as exc:
        print(
            f"error: halt-diary clear refused: {exc}. "
            "Fix: run from inside a harness-managed repository.",
            file=sys.stderr,
        )
        return 6

    scratch = cwd / SCRATCH_ROOT
    audit_path = cwd / AUDIT_PATH

    # Anchor verification (fail-closed per §12.1).
    anchor_verified, anchor_exit, _sub = _verify_anchor(cwd)
    if not anchor_verified:
        return anchor_exit

    # Resolve identity (--by flag or gitconfig fallback).
    by: Optional[str] = getattr(args, "by", None)
    if by is None:
        try:
            by = _phase_preflight.default_gitconfig_email_lookup()
        except Exception:
            by = None

    # Detect TTY.
    stdin_is_tty: bool = sys.stdin.isatty()

    # Acquire lock.
    lock = _phase_lock.acquire_primary(scratch, timeout_s=30.0, audit_path=audit_path)
    try:
        # State-trust preflight (§2.6) before any mutation.
        try:
            _phase_preflight.run_state_trust_preflight(
                scratch=scratch,
                audit_path=audit_path,
                lock=lock,
                anchor_verified=anchor_verified,
            )
        except _phase_preflight.StateTrustPreflightError as exc:
            print(
                f"error: halt-diary clear refused: {exc.message}. {exc.fix_line}",
                file=sys.stderr,
            )
            return exc.exit_code

        result = _halt_diary.run_clear(
            scratch_root=scratch,
            audit_path=audit_path,
            lock_handle=lock,
            anchor_verified=anchor_verified,
            stdin_is_tty=stdin_is_tty,
            by=by,
        )
    finally:
        _phase_lock.release_primary(lock)

    # Print result message (either error or success JSON).
    if result.exit_code != 0:
        print(f"error: {result.message}", file=sys.stderr)
    else:
        print(result.message)

    return result.exit_code


__all__ = [
    "cmd_halt_diary_clear",
]
