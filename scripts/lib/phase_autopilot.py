"""`phase autopilot start | stop | next-pending` verb logic (design §3.5).

Order of operations for `run_start` (any failure → `AutopilotResult` with
non-zero `exit_code`; the CLI dispatcher maps to `sys.exit`):

  1. Lock contract check (TxnLockMissingError raised if lock missing/released).
  2. Anchor preflight (§12.1). Default `repo_root=None` + `skip_anchor_preflight=False`
     → exit 6 `anchor_preflight_unwired` (fail-closed).
  3. State-trust preflight (§2.6). Refuses forged state with exit 10.
  4. Windows containment check (§3.5 Round-3 BLOCK): Windows + chain mode
     + NOT (accept_degraded_windows_containment OR allow_network) → exit 11.
  5. Phase slug validation: None → exit 2 `invalid_phase_slug`;
     not in roadmap → exit 2 `phase_slug_not_in_roadmap`.
  6. Git repo check (chain mode only): if repo_root provided and has no .git
     → exit 12 `git_repo_required`.
  7. Active-autopilot re-entry (§3.5.2): execution_mode != "manual"
     → exit 15 `autopilot_already_active`.
  8. State + audit mutation via `phase_txn.commit_transaction`. Populates all
     §1.1 autopilot identity fields.

`run_stop` (§3.5):
  - Idempotent: if already manual, exit 0 silently.
  - Clears all autopilot identity fields, sets execution_mode=manual.
  - Emits verb=phase.autopilot.stop audit row with reason.

`run_next_pending` (§3.5):
  - Pure read: acquires lock briefly (crash-recovery consistent snapshot),
    returns next non-done phase slug or sentinel.
  - No audit row. No state mutation.

Note on `authorization_source`: this parameter is an opaque string passed by
the caller (CLI dispatcher). §3.5.1 CI provenance predicate validation is
DEFERRED to a later step. This module ACCEPTS whatever the caller provides and
records it verbatim in the audit row.

Spec: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`
Sections: §3.5, §3.5.2, §1.1, §3.4
"""

from __future__ import annotations

import dataclasses
import json
import secrets
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

from . import phase_lock as _phase_lock
from . import phase_preflight as _phase_preflight
from . import phase_txn as _phase_txn


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class AutopilotResult:
    """One invocation outcome for start/stop. `exit_code` MUST be one of the
    design §3.4 codes; `sub_reason` is the machine-readable taxonomy bucket."""

    exit_code: int
    sub_reason: str
    message: str = ""
    autopilot_run_id: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class NextPendingResult:
    """Result of `run_next_pending`. `next_slug` is the first non-done phase
    slug, or "" when all phases are done. `all_done` is True in the latter
    case. `exit_code` is always 0 per spec (pure read)."""

    exit_code: int
    next_slug: str
    all_done: bool = False


# ---------------------------------------------------------------------------
# Fix-line messages (§3.9 — every error MUST carry a remediation)
# ---------------------------------------------------------------------------


_FIX_ANCHOR_UNWIRED = (
    "Fix: caller must pass `repo_root=` so the §12.1 trust chain can "
    "verify the out-of-repo audit-tip anchor before reading state; "
    "or pass `skip_anchor_preflight=True` ONLY from controlled test paths"
)
_FIX_WINDOWS_CHAIN = (
    "Fix: pass `--accept-degraded-windows-containment` to allow chain mode "
    "on Windows without network isolation, or pass `--allow-network` to "
    "enable network access (disabling containment check), or use mode=phase "
    "instead (design §3.5 Round-3)"
)
_FIX_SLUG_MISSING = (
    "Fix: provide a non-None phase_slug; for chain mode without a target "
    "phase, the WRAPPER should call next-pending first (design §3.5)"
)
_FIX_SLUG_NOT_IN_ROADMAP = (
    "Fix: verify the phase slug matches a directory under `.planning/phases/`; "
    "run `harness phase next-pending` to list pending phases (design §3.5)"
)
_FIX_GIT_REQUIRED = (
    "Fix: chain mode requires a git repository (design §7.5); "
    "run `git init` or switch to mode=phase for no-git environments"
)
_FIX_ALREADY_ACTIVE = (
    "Fix: run `harness status` to inspect. "
    "Then choose exactly one path: let the current autopilot continue, "
    "or run `harness phase autopilot stop --reason \"<text>\"` to return "
    "to manual mode. Only after stop may you use manual `harness phase set <next>` "
    "or start a new autopilot run. (design §3.5.2)"
)
_FIX_STATE_TRUST = (
    "Fix: run `harness verify --audit`; "
    "if intentional, restore via `git checkout -- .scratch/phase-state.json` "
    "or re-run `harness install`"
)


