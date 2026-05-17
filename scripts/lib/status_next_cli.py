"""CLI handlers for `harness status` and `harness next` (design §3.9).

Wired from ``scripts/harness.py`` argparse dispatch. Both verbs are
read-only (no state mutation, no audit row written). The state-trust
preflight uses option (a) from §3.9 line 554: brief lock acquire + release
so the state-trust module can be invoked without requiring a lock-free code
path in state_trust.preflight (its current signature requires a live lock).

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md
§3.9, §1.1 line 624, §3.4 exit 17/18
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

SCRATCH_ROOT = Path(".scratch")
AUDIT_PATH = Path(".harness") / "audit.log"
STATE_NAME = "phase-state.json"


def _walk_up_for_repo_root(start: Path) -> Path:
    """Walk parent directories looking for ``.git/`` or ``.harness/``.

    Returns the first ancestor directory that contains either marker.
    Raises ``FileNotFoundError`` if neither is found before the filesystem root.
    """
    cur = start.resolve()
    while True:
        if (cur / ".git").exists() or (cur / ".harness").exists():
            return cur
        if cur.parent == cur:
            raise FileNotFoundError(
                f"No .git/ or .harness/ directory found walking up from {start} "
                "to the filesystem root. Ensure you are inside a harness-managed "
                "repository before running status/next commands."
            )
        cur = cur.parent


def _cwd_repo_root() -> Path:
    """Return the repo root by walking up from CWD to the first .git/.harness ancestor."""
    return _walk_up_for_repo_root(Path.cwd())


def _read_state_with_preflight(
    *,
    scratch: Path,
    audit_path: Path,
    cwd: Path,
) -> tuple[Optional[dict], int]:
    """Read phase-state.json after running state-trust preflight.

    Implements option (a) from §3.9 line 554: acquire lock briefly,
    run preflight, release lock, then return state dict.

    Returns (state_dict, exit_code). On preflight failure returns (None, exit_code).
    """
    from . import phase_lock as _phase_lock
    from . import state_trust as _state_trust
    from . import audit_anchor as _audit_anchor

    state_path = scratch / STATE_NAME
    if not state_path.exists():
        # Bootstrap case: no state file yet — anchor irrelevant, return defaults.
        return ({"phase": "discuss", "execution_mode": "manual"}, 0)

    # Anchor verification — fail-closed, same pattern as phase_approve.run_approve
    # (S01-E review-fix reference: scripts/lib/phase_approve.py:411-422).
    # A state file exists: we MUST verify the anchor before trusting the state.
    anchor_verified = False
    try:
        _audit_anchor.verify_existing_anchor_for_repo(cwd)
        anchor_verified = True
    except _audit_anchor.AnchorMissingError:
        # Anchor absent but state exists → fail-closed (attacker path).
        print(
            "error: harness status/next refused: audit-tip anchor not found "
            "but phase-state.json exists. "
            "Fix: run 'harness init' or restore .harness/audit.tip-anchor.json",
            file=sys.stderr,
        )
        return None, 6  # sub_reason: anchor_missing
    except _audit_anchor.AnchorMismatchError as exc:
        sub = getattr(exc, "sub_reason", None) or "anchor_mismatch"
        print(
            f"error: harness status/next refused: audit-tip anchor verification "
            f"failed ({sub}: {exc}). "
            "Fix: run 'harness verify --audit' to diagnose",
            file=sys.stderr,
        )
        return None, 6  # sub_reason: anchor_mismatch
    except _audit_anchor.AnchorError as exc:
        # Schema/unreadable/etc. — surface verbatim; do not swallow.
        sub = getattr(exc, "sub_reason", None) or "anchor_error"
        print(
            f"error: harness status/next refused: audit-tip anchor unreadable "
            f"({sub}: {exc}). "
            "Fix: run 'harness verify --audit' to diagnose",
            file=sys.stderr,
        )
        return None, 6  # sub_reason: anchor_error

    # Brief lock acquire + preflight + release (option a, §3.9 line 554).
    # audit_path=None ensures stale-lock recovery does not write an audit row;
    # §3.9 line 578 mandates auditless status.
    try:
        lock = _phase_lock.acquire_primary(scratch, timeout_s=5.0, audit_path=None)
    except _phase_lock.LockError as exc:
        print(
            f"error: harness status/next: cannot acquire state lock: {exc}\n"
            f"Fix: run 'harness session unlock --force' if the lock is stale.",
            file=sys.stderr,
        )
        return None, 3

    try:
        if anchor_verified:
            try:
                _state_trust.preflight(
                    scratch,
                    audit_path=audit_path,
                    lock=lock,
                    anchor_verified=anchor_verified,
                )
            except _state_trust.StateAuditMismatchError as exc:
                print(
                    f"error: harness status/next: state-trust mismatch: {exc}\n"
                    f"Fix: run 'harness verify --audit'",
                    file=sys.stderr,
                )
                return None, 10
            except _state_trust.StateEmptyError as exc:
                print(
                    f"error: harness status/next: state file empty (crash artefact): {exc}\n"
                    f"Fix: run 'harness recover' before any state-mutating verb.",
                    file=sys.stderr,
                )
                return None, 14
            except _state_trust.StateTrustError as exc:
                exit_code = getattr(exc, "exit_code", 10)
                print(
                    f"error: harness status/next: state-trust preflight failed: {exc}\n"
                    f"Fix: run 'harness verify --audit'",
                    file=sys.stderr,
                )
                return None, exit_code

        # Read state while lock is held
        state_bytes = state_path.read_bytes()
        try:
            state = json.loads(state_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(
                f"error: harness status/next: state file not parseable: {exc}\n"
                f"Fix: run 'harness recover'",
                file=sys.stderr,
            )
            return None, 5

    finally:
        _phase_lock.release_primary(lock)

    return state, 0


def cmd_status(args) -> int:
    """Handle ``harness status [--json]`` (§3.9).

    Walk up to repo root, read state + audit (brief lock for preflight,
    then released — NO lock during format/print), compute_status,
    format per args.json flag, print to stdout, return 0.
    """
    from . import status_next as _sn
    from . import phase_state as _phase_state

    try:
        cwd = _cwd_repo_root()
    except FileNotFoundError as exc:
        print(
            f"error: harness status refused: {exc}\n"
            "Fix: run from inside a harness-managed repository.",
            file=sys.stderr,
        )
        return 6

    scratch = cwd / SCRATCH_ROOT
    audit_path = cwd / AUDIT_PATH

    state, preflight_exit = _read_state_with_preflight(
        scratch=scratch,
        audit_path=audit_path,
        cwd=cwd,
    )
    if state is None:
        return preflight_exit

    # Apply v2 defaults so all fields are present
    try:
        state = _phase_state.coerce_legacy_execution_mode(state)
    except ValueError:
        pass  # best-effort for status
    state = _phase_state.apply_v2_defaults(state)

    result = _sn.compute_status(state=state, audit_path=audit_path)

    use_json = getattr(args, "json", False)
    if use_json:
        sys.stdout.write(_sn.format_status_json(result))
    else:
        sys.stdout.write(_sn.format_status_human(result))

    return 0


def cmd_next(args) -> int:
    """Handle ``harness next [--shell | --json]`` (§3.9).

    Walk up + read state (brief lock for preflight, then released),
    compute_next, format per args.shell/args.json, return exit_code.
    """
    from . import status_next as _sn
    from . import phase_state as _phase_state

    try:
        cwd = _cwd_repo_root()
    except FileNotFoundError as exc:
        print(
            f"error: harness next refused: {exc}\n"
            "Fix: run from inside a harness-managed repository.",
            file=sys.stderr,
        )
        return 6

    scratch = cwd / SCRATCH_ROOT
    audit_path = cwd / AUDIT_PATH

    state, preflight_exit = _read_state_with_preflight(
        scratch=scratch,
        audit_path=audit_path,
        cwd=cwd,
    )
    if state is None:
        return preflight_exit

    # Apply v2 defaults so all fields are present
    try:
        state = _phase_state.coerce_legacy_execution_mode(state)
    except ValueError:
        pass  # best-effort for next
    state = _phase_state.apply_v2_defaults(state)

    result = _sn.compute_next(state=state, audit_path=audit_path)

    use_shell = getattr(args, "shell", False)
    use_json = getattr(args, "json", False)

    if use_json:
        sys.stdout.write(_sn.format_next_json(result))
        return result.exit_code
    elif use_shell:
        text, exit_code = _sn.format_next_shell(result)
        if text:
            sys.stdout.write(text)
        return exit_code
    else:
        sys.stdout.write(_sn.format_next_human(result))
        return result.exit_code


__all__ = [
    "cmd_status",
    "cmd_next",
]
