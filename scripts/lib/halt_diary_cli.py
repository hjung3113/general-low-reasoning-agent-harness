"""CLI handler for `harness halt-diary clear` (design §5.3 + §12.7).

Wired from ``scripts/harness.py`` argparse dispatch. Follows the standard
pattern from ``scripts/lib/phase_autopilot_cli.py``:

  1. Walk-up for repo root.
  2. State-trust preflight.
  3. Acquire primary lock.
  4. Call `halt_diary.run_clear`.
  5. Release lock.
  6. Print result + sys.exit.

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
# Re-use walk-up helper from phase_autopilot_cli
# ---------------------------------------------------------------------------


def _cwd_repo_root() -> Path:
    """Walk up from CWD to the first .git/.harness ancestor."""
    cwd = Path.cwd().resolve()
    for ancestor in (cwd, *cwd.parents):
        if (ancestor / ".harness").is_dir() or (ancestor / ".git").exists():
            return ancestor
    raise FileNotFoundError(
        "no .harness/.git ancestor found from " + str(cwd)
    )


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
