"""CLI handlers for `phase autopilot start|stop|next-pending` and
`fsd-run-phase` / `fsd-run-all` (design §3.5).

Wired from ``scripts/harness.py`` argparse dispatch. Each handler follows
the same pattern as ``scripts/lib/phase_cli.py``: accept an
``argparse.Namespace``, delegate to the underlying module, map the result's
``exit_code`` to ``sys.exit``.

Anchor wiring (§12.1 fail-closed pattern)
------------------------------------------
Each handler that calls ``run_start`` directly attempts to verify the
out-of-repo audit-tip anchor via ``audit_anchor.verify_existing_anchor_for_repo``.
On success ``anchor_verified=True`` is passed downstream. On any
``AnchorError`` (missing / mismatch / unreadable) the handler prints the
structured error to stderr and returns exit 6 — identical to the
``phase_approve.run_approve`` pattern after the S02 review-fix.

When the handler delegates to ``fsd_wrappers.run_fsd_run_phase`` or
``run_fsd_run_all``, those wrappers pass ``skip_anchor_preflight=(repo_root is None)``
internally; the CLI sets ``repo_root=cwd`` so the wrapper does the check.

OIDC gap note
--------------
``oidc_fetcher=None`` / ``oidc_verifier=None`` are passed to ``run_start``
and the fsd wrappers. ``ci_provenance`` will fall back to its TEST-ONLY
stubs (``HARNESS_TEST_OIDC_TOKEN_*`` / ``HARNESS_TEST_OIDC_CLAIMS_*`` env
vars). Production real-OIDC HTTP+JWT wiring is deferred to a later slice.

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md
Sections: §3.5, §3.5.1, §3.4
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths (CWD-relative, following phase_cli.py convention)
# ---------------------------------------------------------------------------

SCRATCH_ROOT = Path(".scratch")
AUDIT_PATH = Path(".harness") / "audit.log"
HARNESS_DIR = Path(".harness")
INSTALL_RECORD_ROOT = Path(".")  # install-record.json is at .harness/install-record.json


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _walk_up_for_repo_root(start: Path) -> Path:
    """Walk parent directories looking for ``.git/`` or ``.harness/``.

    Returns the first ancestor directory that contains either marker.
    Raises ``FileNotFoundError`` if neither is found before the filesystem root.

    This is needed so ``harness phase autopilot start`` works correctly when
    invoked from a subdirectory of the repo (e.g. ``scripts/`` or ``src/``).
    Without walk-up, ``.harness/install-record.json`` is not found, the
    approvers_set stays empty, and the ``if approvers_set and ...`` guard
    silently accepts any email (P1-A2 bypass).
    """
    cur = start.resolve()
    while True:
        if (cur / ".git").exists() or (cur / ".harness").exists():
            return cur
        if cur.parent == cur:
            raise FileNotFoundError(
                f"No .git/ or .harness/ directory found walking up from {start} "
                "to the filesystem root. Ensure you are inside a harness-managed "
                "repository before running autopilot commands."
            )
        cur = cur.parent


def _cwd_repo_root() -> Path:
    """Return the repo root by walking up from CWD to the first .git/.harness ancestor.

    Raises FileNotFoundError if no repo root is found.
    """
    return _walk_up_for_repo_root(Path.cwd())


MAX_BUDGET_VALUE = 10_000_000  # upper bound for any single budget integer (P2-B2)


def _parse_budgets(budget_list: Optional[list]) -> Optional[dict]:
    """Parse repeated ``--budget key=value`` flags into a dict.

    Example: ``["shell_invocations=100", "wall_seconds=300"]``
             → ``{"shell_invocations": 100, "wall_seconds": 300}``

    Only non-negative integers in [0, MAX_BUDGET_VALUE] are accepted.
    Malformed, negative, or oversized values cause exit 2 with a clear error.
    """
    if not budget_list:
        return None
    result: dict = {}
    for item in budget_list:
        if "=" not in item:
            print(
                f"error: --budget item {item!r} is malformed "
                "(expected key=value format, e.g. shell_invocations=100)",
                file=sys.stderr,
            )
            raise SystemExit(2)
        key, _, raw_val = item.partition("=")
        key = key.strip()
        raw_val = raw_val.strip()
        try:
            val = int(raw_val)
        except ValueError:
            print(
                f"error: --budget item {item!r} has non-integer value {raw_val!r} "
                "(budget values must be non-negative integers)",
                file=sys.stderr,
            )
            raise SystemExit(2)
        if val < 0:
            print(
                f"error: --budget item {item!r} has negative value {val} "
                "(budget values must be >= 0)",
                file=sys.stderr,
            )
            raise SystemExit(2)
        if val > MAX_BUDGET_VALUE:
            print(
                f"error: --budget item {item!r} has value {val} exceeding "
                f"maximum allowed budget value {MAX_BUDGET_VALUE}",
                file=sys.stderr,
            )
            raise SystemExit(2)
        result[key] = val
    return result or None


def _verify_anchor(cwd: Path) -> tuple[bool, int, str]:
    """Verify the out-of-repo audit-tip anchor for *cwd*.

    Returns ``(anchor_verified, exit_code, sub_reason)``.
    On success: ``(True, 0, "")``.
    On failure: ``(False, 6, "<sub_reason>")``.
    """
    from . import audit_anchor as _audit_anchor  # lazy import

    try:
        _audit_anchor.verify_existing_anchor_for_repo(cwd)
        return True, 0, ""
    except _audit_anchor.AnchorMissingError as exc:
        print(
            f"error: phase autopilot start refused: audit-tip anchor not found "
            f"({exc}). "
            "Fix: run 'harness anchor repair' to rebuild the anchor from current state.",
            file=sys.stderr,
        )
        return False, 6, "anchor_missing"
    except _audit_anchor.AnchorMismatchError as exc:
        sub = exc.sub_reason or "anchor_verification_failed"
        print(
            f"error: phase autopilot start refused: audit-tip anchor "
            f"verification failed ({sub}: {exc}). "
            "Fix: run 'harness verify --audit' and 'harness anchor repair'.",
            file=sys.stderr,
        )
        return False, 6, sub
    except Exception as exc:  # AnchorError or unexpected
        sub = getattr(exc, "sub_reason", None) or "anchor_error"
        print(
            f"error: phase autopilot start refused: audit-tip anchor "
            f"unreadable ({sub}: {exc}). "
            "Fix: run 'harness verify --audit' and 'harness anchor repair'.",
            file=sys.stderr,
        )
        return False, 6, sub


# ---------------------------------------------------------------------------
# cmd_phase_autopilot_start
# ---------------------------------------------------------------------------


def cmd_phase_autopilot_start(args) -> int:  # type: ignore[no-untyped-def]
    """Handle ``harness phase autopilot start`` (§3.5).

    Acquires lock, verifies anchor, resolves authorization inputs, calls
    ``phase_autopilot.run_start``, releases lock.
    """
    from . import phase_autopilot as _phase_autopilot
    from . import phase_lock as _phase_lock
    from . import phase_preflight as _phase_preflight

    try:
        cwd = _cwd_repo_root()
    except FileNotFoundError as exc:
        print(
            f"error: phase autopilot start refused: {exc}. "
            "Fix: run from inside a harness-managed repository.",
            file=sys.stderr,
        )
        return 6

    scratch = cwd / SCRATCH_ROOT
    audit_path = cwd / AUDIT_PATH

    # Anchor verification (fail-closed per §12.1 + S02 review-fix P1-1).
    anchor_verified, anchor_exit, anchor_sub = _verify_anchor(cwd)
    if not anchor_verified:
        return anchor_exit

    # Resolve --by email (fall back to gitconfig).
    by_email: Optional[str] = getattr(args, "by", None)
    if by_email is None:
        try:
            by_email = _phase_preflight.default_gitconfig_email_lookup()
        except Exception:
            by_email = None

    # Resolve consumer_tty kwargs from --consumer-tty (or legacy --nonce-id).
    consumer_tty: Optional[str] = getattr(args, "consumer_tty", None)
    if consumer_tty is None:
        consumer_tty = getattr(args, "nonce_id", None)  # legacy compat
    nonce_audience: Optional[str] = "phase.autopilot.start"
    nonce_dir_raw: Optional[str] = getattr(args, "nonce_dir", None)
    nonce_dir: Optional[Path] = Path(nonce_dir_raw) if nonce_dir_raw else None

    # Parse --budget entries.
    budget_list = getattr(args, "budget", None)
    budgets = _parse_budgets(budget_list)

    # Mode (default "phase").
    mode: str = getattr(args, "mode", None) or "phase"

    # Phase slug from --phase.
    phase_slug: Optional[str] = getattr(args, "phase_slug", None)

    # Flags.
    allow_network: bool = bool(getattr(args, "allow_network", False))
    accept_degraded: bool = bool(getattr(args, "accept_degraded_windows_containment", False))

    # Detect TTY.
    stdin_is_tty: bool = sys.stdin.isatty()

    # Roadmap root relative to cwd.
    roadmap_root: Optional[Path] = cwd / ".planning" / "phases"
    if not roadmap_root.is_dir():
        roadmap_root = None

    # Acquire lock.
    lock = _phase_lock.acquire_primary(scratch, timeout_s=30.0, audit_path=audit_path)
    try:
        result = _phase_autopilot.run_start(
            scratch_root=scratch,
            audit_path=audit_path,
            lock_handle=lock,
            phase_slug=phase_slug,
            mode=mode,
            budgets=budgets,
            allow_network=allow_network,
            anchor_verified=anchor_verified,
            skip_anchor_preflight=False,  # anchor already verified above
            accept_degraded_windows_containment=accept_degraded,
            repo_root=cwd,
            roadmap_root=roadmap_root,
            env=os.environ,
            stdin_is_tty=stdin_is_tty,
            consumer_tty=consumer_tty,
            nonce_audience=nonce_audience,
            nonce_dir=nonce_dir,
            by_email=by_email,
            install_record_root=cwd,
            oidc_fetcher=None,   # production OIDC wiring deferred; needs HARNESS_OIDC_TEST_MODE=1 for stubs
            oidc_verifier=None,  # production OIDC wiring deferred; needs HARNESS_OIDC_TEST_MODE=1 for stubs
        )
    finally:
        _phase_lock.release_primary(lock)

    if result.message and result.exit_code != 0:
        # Message already printed by run_start; nothing extra needed.
        pass
    elif result.exit_code == 0:
        print(
            json.dumps(
                {
                    "ok": True,
                    "verb": "phase.autopilot.start",
                    "autopilot_run_id": result.autopilot_run_id,
                    "sub_reason": result.sub_reason,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return result.exit_code


# ---------------------------------------------------------------------------
# cmd_phase_autopilot_stop
# ---------------------------------------------------------------------------


def cmd_phase_autopilot_stop(args) -> int:  # type: ignore[no-untyped-def]
    """Handle ``harness phase autopilot stop`` (§3.5).

    Idempotent: if already manual, exits 0. Otherwise clears autopilot fields
    and audits verb=phase.autopilot.stop.
    """
    from . import phase_autopilot as _phase_autopilot
    from . import phase_lock as _phase_lock

    try:
        cwd = _cwd_repo_root()
    except FileNotFoundError as exc:
        print(
            f"error: phase autopilot stop refused: {exc}. "
            "Fix: run from inside a harness-managed repository.",
            file=sys.stderr,
        )
        return 6

    scratch = cwd / SCRATCH_ROOT
    audit_path = cwd / AUDIT_PATH

    # Anchor verification (fail-closed).
    anchor_verified, anchor_exit, _sub = _verify_anchor(cwd)
    if not anchor_verified:
        return anchor_exit

    reason: str = getattr(args, "reason", None) or ""

    lock = _phase_lock.acquire_primary(scratch, timeout_s=30.0, audit_path=audit_path)
    try:
        result = _phase_autopilot.run_stop(
            scratch_root=scratch,
            audit_path=audit_path,
            lock_handle=lock,
            reason=reason,
            anchor_verified=anchor_verified,
            skip_anchor_preflight=False,
            repo_root=cwd,
        )
    finally:
        _phase_lock.release_primary(lock)

    if result.exit_code != 0 and result.message:
        print(f"error: {result.message}", file=sys.stderr)
    return result.exit_code


# ---------------------------------------------------------------------------
# cmd_phase_next_pending
# ---------------------------------------------------------------------------


def cmd_phase_next_pending(args) -> int:  # type: ignore[no-untyped-def]
    """Handle ``harness phase next-pending`` (§3.5).

    Pure read: prints the next non-done phase slug, or "all done" sentinel.
    No state mutation, no audit row.
    """
    from . import phase_autopilot as _phase_autopilot
    from . import phase_lock as _phase_lock

    try:
        cwd = _cwd_repo_root()
    except FileNotFoundError as exc:
        print(
            f"error: phase next-pending refused: {exc}. "
            "Fix: run from inside a harness-managed repository.",
            file=sys.stderr,
        )
        return 6

    scratch = cwd / SCRATCH_ROOT
    audit_path = cwd / AUDIT_PATH

    # Anchor verification (fail-closed).
    anchor_verified, anchor_exit, _sub = _verify_anchor(cwd)
    if not anchor_verified:
        return anchor_exit

    roadmap_root: Optional[Path] = cwd / ".planning" / "phases"
    if not roadmap_root.is_dir():
        roadmap_root = None

    lock = _phase_lock.acquire_primary(scratch, timeout_s=30.0, audit_path=audit_path)
    try:
        result = _phase_autopilot.run_next_pending(
            scratch_root=scratch,
            audit_path=audit_path,
            lock_handle=lock,
            anchor_verified=anchor_verified,
            skip_anchor_preflight=False,
            repo_root=cwd,
            roadmap_root=roadmap_root,
        )
    finally:
        _phase_lock.release_primary(lock)

    if result.exit_code != 0:
        print(
            f"error: next-pending failed with exit {result.exit_code}",
            file=sys.stderr,
        )
        return result.exit_code

    if result.all_done or not result.next_slug:
        print("all done")
    else:
        print(result.next_slug)
    return 0


# ---------------------------------------------------------------------------
# cmd_fsd_run_phase
# ---------------------------------------------------------------------------


def cmd_fsd_run_phase(args) -> int:  # type: ignore[no-untyped-def]
    """Handle ``harness fsd-run-phase [<slug>]`` (§3.5).

    Delegates to ``fsd_wrappers.run_fsd_run_phase``. Argument may be None
    (next-pending is called) or a single slug token (validated by wrapper).
    """
    from . import fsd_wrappers as _fsd_wrappers
    from . import phase_preflight as _phase_preflight

    try:
        cwd = _cwd_repo_root()
    except FileNotFoundError as exc:
        print(
            f"error: fsd-run-phase refused: {exc}. "
            "Fix: run from inside a harness-managed repository.",
            file=sys.stderr,
        )
        return 6

    scratch = cwd / SCRATCH_ROOT
    audit_path = cwd / AUDIT_PATH

    # Anchor: delegate verification to fsd_wrappers (via repo_root=cwd).
    # run_fsd_run_phase passes skip_anchor_preflight=(repo_root is None)
    # so by supplying repo_root=cwd we enable the anchor check inside run_start.
    # We also pre-verify here and pass anchor_verified so the inner call
    # doesn't double-fail.
    anchor_verified, anchor_exit, _sub = _verify_anchor(cwd)
    if not anchor_verified:
        return anchor_exit

    # nargs="?" positional: None if absent, str if supplied.
    argument: Optional[str] = getattr(args, "slug", None)

    # Resolve --by email.
    by_email: Optional[str] = getattr(args, "by", None)
    if by_email is None:
        try:
            by_email = _phase_preflight.default_gitconfig_email_lookup()
        except Exception:
            by_email = None

    consumer_tty: Optional[str] = getattr(args, "consumer_tty", None)
    if consumer_tty is None:
        consumer_tty = getattr(args, "nonce_id", None)  # legacy compat
    nonce_dir_raw: Optional[str] = getattr(args, "nonce_dir", None)
    nonce_dir: Optional[Path] = Path(nonce_dir_raw) if nonce_dir_raw else None

    budget_list = getattr(args, "budget", None)
    budgets = _parse_budgets(budget_list)
    allow_network: bool = bool(getattr(args, "allow_network", False))
    accept_degraded: bool = bool(getattr(args, "accept_degraded_windows_containment", False))

    roadmap_root: Optional[Path] = cwd / ".planning" / "phases"
    if not roadmap_root.is_dir():
        roadmap_root = None

    result = _fsd_wrappers.run_fsd_run_phase(
        argument=argument,
        scratch_root=scratch,
        audit_path=audit_path,
        repo_root=cwd,
        env=os.environ,
        stdin_is_tty=sys.stdin.isatty(),
        consumer_tty=consumer_tty,
        nonce_audience="phase.autopilot.start",
        nonce_dir=nonce_dir,
        by_email=by_email,
        install_record_root=cwd,
        oidc_fetcher=None,   # production OIDC wiring deferred; needs HARNESS_OIDC_TEST_MODE=1 for stubs
        oidc_verifier=None,  # production OIDC wiring deferred; needs HARNESS_OIDC_TEST_MODE=1 for stubs
        budgets=budgets,
        allow_network=allow_network,
        accept_degraded_windows_containment=accept_degraded,
        anchor_verified=anchor_verified,
        roadmap_root=roadmap_root,
    )

    if result.exit_code != 0 and result.message:
        # Error messages already printed by the wrapper internals.
        pass
    elif result.exit_code == 0:
        print(
            json.dumps(
                {
                    "ok": True,
                    "verb": "fsd-run-phase",
                    "sub_reason": result.sub_reason,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return result.exit_code


# ---------------------------------------------------------------------------
# cmd_fsd_run_all
# ---------------------------------------------------------------------------


def cmd_fsd_run_all(args) -> int:  # type: ignore[no-untyped-def]
    """Handle ``harness fsd-run-all`` (§3.5).

    Delegates to ``fsd_wrappers.run_fsd_run_all``. Always calls next-pending
    then run_start with mode="chain".
    """
    from . import fsd_wrappers as _fsd_wrappers
    from . import phase_preflight as _phase_preflight

    try:
        cwd = _cwd_repo_root()
    except FileNotFoundError as exc:
        print(
            f"error: fsd-run-all refused: {exc}. "
            "Fix: run from inside a harness-managed repository.",
            file=sys.stderr,
        )
        return 6

    scratch = cwd / SCRATCH_ROOT
    audit_path = cwd / AUDIT_PATH

    # Anchor verification (fail-closed).
    anchor_verified, anchor_exit, _sub = _verify_anchor(cwd)
    if not anchor_verified:
        return anchor_exit

    by_email: Optional[str] = getattr(args, "by", None)
    if by_email is None:
        try:
            by_email = _phase_preflight.default_gitconfig_email_lookup()
        except Exception:
            by_email = None

    consumer_tty: Optional[str] = getattr(args, "consumer_tty", None)
    if consumer_tty is None:
        consumer_tty = getattr(args, "nonce_id", None)  # legacy compat
    nonce_dir_raw: Optional[str] = getattr(args, "nonce_dir", None)
    nonce_dir: Optional[Path] = Path(nonce_dir_raw) if nonce_dir_raw else None

    budget_list = getattr(args, "budget", None)
    budgets = _parse_budgets(budget_list)
    allow_network: bool = bool(getattr(args, "allow_network", False))
    accept_degraded: bool = bool(getattr(args, "accept_degraded_windows_containment", False))

    roadmap_root: Optional[Path] = cwd / ".planning" / "phases"
    if not roadmap_root.is_dir():
        roadmap_root = None

    result = _fsd_wrappers.run_fsd_run_all(
        scratch_root=scratch,
        audit_path=audit_path,
        repo_root=cwd,
        env=os.environ,
        stdin_is_tty=sys.stdin.isatty(),
        consumer_tty=consumer_tty,
        nonce_audience="phase.autopilot.start",
        nonce_dir=nonce_dir,
        by_email=by_email,
        install_record_root=cwd,
        oidc_fetcher=None,   # production OIDC wiring deferred; needs HARNESS_OIDC_TEST_MODE=1 for stubs
        oidc_verifier=None,  # production OIDC wiring deferred; needs HARNESS_OIDC_TEST_MODE=1 for stubs
        budgets=budgets,
        allow_network=allow_network,
        accept_degraded_windows_containment=accept_degraded,
        anchor_verified=anchor_verified,
        roadmap_root=roadmap_root,
    )

    if result.exit_code != 0 and result.message:
        pass  # Messages already printed by wrapper internals.
    elif result.exit_code == 0:
        print(
            json.dumps(
                {
                    "ok": True,
                    "verb": "fsd-run-all",
                    "sub_reason": result.sub_reason,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return result.exit_code


# ---------------------------------------------------------------------------
# _wall_seconds_check_and_maybe_halt — budget guard helper
# ---------------------------------------------------------------------------


def _wall_seconds_check_and_maybe_halt(
    *,
    before_state: dict,
    scratch_root,
    audit_path,
    lock_handle,
    now_iso: str | None = None,
) -> int | None:
    """If autopilot is active and wall_seconds budget exhausted, apply halt +
    commit the halted state and return exit code 9.  Otherwise return None
    (caller should proceed normally).

    Design (§3.5 / §5.3 / S10a step 2):
      - Only fires when execution_mode != "manual".
      - Uses cli_budgets.budget_check(capability="wall_seconds").
      - On exhaustion: build diary → apply_budget_halt → commit halted state
        (manual mode so the budget check in commit_transaction is bypassed).
      - Returns 9 on exhaustion, None on OK.

    Position contract: call AFTER state-trust preflight (state is trusted),
    BEFORE verb-specific mutation logic.  The caller MUST hold the lock.

    shell_invocations enforcement note: shell_invocations is NOT checked here
    (S10a step 2 limited-enforcement scope: the harness CLI itself does not
    heavily shell out; shell_invocations is stamped at start + checked only
    if a future step wires subprocess counting).
    """
    from . import cli_budgets as _cli_budgets
    from . import phase_txn as _phase_txn
    from . import phase_preflight as _phase_preflight
    from pathlib import Path

    # Only enforce when autopilot is active.
    exec_mode = before_state.get("execution_mode", "manual")
    if exec_mode == "manual":
        return None

    _now = now_iso or _phase_preflight.now_iso_z()
    check = _cli_budgets.budget_check(
        before_state,
        capability="wall_seconds",
        now_iso=_now,
    )
    if not check.exhausted:
        return None

    # Budget exhausted: build diary, apply halt, commit.
    diary = _cli_budgets.build_budget_halt_diary(
        result=check,
        state=before_state,
        now_iso=_now,
    )
    halted_state = _cli_budgets.apply_budget_halt(before_state, diary=diary)

    scratch = Path(scratch_root)
    audit_path_p = Path(audit_path)

    try:
        _phase_txn.commit_transaction(
            scratch,
            lock=lock_handle,
            request=_phase_txn.TxnRequest(
                action="phase.autopilot.halt.budget",
                before_state=before_state,
                after_state=halted_state,
                audit_entry_draft={
                    "verb": "phase.autopilot.halt",
                    "args": {
                        "reason": diary.reason,
                        "capability": diary.capability,
                        "remaining_at_halt": diary.remaining_at_halt,
                        "halted_at": _now,
                    },
                },
            ),
            audit_path=audit_path_p,
        )
    except Exception:
        # If the halt commit itself fails, still return 9 so the caller
        # knows not to proceed with the original mutation.
        pass

    return 9


__all__ = [
    "cmd_phase_autopilot_start",
    "cmd_phase_autopilot_stop",
    "cmd_phase_next_pending",
    "cmd_fsd_run_phase",
    "cmd_fsd_run_all",
    "_parse_budgets",
    "_verify_anchor",
    "_walk_up_for_repo_root",
    "_cwd_repo_root",
    "_wall_seconds_check_and_maybe_halt",
]
