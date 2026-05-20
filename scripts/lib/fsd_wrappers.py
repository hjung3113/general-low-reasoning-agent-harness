"""`harness fsd-run-phase` and `harness fsd-run-all` wrapper logic (design §3.5).

These wrappers implement the adapter-safe contract described in §3.5 of the
phase-gate hardening design. They own slug parsing, `next-pending` delegation,
and autopilot start semantics. CLI argparse wiring is deferred to step 5.

Slug regex contract:
    ^[a-z0-9][a-z0-9-]{0,63}$
    - Must start with lowercase alphanumeric.
    - Max total length 64 (1 first char + up to 63 more).
    - Only lowercase letters, digits, and hyphens.

Wrapper entry points:
    run_fsd_run_phase(*, argument, ...)  — §3.5 fsd-run-phase adapter wrapper
    run_fsd_run_all(*, ...)              — §3.5 fsd-run-all chain wrapper

Fault sub_reasons introduced here:
    multi_token_argument    (exit 2) — argument contained whitespace
    slug_regex_mismatch     (exit 2) — single token but regex mismatch
    all_phases_done         (exit 0) — next-pending returned all_done

All other fault sub_reasons are forwarded from phase_autopilot.run_start via
the wrapped AutopilotResult.

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md
Sections: §3.5 (lines 632-660)
"""

from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from . import phase_autopilot as _phase_autopilot
from . import phase_lock as _phase_lock

# ---------------------------------------------------------------------------
# Slug contract (§3.5 canonical)
# ---------------------------------------------------------------------------

CANONICAL_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class FsdWrapperResult:
    """One invocation outcome for fsd-run-phase / fsd-run-all.

    `exit_code` is the final exit code the CLI should use.
    `sub_reason` is the machine-readable taxonomy bucket.
    `message` is a human-readable description.
    `autopilot_result` carries the delegate result if run_start was attempted.
    """

    exit_code: int
    sub_reason: str
    message: str = ""
    autopilot_result: Optional[_phase_autopilot.AutopilotResult] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_argument(argument: Optional[str]) -> tuple[Optional[str], Optional[FsdWrapperResult]]:
    """Validate the user-supplied argument per §3.5 wrapper contract.

    Returns (resolved_slug_or_None, None) on success:
        resolved_slug_or_None is None when next-pending must be called,
        or the single validated token to use as the phase slug.

    Returns (None, FsdWrapperResult) on validation error.
    """
    # Treat empty string same as None (both → next-pending path).
    if argument is None or argument == "":
        return None, None

    # Defensive multi-token check: shell expansion is the caller's job, but
    # detect whitespace defensively (§3.5: "multi-token → exit 2").
    if " " in argument or "\t" in argument:
        return None, FsdWrapperResult(
            exit_code=2,
            sub_reason="multi_token_argument",
            message=(
                f"fsd-run-phase refused: argument {argument!r} contains whitespace "
                "(multi-token after shell expansion). "
                "Fix: supply a single slug token, e.g. `harness fsd-run-phase 01-foo`. "
                "Spec: §3.5 canonical slug regex."
            ),
        )

    # Single token: validate against canonical slug regex.
    # Use fullmatch (not match) so trailing newline/whitespace is rejected —
    # Python's $ in re.match matches before a final \n, allowing "slug\n"
    # to pass incorrectly. fullmatch requires the ENTIRE string to match.
    if not CANONICAL_SLUG_RE.fullmatch(argument):
        return None, FsdWrapperResult(
            exit_code=2,
            sub_reason="slug_regex_mismatch",
            message=(
                f"fsd-run-phase refused: argument {argument!r} does not match "
                r"canonical slug regex ^[a-z0-9][a-z0-9-]{0,63}$ "
                "(must start with lowercase alphanumeric; only lowercase letters, "
                "digits, hyphens; max 64 chars). "
                "Fix: use a lowercase slug, e.g. `01-my-phase`. Spec: §3.5."
            ),
        )

    # Valid single token.
    return argument, None


def _resolve_next_pending(
    *,
    scratch_root: Path,
    audit_path: Path,
    lock_handle: Any,
    repo_root: Optional[Path],
    roadmap_root: Optional[Path],
) -> tuple[Optional[str], Optional[FsdWrapperResult]]:
    """Call run_next_pending (lock already held) and resolve the slug.

    Returns (slug, None) on success, or (None, FsdWrapperResult) if all done
    or if next_pending itself signals an error.
    """
    np_result = _phase_autopilot.run_next_pending(
        scratch_root=scratch_root,
        audit_path=audit_path,
        lock_handle=lock_handle,
        repo_root=repo_root,
        roadmap_root=roadmap_root,
    )

    if np_result.all_done or np_result.next_slug == "":
        return None, FsdWrapperResult(
            exit_code=0,
            sub_reason="all_phases_done",
            message="fsd-run-phase: all phases are done; nothing to start.",
        )

    if np_result.exit_code != 0:
        # Propagate error from next_pending.
        return None, FsdWrapperResult(
            exit_code=np_result.exit_code,
            sub_reason="next_pending_error",
            message=(
                f"fsd-run-phase refused: next-pending returned exit_code "
                f"{np_result.exit_code}."
            ),
        )

    return np_result.next_slug, None