# ---------------------------------------------------------------------------
# Default budget values (§3.5 / §4.3)
# ---------------------------------------------------------------------------


_DEFAULT_BUDGETS = {
    "shell_invocations": 50,
    "file_mutation_ops": 100,
    "wall_seconds": 300,
}


# ---------------------------------------------------------------------------
# Roadmap helpers
# ---------------------------------------------------------------------------


def _list_roadmap_slugs(roadmap_root: Optional[Path]) -> list[str]:
    """Return sorted phase slugs from `.planning/phases/` directories.

    Roadmap order = alphabetical sort of directory names (consistent with
    §12.3 design note: 'roadmap-order; roadmap source is `.planning/phases/*/`
    glob in roadmap-order').
    """
    if roadmap_root is None:
        return []
    root = Path(roadmap_root)
    if not root.is_dir():
        return []
    dirs = sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )
    return dirs


def _is_phase_done(roadmap_root: Optional[Path], slug: str) -> bool:
    """Return True if the phase directory has a phase-state.json that records done."""
    if roadmap_root is None:
        return False
    phase_dir = Path(roadmap_root) / slug
    state_file = phase_dir / "phase-state.json"
    if not state_file.exists():
        return False
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return str(data.get("phase", "")).lower() == "done"
    except (json.JSONDecodeError, OSError):
        return False


# ---------------------------------------------------------------------------
# Internal preflight helpers (mirror phase_approve.py pattern)
# ---------------------------------------------------------------------------


def _run_anchor_preflight_for_autopilot(
    *,
    skip_anchor_preflight: bool,
    repo_root: Optional[Path],
) -> Optional[AutopilotResult]:
    """Run anchor preflight. Returns an AutopilotResult on failure, None on success."""
    try:
        _phase_preflight.run_anchor_preflight(
            skip_anchor_preflight=skip_anchor_preflight,
            repo_root=repo_root,
        )
        return None
    except _phase_preflight.AnchorPreflightError as exc:
        print(
            f"error: phase autopilot start refused: {exc.message}. "
            f"{exc.fix_line}",
            file=sys.stderr,
        )
        return AutopilotResult(
            exit_code=6,
            sub_reason=exc.sub_reason,
            message=exc.message,
        )


def _run_state_trust_preflight_for_autopilot(
    *,
    scratch: Path,
    audit_path: Path,
    lock: Any,
    anchor_verified: bool,
) -> Optional[AutopilotResult]:
    """Run state-trust preflight. Returns AutopilotResult on failure, None on success."""
    try:
        _phase_preflight.run_state_trust_preflight(
            scratch=scratch,
            audit_path=audit_path,
            lock=lock,
            anchor_verified=anchor_verified,
        )
        return None
    except _phase_preflight.StateTrustPreflightError as exc:
        print(
            f"error: phase autopilot refused: {exc.message}. {exc.fix_line}",
            file=sys.stderr,
        )
        return AutopilotResult(
            exit_code=exc.exit_code,
            sub_reason=exc.sub_reason,
            message=exc.message,
        )


# ---------------------------------------------------------------------------
# run_start
# ---------------------------------------------------------------------------


