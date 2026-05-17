"""`phase autopilot start | stop | next-pending` verb logic (design §3.5).

Order of operations for `run_start` (any failure → `AutopilotResult` with
non-zero `exit_code`; the CLI dispatcher maps to `sys.exit`):

  1. Lock contract check (TxnLockMissingError raised if lock missing/released).
  2. Anchor preflight (§12.1). Default `repo_root=None` + `skip_anchor_preflight=False`
     → exit 6 `anchor_preflight_unwired` (fail-closed).
  3. State-trust preflight (§2.6). Refuses forged state with exit 10.
  3b. Authorization algorithm (§3.5 + §3.5.1):
     TTY path: validate by_email ∈ approvers, consume nonce → authorization_source="cli_tty_human".
     CI path: run ci_predicate_satisfied → authorization_source from result.
  4. Windows containment check (§3.5 Round-3 BLOCK): Windows + chain mode
     + NOT (accept_degraded_windows_containment OR allow_network) → exit 11.
  5. Phase slug validation: None → exit 2 `invalid_phase_slug`;
     not in roadmap → exit 2 `phase_slug_not_in_roadmap`.
  6. Git repo check (chain mode only): if repo_root provided and has no .git
     → exit 12 `git_repo_required`.
  7. Active-autopilot re-entry (§3.5.2): execution_mode != "manual"
     → exit 15 `autopilot_already_active`.
  8. State + audit mutation via `phase_txn.commit_transaction`. Populates all
     §1.1 autopilot identity fields + §3.5.1 CI provenance fields.

`run_stop` (§3.5):
  - Idempotent: if already manual, exit 0 silently.
  - Clears all autopilot identity fields, sets execution_mode=manual.
  - Emits verb=phase.autopilot.stop audit row with reason.

`run_next_pending` (§3.5):
  - Pure read: acquires lock briefly (crash-recovery consistent snapshot),
    returns next non-done phase slug or sentinel.
  - No audit row. No state mutation.

Note on authorization: `run_start` derives `authorization_source` from TTY-or-CI
check (§3.5.1). The caller supplies TTY/CI inputs; `run_start` runs the algorithm.
The former opaque `authorization_source: str` kwarg is replaced by `stdin_is_tty`,
`by_email`, `nonce_*`, and `env`/OIDC injectors.

Spec: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`
Sections: §3.5, §3.5.1, §3.5.2, §1.1, §3.4
"""

from __future__ import annotations