# ---------------------------------------------------------------------------
# run_fsd_run_phase
# ---------------------------------------------------------------------------


def run_fsd_run_phase(
    *,
    argument: Optional[str],
    scratch_root: Path,
    audit_path: Path,
    repo_root: Optional[Path],
    env: Optional[Mapping[str, str]] = None,
    stdin_is_tty: Optional[bool] = None,
    consumer_tty: Optional[str] = None,
    nonce_audience: Optional[str] = None,
    nonce_dir: Optional[Path] = None,
    by_email: Optional[str] = None,
    install_record_root: Optional[Path] = None,
    oidc_fetcher: Optional[Callable] = None,
    oidc_verifier: Optional[Callable] = None,
    budgets: Optional[dict] = None,
    allow_network: bool = False,
    accept_degraded_windows_containment: bool = False,
    roadmap_root: Optional[Path] = None,
    # Deprecated alias (one release cycle): use consumer_tty instead.
    nonce_id: Optional[str] = None,
) -> FsdWrapperResult:
    """§3.5 `harness fsd-run-phase` wrapper.

    Argument contract:
        argument is None or ""          → call next-pending, use returned slug
        argument has whitespace         → exit 2 sub=multi_token_argument
        argument matches slug regex     → use as phase_slug, mode="phase"
        argument does NOT match regex   → exit 2 sub=slug_regex_mismatch

    Then: acquire lock → (optional) next-pending → run_start(mode="phase") →
    release lock.

    The wrapper holds the lock for the full duration and passes lock_handle
    into run_next_pending and run_start directly (they require lock already held).

    nonce_id is deprecated; use consumer_tty instead.
    """
    import warnings
    if nonce_id is not None:
        warnings.warn(
            "run_fsd_run_phase() kwarg 'nonce_id' is deprecated; use 'consumer_tty' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if consumer_tty is None:
            consumer_tty = nonce_id

    scratch_root = Path(scratch_root)
    audit_path = Path(audit_path)

    # Step 1: validate argument (before acquiring lock — cheap fail-fast).
    resolved_slug, err = _validate_argument(argument)
    if err is not None:
        print(f"error: {err.message}", file=sys.stderr)
        return err

    # Step 2: acquire primary lock.
    lock = _phase_lock.acquire_primary(scratch_root, timeout_s=10.0, audit_path=audit_path)
    try:
        # P1-2: wall-seconds check BEFORE any mutation (lock held, state trusted).
        import json as _json
        from . import cli_budgets as _cli_budgets
        _state_path = scratch_root / "phase-state.json"
        if _state_path.exists():
            _before_state = _json.loads(_state_path.read_text(encoding="utf-8"))
            _halt_exit = _cli_budgets.wall_seconds_check_and_maybe_halt(
                before_state=_before_state,
                scratch_root=scratch_root,
                audit_path=audit_path,
                lock_handle=lock,
            )
            if _halt_exit is not None:
                return FsdWrapperResult(
                    exit_code=_halt_exit,
                    sub_reason="budget_exhausted:wall_seconds",
                    message="wall_seconds budget exhausted; autopilot halted",
                )

        # Step 3: if no slug yet, call next-pending (lock already held).
        if resolved_slug is None:
            resolved_slug, err = _resolve_next_pending(
                scratch_root=scratch_root,
                audit_path=audit_path,
                lock_handle=lock,
                repo_root=repo_root,
                roadmap_root=roadmap_root,
            )
            if err is not None:
                if err.sub_reason != "all_phases_done":
                    print(f"error: {err.message}", file=sys.stderr)
                return err

        # Step 4: call run_start with mode="phase".
        ap_result = _phase_autopilot.run_start(
            scratch_root=scratch_root,
            audit_path=audit_path,
            lock_handle=lock,
            phase_slug=resolved_slug,
            mode="phase",
            budgets=budgets,
            allow_network=allow_network,
            accept_degraded_windows_containment=accept_degraded_windows_containment,
            repo_root=repo_root,
            roadmap_root=roadmap_root,
            env=env,
            stdin_is_tty=stdin_is_tty,
            consumer_tty=consumer_tty,
            nonce_audience=nonce_audience,
            nonce_dir=nonce_dir,
            by_email=by_email,
            install_record_root=install_record_root,
            oidc_fetcher=oidc_fetcher,
            oidc_verifier=oidc_verifier,
        )

        return FsdWrapperResult(
            exit_code=ap_result.exit_code,
            sub_reason=ap_result.sub_reason,
            message=ap_result.message,
            autopilot_result=ap_result,
        )
    finally:
        _phase_lock.release_primary(lock)


# ---------------------------------------------------------------------------
# run_fsd_run_all
# ---------------------------------------------------------------------------


def run_fsd_run_all(
    *,
    scratch_root: Path,
    audit_path: Path,
    repo_root: Optional[Path],
    env: Optional[Mapping[str, str]] = None,
    stdin_is_tty: Optional[bool] = None,
    consumer_tty: Optional[str] = None,
    nonce_audience: Optional[str] = None,
    nonce_dir: Optional[Path] = None,
    by_email: Optional[str] = None,
    install_record_root: Optional[Path] = None,
    oidc_fetcher: Optional[Callable] = None,
    oidc_verifier: Optional[Callable] = None,
    budgets: Optional[dict] = None,
    allow_network: bool = False,
    accept_degraded_windows_containment: bool = False,
    roadmap_root: Optional[Path] = None,
    # Deprecated alias (one release cycle): use consumer_tty instead.
    nonce_id: Optional[str] = None,
) -> FsdWrapperResult:
    """§3.5 `harness fsd-run-all` chain wrapper.

    Always uses next-pending to select the phase slug, then calls
    run_start with mode="chain". No user-supplied slug argument.

    Lock contract: acquire once → next-pending (lock held) → run_start (lock
    held) → release in finally.

    nonce_id is deprecated; use consumer_tty instead.
    """
    import warnings
    if nonce_id is not None:
        warnings.warn(
            "run_fsd_run_all() kwarg 'nonce_id' is deprecated; use 'consumer_tty' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if consumer_tty is None:
            consumer_tty = nonce_id

    scratch_root = Path(scratch_root)
    audit_path = Path(audit_path)

    # Acquire primary lock.
    lock = _phase_lock.acquire_primary(scratch_root, timeout_s=10.0, audit_path=audit_path)
    try:
        # P1-2: wall-seconds check BEFORE any mutation (lock held, state trusted).
        import json as _json
        from . import cli_budgets as _cli_budgets
        _state_path = scratch_root / "phase-state.json"
        if _state_path.exists():
            _before_state = _json.loads(_state_path.read_text(encoding="utf-8"))
            _halt_exit = _cli_budgets.wall_seconds_check_and_maybe_halt(
                before_state=_before_state,
                scratch_root=scratch_root,
                audit_path=audit_path,
                lock_handle=lock,
            )
            if _halt_exit is not None:
                return FsdWrapperResult(
                    exit_code=_halt_exit,
                    sub_reason="budget_exhausted:wall_seconds",
                    message="wall_seconds budget exhausted; autopilot halted",
                )

        # Call next-pending (lock held).
        resolved_slug, err = _resolve_next_pending(
            scratch_root=scratch_root,
            audit_path=audit_path,
            lock_handle=lock,
            repo_root=repo_root,
            roadmap_root=roadmap_root,
        )
        if err is not None:
            if err.sub_reason != "all_phases_done":
                print(f"error: {err.message}", file=sys.stderr)
            return err

        # Call run_start with mode="chain".
        ap_result = _phase_autopilot.run_start(
            scratch_root=scratch_root,
            audit_path=audit_path,
            lock_handle=lock,
            phase_slug=resolved_slug,
            mode="chain",
            budgets=budgets,
            allow_network=allow_network,
            accept_degraded_windows_containment=accept_degraded_windows_containment,
            repo_root=repo_root,
            roadmap_root=roadmap_root,
            env=env,
            stdin_is_tty=stdin_is_tty,
            consumer_tty=consumer_tty,
            nonce_audience=nonce_audience,
            nonce_dir=nonce_dir,
            by_email=by_email,
            install_record_root=install_record_root,
            oidc_fetcher=oidc_fetcher,
            oidc_verifier=oidc_verifier,
        )

        return FsdWrapperResult(
            exit_code=ap_result.exit_code,
            sub_reason=ap_result.sub_reason,
            message=ap_result.message,
            autopilot_result=ap_result,
        )
    finally:
        _phase_lock.release_primary(lock)


__all__ = [
    "CANONICAL_SLUG_RE",
    "FsdWrapperResult",
    "run_fsd_run_phase",
    "run_fsd_run_all",
]