def run_start(
    *,
    scratch_root: Path,
    audit_path: Path,
    lock_handle: Any,
    phase_slug: Optional[str],
    mode: str,
    budgets: Optional[Mapping[str, int]],
    allow_network: bool,
    authorization_source: str,
    anchor_verified: bool,
    skip_anchor_preflight: bool = False,
    accept_degraded_windows_containment: bool = False,
    repo_root: Optional[Path] = None,
    roadmap_root: Optional[Path] = None,
) -> AutopilotResult:
    """Execute the §3.5 `phase autopilot start` sequence.

    Parameters
    ----------
    scratch_root : Path
        `.scratch/` directory (contains phase-state.json).
    audit_path : Path
        Audit log path (e.g. `.harness/audit.log`).
    lock_handle : LockHandle | None
        Must be an acquired, un-released LockHandle. None → TxnLockMissingError.
    phase_slug : str | None
        Phase slug from roadmap. None → exit 2 `invalid_phase_slug`.
    mode : str
        "phase" or "chain".
    budgets : dict | None
        Budget overrides. None → defaults.
    allow_network : bool
        Whether to allow network (echoed to state + audit).
    authorization_source : str
        Opaque string from caller (§3.5.1 predicate deferred).
    anchor_verified : bool
        True when §12.1 anchor already verified externally.
    skip_anchor_preflight : bool
        True ONLY in controlled test paths (skips §12.1 chain).
    accept_degraded_windows_containment : bool
        Bypasses Windows exit 11 (§3.5 Round-3 escape hatch).
    repo_root : Path | None
        Repo root for git check (chain mode) and anchor preflight.
    roadmap_root : Path | None
        `.planning/phases/` root for slug validation. None → no check.
    """
    scratch = Path(scratch_root)
    audit_path = Path(audit_path)

    # Step 1: lock contract check (raises TxnLockMissingError if not held).
    _phase_txn._check_lock(lock_handle, scratch)

    # Step 2: anchor preflight.
    fail = _run_anchor_preflight_for_autopilot(
        skip_anchor_preflight=skip_anchor_preflight,
        repo_root=repo_root,
    )
    if fail is not None:
        return fail

    # Determine anchor_verified flag for state-trust preflight.
    av = anchor_verified if not skip_anchor_preflight else True

    # Step 3: state-trust preflight.
    fail = _run_state_trust_preflight_for_autopilot(
        scratch=scratch,
        audit_path=audit_path,
        lock=lock_handle,
        anchor_verified=av,
    )
    if fail is not None:
        return fail

    # Step 4: Windows containment check (§3.5 Round-3 BLOCK).
    if (
        sys.platform.startswith("win")
        and mode == "chain"
        and not accept_degraded_windows_containment
        and not allow_network
    ):
        msg = (
            "phase autopilot start refused: Windows + chain mode without "
            "network isolation (containment degraded). "
            f"{_FIX_WINDOWS_CHAIN}"
        )
        print(f"error: {msg}", file=sys.stderr)
        return AutopilotResult(
            exit_code=11,
            sub_reason="windows_containment_degraded",
            message=msg,
        )

    # Step 5: Phase slug validation.
    if phase_slug is None:
        msg = (
            "phase autopilot start refused: phase_slug is None. "
            f"{_FIX_SLUG_MISSING}"
        )
        print(f"error: {msg}", file=sys.stderr)
        return AutopilotResult(
            exit_code=2,
            sub_reason="invalid_phase_slug",
            message=msg,
        )

    known_slugs = _list_roadmap_slugs(roadmap_root)
    if known_slugs and phase_slug not in known_slugs:
        msg = (
            f"phase autopilot start refused: phase_slug {phase_slug!r} "
            f"not found in roadmap. {_FIX_SLUG_NOT_IN_ROADMAP}"
        )
        print(f"error: {msg}", file=sys.stderr)
        return AutopilotResult(
            exit_code=2,
            sub_reason="phase_slug_not_in_roadmap",
            message=msg,
        )
    # If roadmap_root is None or no phase dirs exist, we cannot validate —
    # accept the slug to avoid blocking on empty-roadmap installs.

    # Step 6: Git repo check (chain mode only, when repo_root is explicit).
    if mode == "chain" and repo_root is not None:
        repo_path = Path(repo_root)
        if not (repo_path / ".git").exists():
            msg = (
                f"phase autopilot start refused: chain mode requires a git "
                f"repository at {repo_path}. {_FIX_GIT_REQUIRED}"
            )
            print(f"error: {msg}", file=sys.stderr)
            return AutopilotResult(
                exit_code=12,
                sub_reason="git_repo_required",
                message=msg,
            )

    # Step 7: Load state and check for active autopilot (§3.5.2).
    state_path = scratch / _phase_txn.STATE_NAME
    if not state_path.exists():
        # Bootstrap case: state missing; cannot start autopilot without state.
        msg = (
            "phase autopilot start refused: no state file present. "
            "Fix: run `harness phase set discuss` to bootstrap state."
        )
        print(f"error: {msg}", file=sys.stderr)
        return AutopilotResult(exit_code=6, sub_reason="state_missing", message=msg)

    before_state = json.loads(state_path.read_text(encoding="utf-8"))
    execution_mode = before_state.get("execution_mode", "manual")

    if execution_mode != "manual":
        existing_run_id = before_state.get("autopilot_run_id", "<unknown>")
        existing_mode = before_state.get("autopilot_mode", "<unknown>")
        existing_slug = before_state.get("autopilot_phase_slug", "<unknown>")
        msg = (
            f"phase autopilot start refused: autopilot already active "
            f"(run_id={existing_run_id!r}, mode={existing_mode!r}, "
            f"phase_slug={existing_slug!r}). {_FIX_ALREADY_ACTIVE}"
        )
        print(f"error: {msg}", file=sys.stderr)
        return AutopilotResult(
            exit_code=15,
            sub_reason="autopilot_already_active",
            message=msg,
        )

    # Step 8: State + audit mutation.
    new_run_id = secrets.token_hex(16)
    resolved_budgets = dict(_DEFAULT_BUDGETS)
    if budgets:
        resolved_budgets.update(budgets)

    execution_mode_value = (
        "chain_autopilot" if mode == "chain" else "phase_autopilot"
    )

    after_state = dict(before_state)
    after_state["execution_mode"] = execution_mode_value
    after_state["autopilot_run_id"] = new_run_id
    after_state["autopilot_mode"] = mode
    after_state["autopilot_phase_slug"] = phase_slug
    after_state["autopilot_allow_network"] = allow_network
    after_state["cli_budgets_remaining"] = resolved_budgets
    # autopilot_start_entry_hash is set below before commit_transaction using
    # a pre-generated txn_id (see design decision comment below).

    # Audit entry (§3.5 fields).
    now_iso = _phase_preflight.now_iso_z()
    audit_draft: dict = {
        "verb": "phase.autopilot.start",
        "authorization_source": authorization_source,
        "args": {
            "mode": mode,
            "phase_slug": phase_slug,
            "budgets": resolved_budgets,
            "allow_network": allow_network,
            "started_at": now_iso,
        },
    }

    # We need the txn_id to store in autopilot_start_entry_hash, but txn_id
    # is returned AFTER commit_transaction. Solution: generate it here and
    # pass it. (phase_txn generates one internally; we override by pre-
    # generating and injecting it via the audit draft so both state and audit
    # carry the same identifier.)
    #
    # Design decision: §1.1 says autopilot_start_entry_hash = "entry_hash of
    # the phase.autopilot.start audit entry". Since S06 (hash-chain) is not
    # yet complete, we use `txn_id` as a stable cross-reference. When S06
    # lands, the CLI dispatcher can read the audit tail and replace this
    # field with the actual entry_hash. For now we populate it from the
    # returned txn_id.

    # Design decision: §1.1 says autopilot_start_entry_hash = "the entry_hash
    # of the verb=phase.autopilot.start audit entry". S06 (hash-chain) will
    # supply the actual entry_hash. For this slice we use the pre-generated
    # txn_id as the cross-reference anchor — forward-compatible because S06
    # will replace this field's source of truth.
    #
    # We pre-generate txn_id here and embed it in BOTH after_state and the
    # audit draft so a single commit_transaction sets the field atomically.
    # phase_txn generates its own internal txn_id; we pass our pre-generated
    # value via the audit draft's `txn_id` field and accept the one returned
    # (they will differ, but the state field correctly references the
    # pre-generated one which is also in the audit draft args for forensics).
    pre_txn_id = _phase_txn._new_txn_id()
    after_state["autopilot_start_entry_hash"] = pre_txn_id
    audit_draft["args"]["autopilot_start_entry_hash_ref"] = pre_txn_id

    txn_id = _phase_txn.commit_transaction(
        scratch,
        lock=lock_handle,
        request=_phase_txn.TxnRequest(
            action="phase.autopilot.start",
            before_state=before_state,
            after_state=after_state,
            audit_entry_draft=audit_draft,
        ),
        audit_path=audit_path,
    )

    print(
        json.dumps(
            {
                "ok": True,
                "verb": "phase.autopilot.start",
                "autopilot_run_id": new_run_id,
                "mode": mode,
                "phase_slug": phase_slug,
                "execution_mode": execution_mode_value,
                "authorization_source": authorization_source,
                "txn_id": txn_id,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return AutopilotResult(
        exit_code=0,
        sub_reason="started",
        message="autopilot started",
        autopilot_run_id=new_run_id,
    )


# ---------------------------------------------------------------------------
# run_stop
# ---------------------------------------------------------------------------


def run_stop(
    *,
    scratch_root: Path,
    audit_path: Path,
    lock_handle: Any,
    reason: str,
    anchor_verified: bool,
    skip_anchor_preflight: bool = False,
    repo_root: Optional[Path] = None,
) -> AutopilotResult:
    """Execute the §3.5 `phase autopilot stop` sequence.

    Idempotent: if execution_mode is already "manual", exit 0 silently
    (no state mutation, no audit row). This prevents audit clutter from
    double-stop calls in wrapper scripts.

    Parameters mirror `run_start` minus autopilot-specific fields.
    """
    scratch = Path(scratch_root)
    audit_path = Path(audit_path)

    # Lock contract check.
    _phase_txn._check_lock(lock_handle, scratch)

    # Anchor preflight.
    fail = _run_anchor_preflight_for_autopilot(
        skip_anchor_preflight=skip_anchor_preflight,
        repo_root=repo_root,
    )
    if fail is not None:
        return fail

    av = anchor_verified if not skip_anchor_preflight else True

    # State-trust preflight.
    fail = _run_state_trust_preflight_for_autopilot(
        scratch=scratch,
        audit_path=audit_path,
        lock=lock_handle,
        anchor_verified=av,
    )
    if fail is not None:
        return fail

    state_path = scratch / _phase_txn.STATE_NAME
    if not state_path.exists():
        # No state: nothing to stop.
        return AutopilotResult(
            exit_code=0,
            sub_reason="stopped",
            message="no state file; nothing to stop",
        )

    before_state = json.loads(state_path.read_text(encoding="utf-8"))
    execution_mode = before_state.get("execution_mode", "manual")

    # Idempotency: already manual → exit 0 silently.
    if execution_mode == "manual":
        return AutopilotResult(
            exit_code=0,
            sub_reason="stopped",
            message="already manual; no-op",
        )

    # Clear all autopilot identity fields.
    now_iso = _phase_preflight.now_iso_z()
    after_state = dict(before_state)
    after_state["execution_mode"] = "manual"
    after_state["autopilot_run_id"] = None
    after_state["autopilot_mode"] = None
    after_state["autopilot_phase_slug"] = None
    after_state["autopilot_start_entry_hash"] = None
    after_state["cli_budgets_remaining"] = None

    audit_draft = {
        "verb": "phase.autopilot.stop",
        "args": {
            "reason": reason,
            "stopped_at": now_iso,
            "prior_execution_mode": execution_mode,
            "prior_autopilot_run_id": before_state.get("autopilot_run_id"),
        },
    }

    _phase_txn.commit_transaction(
        scratch,
        lock=lock_handle,
        request=_phase_txn.TxnRequest(
            action="phase.autopilot.stop",
            before_state=before_state,
            after_state=after_state,
            audit_entry_draft=audit_draft,
        ),
        audit_path=audit_path,
    )

    print(
        json.dumps(
            {
                "ok": True,
                "verb": "phase.autopilot.stop",
                "reason": reason,
                "stopped_at": now_iso,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return AutopilotResult(
        exit_code=0,
        sub_reason="stopped",
        message="autopilot stopped",
    )


# ---------------------------------------------------------------------------
# run_next_pending
# ---------------------------------------------------------------------------


def run_next_pending(
    *,
    scratch_root: Path,
    audit_path: Path,
    lock_handle: Any,
    anchor_verified: bool,
    skip_anchor_preflight: bool = False,
    repo_root: Optional[Path] = None,
    roadmap_root: Optional[Path] = None,
) -> NextPendingResult:
    """Pure read: return the next non-done phase slug from `.planning/phases/`.

    Acquires state lock briefly for a consistent-snapshot read + crash
    recovery guard. No audit row. No state mutation.

    Returns `NextPendingResult(exit_code=0, next_slug="", all_done=True)`
    when all phases are done or roadmap is empty (design §3.5.2).
    """
    scratch = Path(scratch_root)
    audit_path_p = Path(audit_path)

    # Lock contract check.
    _phase_txn._check_lock(lock_handle, scratch)

    # Anchor preflight.
    fail = _run_anchor_preflight_for_autopilot(
        skip_anchor_preflight=skip_anchor_preflight,
        repo_root=repo_root,
    )
    if fail is not None:
        # Translate anchor failure to a NextPendingResult.
        return NextPendingResult(exit_code=fail.exit_code, next_slug="", all_done=False)

    av = anchor_verified if not skip_anchor_preflight else True

    # State-trust preflight (crash recovery runs inside here).
    fail = _run_state_trust_preflight_for_autopilot(
        scratch=scratch,
        audit_path=audit_path_p,
        lock=lock_handle,
        anchor_verified=av,
    )
    if fail is not None:
        return NextPendingResult(exit_code=fail.exit_code, next_slug="", all_done=False)

    # Pure read of roadmap.
    slugs = _list_roadmap_slugs(roadmap_root)
    for slug in slugs:
        if not _is_phase_done(roadmap_root, slug):
            return NextPendingResult(exit_code=0, next_slug=slug, all_done=False)

    # All done (or empty roadmap).
    return NextPendingResult(exit_code=0, next_slug="", all_done=True)


__all__ = [
    "AutopilotResult",
    "NextPendingResult",
    "run_start",
    "run_stop",
    "run_next_pending",
]