import dataclasses
import json
import os
import secrets
import sys
import warnings
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from . import approval_nonce as _approval_nonce
from . import ci_provenance as _ci_provenance
from . import cli_budgets as _cli_budgets
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
_FIX_APPROVER_NOT_IN_INSTALL_RECORD = (
    "Fix: only emails listed in `.harness/install-record.json approvers[]` "
    "may authorize autopilot; re-run `harness install` to update approvers"
)
_FIX_HUMAN_PROOF = (
    "Fix: run `harness approve-nonce mint` in your TTY before calling "
    "`phase autopilot start`; the nonce must be minted from a DIFFERENT "
    "TTY than the one running the command (design §3.1.1)"
)
_FIX_ALLOW_NETWORK_SOURCE = (
    "Fix: `--allow-network` is only permitted when the same CI predicate "
    "or TTY-human authorization path that authorized this run is satisfied; "
    "HARNESS_ALLOW_NETWORK=1 alone is insufficient (design §3.5)"
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


def _run_crash_recovery(
    *,
    scratch: Path,
    audit_path: Path,
    lock: Any,
) -> Optional["AutopilotResult"]:
    """Run crash recovery (§3.5.2 / §3.8). Returns AutopilotResult on undecidable failure, None on success.

    This MUST be called before reading state in run_start, run_stop, and
    run_next_pending (§3.5.2 line 319 / line 312). The lock MUST already be held.
    """
    try:
        recovery = _phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
        if recovery.exit_code != 0:
            msg = (
                f"crash recovery undecidable (row={recovery.row}, "
                f"decision={recovery.decision!r}); "
                "Fix: run `harness verify --audit` to inspect audit chain, "
                "then `harness anchor repair` if the anchor is stale."
            )
            print(f"error: {msg}", file=sys.stderr)
            return AutopilotResult(
                exit_code=recovery.exit_code,
                sub_reason=f"crash_recovery_undecidable:{recovery.decision}",
                message=msg,
            )
    except _phase_txn.TxnLockMissingError:
        raise  # propagate — callers handle this at the lock-contract-check step
    except Exception as exc:
        msg = (
            f"crash recovery raised unexpected error ({exc}); "
            "Fix: run `harness verify --audit` to inspect state."
        )
        print(f"error: {msg}", file=sys.stderr)
        return AutopilotResult(
            exit_code=14,
            sub_reason="crash_recovery_error",
            message=msg,
        )
    return None


def run_start(
    *,
    scratch_root: Path,
    audit_path: Path,
    lock_handle: Any,
    phase_slug: Optional[str],
    mode: str,
    budgets: Optional[Mapping[str, int]],
    allow_network: bool,
    anchor_verified: bool = False,
    skip_anchor_preflight: bool = False,
    accept_degraded_windows_containment: bool = False,
    repo_root: Optional[Path] = None,
    roadmap_root: Optional[Path] = None,
    # Authorization inputs (§3.5 + §3.5.1) — caller supplies raw inputs;
    # run_start runs the algorithm and derives authorization_source.
    env: Optional[Mapping[str, str]] = None,
    stdin_is_tty: Optional[bool] = None,
    consumer_tty: Optional[str] = None,
    nonce_audience: Optional[str] = None,
    nonce_dir: Optional[Path] = None,
    by_email: Optional[str] = None,
    install_record_root: Optional[Path] = None,
    oidc_fetcher: Optional[Callable] = None,
    oidc_verifier: Optional[Callable] = None,
    # Deprecated alias (one release cycle): use consumer_tty instead.
    nonce_id: Optional[str] = None,
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
    env : Mapping | None
        Environment mapping. Defaults to os.environ (used for CI path).
    stdin_is_tty : bool | None
        Whether stdin is a TTY. Defaults to sys.stdin.isatty().
    consumer_tty : str | None
        TTY path of the consuming process (must differ from the minter TTY
        per §3.1.1 cross-TTY human proof semantics). Required if stdin_is_tty=True.
        Passed verbatim as `consumer_tty` to `approval_nonce.consume_newest_valid`.
    nonce_audience : str | None
        Nonce audience for TTY human proof (required if stdin_is_tty=True).
    nonce_dir : Path | None
        Directory for nonce files (for consume_newest_valid).
    by_email : str | None
        Human approver's email; required if stdin_is_tty=True.
    install_record_root : Path | None
        Directory containing install-record.json for approvers lookup.
        Falls back to repo_root if None.
    oidc_fetcher : Callable | None
        Injected OIDC fetcher for ci_provenance (TEST-ONLY stubs if None and
        HARNESS_OIDC_TEST_MODE=1; otherwise raises CiOidcUnreachable).
    oidc_verifier : Callable | None
        Injected OIDC verifier for ci_provenance (TEST-ONLY stubs if None and
        HARNESS_OIDC_TEST_MODE=1; otherwise raises CiOidcUnreachable).
    nonce_id : str | None
        DEPRECATED — use ``consumer_tty`` instead. Accepted for one release
        cycle; emits DeprecationWarning.
    """
    # Handle deprecated nonce_id alias.
    if nonce_id is not None:
        warnings.warn(
            "run_start() kwarg 'nonce_id' is deprecated; use 'consumer_tty' instead. "
            "'nonce_id' will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        if consumer_tty is None:
            consumer_tty = nonce_id
    scratch = Path(scratch_root)
    audit_path = Path(audit_path)

    # Step 1: lock contract check (raises TxnLockMissingError if not held).
    _phase_txn._check_lock(lock_handle, scratch)

    # Step 1b: crash recovery (§3.5.2 line 312 — run BEFORE reading state).
    fail = _run_crash_recovery(scratch=scratch, audit_path=audit_path, lock=lock_handle)
    if fail is not None:
        return fail

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

    # Step 3b: Authorization algorithm (§3.5 + §3.5.1).
    resolved_env: Mapping[str, str] = env if env is not None else os.environ
    resolved_stdin_is_tty: bool = (
        stdin_is_tty if stdin_is_tty is not None else sys.stdin.isatty()
    )

    # Resolve install-record approvers (used by both TTY and CI paths).
    _ir_root = install_record_root or repo_root
    _install_record_path: Optional[Path] = None
    if _ir_root is not None:
        _ir_root_p = Path(_ir_root)
        # Support both "root containing .harness/" and ".harness/" directly.
        candidate_a = _ir_root_p / ".harness" / "install-record.json"
        candidate_b = _ir_root_p / "install-record.json"
        if candidate_a.exists():
            _install_record_path = candidate_a
        elif candidate_b.exists():
            _install_record_path = candidate_b

    approvers_set: set[str] = set()
    if _install_record_path is not None:
        try:
            rec = _phase_preflight.load_install_record(_install_record_path)
            approvers_set = set(_phase_preflight.approvers_emails(rec))
        except (FileNotFoundError, Exception):
            approvers_set = set()

    # Fields populated by the authorization path.
    authorization_source: str
    by: Optional[str] = None
    by_source: Optional[str] = None
    ci_signature: Optional[dict] = None
    ci_oidc_verified: Optional[bool] = None
    ci_oidc_claims: Optional[dict] = None
    bot_identity: Optional[str] = None
    bot_identity_distinct_from_approvers: Optional[bool] = None

    if resolved_stdin_is_tty:
        # TTY human proof path (§3.1.1).

        # 1. by_email must be in approvers.
        #    Empty approvers_set (install-record missing) + by_email supplied
        #    → reject with install_record_missing (do NOT silently accept).
        if not by_email:
            msg = (
                "phase autopilot start refused: by_email is required for TTY path. "
                f"{_FIX_APPROVER_NOT_IN_INSTALL_RECORD}"
            )
            print(f"error: {msg}", file=sys.stderr)
            return AutopilotResult(
                exit_code=6,
                sub_reason="approver_not_in_install_record",
                message=msg,
            )
        if not approvers_set:
            msg = (
                "phase autopilot start refused: install-record approvers list is "
                "empty or install-record.json is missing; cannot verify "
                f"{by_email!r}. {_FIX_APPROVER_NOT_IN_INSTALL_RECORD}"
            )
            print(f"error: {msg}", file=sys.stderr)
            return AutopilotResult(
                exit_code=6,
                sub_reason="install_record_missing",
                message=msg,
            )
        if by_email.strip().lower() not in approvers_set:
            msg = (
                f"phase autopilot start refused: {by_email!r} is not in "
                f"install-record approvers. {_FIX_APPROVER_NOT_IN_INSTALL_RECORD}"
            )
            print(f"error: {msg}", file=sys.stderr)
            return AutopilotResult(
                exit_code=6,
                sub_reason="approver_not_in_install_record",
                message=msg,
            )

        # 2. Require consumer_tty + nonce_audience + nonce_dir; consume nonce.
        if not consumer_tty or not nonce_audience or nonce_dir is None:
            msg = (
                "phase autopilot start refused: consumer_tty, nonce_audience, "
                f"and nonce_dir are required for TTY human proof. {_FIX_HUMAN_PROOF}"
            )
            print(f"error: {msg}", file=sys.stderr)
            return AutopilotResult(
                exit_code=6,
                sub_reason="human_proof_missing",
                message=msg,
            )

        consume_result = _approval_nonce.consume_newest_valid(
            Path(nonce_dir),
            audience=nonce_audience,
            consumer_tty=consumer_tty,
        )

        _OUTCOME_TO_SUB = {
            "missing": "human_proof_missing",
            "expired": "human_proof_expired",
            "same_tty": "human_proof_same_tty",
            "audience_mismatch": "human_proof_audience_mismatch",
        }
        if consume_result.outcome != "consumed":
            sub = _OUTCOME_TO_SUB.get(consume_result.outcome, "human_proof_missing")
            msg = (
                f"phase autopilot start refused: nonce consume failed "
                f"({consume_result.outcome}). {_FIX_HUMAN_PROOF}"
            )
            print(f"error: {msg}", file=sys.stderr)
            return AutopilotResult(
                exit_code=6,
                sub_reason=sub,
                message=msg,
            )

        # 3. Set authorization fields.
        authorization_source = "cli_tty_human"
        by = by_email
        by_source = "gitconfig"
        # CI fields are None for TTY path.
        ci_signature = None
        ci_oidc_verified = None
        ci_oidc_claims = None
        bot_identity = None
        bot_identity_distinct_from_approvers = None

    else:
        # CI predicate path (§3.5.1).
        try:
            ci_result = _ci_provenance.ci_predicate_satisfied(
                env=resolved_env,
                install_record_approvers=approvers_set,
                oidc_fetcher=oidc_fetcher,
                oidc_verifier=oidc_verifier,
            )
        except _ci_provenance.CiPredicateError as exc:
            msg = (
                f"phase autopilot start refused: CI authorization predicate failed "
                f"({exc.sub_reason}): {exc.message}"
            )
            print(f"error: {msg}", file=sys.stderr)
            return AutopilotResult(
                exit_code=exc.exit_code,
                sub_reason=exc.sub_reason,
                message=msg,
            )

        authorization_source = ci_result.authorization_source
        by = ci_result.bot_identity
        by_source = "env_ci_verified"
        ci_signature = ci_result.ci_signature
        ci_oidc_verified = ci_result.ci_oidc_verified
        ci_oidc_claims = ci_result.ci_oidc_claims
        bot_identity = ci_result.bot_identity
        bot_identity_distinct_from_approvers = ci_result.bot_identity_distinct_from_approvers

    # --allow-network source check (§3.5 line 643 + §3.5.1).
    #
    # Per-flag re-evaluation interpretation (P2-B1 design decision):
    # §3.5.1 says "follows the same predicate independently (per-flag re-evaluation)".
    # The §3.1.1 nonce protocol does NOT currently bind audience claims to specific
    # capability flags (allow_network is not part of the nonce audience string today).
    # Therefore, per-flag re-evaluation is implemented as AUDIT-LABEL ONLY:
    #   - allow_network_by_source records WHICH authorization path authorized this run.
    #   - This provides full auditability of who authorized network access and via what path.
    #   - Flag-specific re-authorization (e.g., nonce audience binding for allow_network)
    #     is deferred to a future slice when §3.1.1 nonce audience binding is extended.
    # Consequence: if allow_network=True, it is recorded as sourced from authorization_source
    # (i.e. the same TTY-human or CI path that authorized the run), NOT from a separate
    # allow_network-specific verification.
    #
    # The env-only-HARNESS_ALLOW_NETWORK path (without proper authorization) is NOT
    # honored: allow_network must be explicitly passed as True by the caller (which
    # means the caller parsed --allow-network from the CLI, not env alone).
    allow_network_by_source: Optional[str] = (
        authorization_source if allow_network else None
    )

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

    # Audit entry (§3.5 + §3.5.1 fields).
    now_iso = _phase_preflight.now_iso_z()

    # §3.5 / §1.1 integration (S10a step 2):
    # Stamp autopilot_started_at_iso as the wall-clock anchor for wall_seconds
    # budget enforcement. REPLACE semantics: each new run_start resets the anchor.
    after_state = _cli_budgets.stamp_autopilot_started_at(after_state, now_iso=now_iso)
    audit_draft: dict = {
        "verb": "phase.autopilot.start",
        "authorization_source": authorization_source,
        "mode": mode,
        "phase_slug": phase_slug,
        "budgets": resolved_budgets,
        "allow_network": allow_network,
        "allow_network_by_source": allow_network_by_source,
        "by": by,
        "by_source": by_source,
        "args": {
            "started_at": now_iso,
            "ci_signature": ci_signature,
            "ci_oidc_verified": ci_oidc_verified,
            "ci_oidc_claims": ci_oidc_claims,
            "bot_identity": bot_identity,
            "bot_identity_distinct_from_approvers": bot_identity_distinct_from_approvers,
        },
    }

    # Design decision (§1.1): autopilot_start_entry_hash MUST equal the
    # actual entry_hash of the verb=phase.autopilot.start audit entry (64 hex
    # chars, sha256 per ADR D-3). We use a TWO-PHASE COMMIT pattern:
    #   1. First commit_transaction with autopilot_start_entry_hash="PENDING"
    #      sentinel. This writes the audit row and stamps chain fields (including
    #      entry_hash) via audit_append.
    #   2. Read back the real entry_hash from the audit tail.
    #   3. Second commit_transaction with verb=phase.autopilot.start_hash_finalized
    #      that updates ONLY autopilot_start_entry_hash to the real hash.
    # This ensures the field is always a valid 64-hex entry_hash, not a
    # random token_hex, satisfying §1.1 without requiring a pre-computation
    # that would require locking the audit file during the state computation.
    after_state["autopilot_start_entry_hash"] = "PENDING"
    audit_draft["args"]["autopilot_start_entry_hash_ref"] = "PENDING"

    # P2-1: warn if user supplies shell_invocations budget (advisory-only in v0.7).
    if budgets and "shell_invocations" in budgets:
        print(
            "warning: --budget shell_invocations=N is ADVISORY in v0.7 "
            "(no decrement hook); treat as audit metadata only. "
            "Tracked OOS-shell-budget-hook for v0.8.",
            file=sys.stderr,
        )

    # P1-1: apply file_mutation_ops decrement for the first commit (caller-contract per §3.5).
    # NOTE: the SECOND commit (start_hash_finalized) is internal-only bookkeeping and
    # MUST NOT decrement again — it uses the exempted action name.
    after_state = _phase_txn.with_budget_decrement(after_state)

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

    # Phase 2: read real entry_hash from the audit tail and finalize.
    start_tail = _phase_txn._audit_tail_entry(audit_path)
    real_entry_hash: Optional[str] = (
        start_tail.get("entry_hash") if start_tail else None
    )
    if real_entry_hash and len(real_entry_hash) == 64:
        # Second commit: update autopilot_start_entry_hash to the real hash.
        finalize_before = dict(after_state)
        finalize_after = dict(after_state)
        finalize_after["autopilot_start_entry_hash"] = real_entry_hash
        finalize_audit = {
            "verb": "phase.autopilot.start_hash_finalized",
            "args": {
                "autopilot_start_entry_hash": real_entry_hash,
                "autopilot_run_id": new_run_id,
            },
        }
        _phase_txn.commit_transaction(
            scratch,
            lock=lock_handle,
            request=_phase_txn.TxnRequest(
                action="phase.autopilot.start_hash_finalized",
                before_state=finalize_before,
                after_state=finalize_after,
                audit_entry_draft=finalize_audit,
            ),
            audit_path=audit_path,
        )
        after_state = finalize_after

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
                "by": by,
                "by_source": by_source,
                "txn_id": txn_id,
            },
            indent=2,
            sort_keys=True,
        )
    )

    # §5.2 network deny shim: set HARNESS_AUTOPILOT_NETWORK=deny so that
    # subsequent harness-mediated subprocesses inherit the deny posture.
    # The env is set in the running process tree only; persistence is not
    # required (the process exits on `phase autopilot stop`).
    # Hard isolation (PATH-prepend installer) is deferred to S10d /
    # `harness install --autopilot-guards`.
    os.environ["HARNESS_AUTOPILOT_NETWORK"] = "deny"

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

    # Crash recovery (§3.5.2 line 312 — run BEFORE reading state).
    fail = _run_crash_recovery(scratch=scratch, audit_path=audit_path, lock=lock_handle)
    if fail is not None:
        return fail

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

    # §3.5 / §1.1 integration (S10a step 2):
    # Clear autopilot_started_at_iso so wall_seconds anchor is gone on stop.
    after_state = _cli_budgets.clear_autopilot_started_at(after_state)

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

    # Crash recovery (§3.5.2 line 319 — "next-pending acquires the state lock
    # briefly (consistent-snapshot read AFTER running crash recovery)").
    # Must run before any state read.
    cr_fail = _run_crash_recovery(scratch=scratch, audit_path=audit_path_p, lock=lock_handle)
    if cr_fail is not None:
        return NextPendingResult(
            exit_code=cr_fail.exit_code,
            next_slug="",
            all_done=False,
        )

    # Anchor preflight.
    fail = _run_anchor_preflight_for_autopilot(
        skip_anchor_preflight=skip_anchor_preflight,
        repo_root=repo_root,
    )
    if fail is not None:
        # Translate anchor failure to a NextPendingResult.
        return NextPendingResult(exit_code=fail.exit_code, next_slug="", all_done=False)

    av = anchor_verified if not skip_anchor_preflight else True

    # State-trust preflight.
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
    "_run_crash_recovery",
    "run_start",
    "run_stop",
    "run_next_pending",
]
