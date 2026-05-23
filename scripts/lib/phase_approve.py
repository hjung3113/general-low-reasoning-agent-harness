"""`phase approve` — interactive speed-bump gate.

Stamps the *current* phase as approved. Does NOT advance to the next phase;
use ``phase set <next>`` to advance after stamping.

Order of operations (any failure → typed ``ApproveResult`` with non-zero
``exit_code``; the CLI dispatcher maps to ``sys.exit``):

  1. TTY gate. ``stdin_isatty=False`` → exit 17 ``non_tty_approval_blocked``.
     HARNESS_BY_TRUST / HARNESS_HUMAN are NEVER consulted on this path.
  2. Identity resolution. ``--by`` if provided, else ``git config user.email``.
     Empty → exit 6 ``gitconfig_email_unset``.
  3. install-record presence check (no membership gate — ADR-0002).
  4. Load state under primary lock.
  5. ``state.execution_mode != "manual"`` → exit 8 ``approve_during_autopilot``.
  6. Idempotency check: ``state.approved == True`` → exit 0 ``already_approved``.
  7. Phase guard. Phase not in ``{plan, execute}`` → refuses with EXIT_WRONG_PHASE_FOR_VERB.
  8. Prompt ``[y/N]`` on TTY. Non-y answer, EOF, or Ctrl+C → exit 0
     + sub_reason=user_cancelled.
  9. State + audit mutation via ``phase_txn.commit_transaction``.
     Audit row records ``proof_class: soft_tty``.

ADR : ``docs/adr/0002-internal-tool-threat-model.md`` (no attacker model —
      override-identity, gitconfig fingerprint, and sanitizer machinery removed in M5).
ADR : ``docs/adr/0001-execution-is-always-manual.md`` (actor field kept for attribution).
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

from . import exitcodes as _exitcodes
from . import phase_lock as _phase_lock
from . import phase_preflight as _phase_preflight
from . import phase_txn as _phase_txn


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ApproveResult:
    """One invocation outcome. `exit_code` MUST be one of the design
    §3.4 codes; `sub_reason` is the machine-readable taxonomy bucket
    used by smoke and reviewers."""

    exit_code: int
    sub_reason: str
    resolved_email: Optional[str] = None
    by_source: Optional[str] = None  # "gitconfig_auto" | "explicit_by_flag"


# ---------------------------------------------------------------------------
# Fix-line messages (every error MUST carry a remediation)
# ---------------------------------------------------------------------------


_FIX_TTY = (
    "Fix: run `harness phase approve` from a real terminal "
    "(not via a piped or agent-spawned subprocess)"
)
_FIX_GITCONFIG = (
    "Fix: run `git config user.email <your-email>` "
    "or pass `harness phase approve --by <your-email>`"
)
_FIX_AUTOPILOT = (
    "Fix: run `harness phase autopilot stop --reason \"<text>\"` "
    "first, then re-approve"
)


# ---------------------------------------------------------------------------
# TTY kind label helper
# ---------------------------------------------------------------------------

def _tty_kind(tty_path: str) -> str:
    """Return the kind label for a TTY path string.

    Labels: ``win-synthetic`` | ``posix-fallback`` | ``posix-real`` | ``unknown``.
    Empty string or unrecognised paths return ``unknown`` rather than lying
    with ``posix-real``.
    """
    if not tty_path:
        return "unknown"
    if tty_path.startswith("win:"):
        return "win-synthetic"
    if tty_path.startswith("posix:"):
        return "posix-fallback"
    if tty_path.startswith("/dev/"):
        return "posix-real"
    return "unknown"


# ---------------------------------------------------------------------------
# Helpers — git config lookup + identity resolution
# ---------------------------------------------------------------------------


# Backward-compat shims — these names existed pre-refactor. Tests
# monkeypatch them and other callers import them, so the shape is
# preserved. The bodies delegate to `phase_preflight` (P2-3 extraction).

def default_gitconfig_email_lookup() -> str:
    """Run `git config user.email`. Empty string on any failure."""
    return _phase_preflight.default_gitconfig_email_lookup()


def _load_install_record(path: Path) -> dict:
    return _phase_preflight.load_install_record(path)


def _now_iso_z() -> str:
    return _phase_preflight.now_iso_z()


# ---------------------------------------------------------------------------
# Identity resolver (tiny pure helper)
# ---------------------------------------------------------------------------


def resolve_approval_identity(
    args,
    lookup: Optional[Callable[[], str]] = None,
) -> tuple[str, str]:
    """Resolve the approver identity from ``--by`` or gitconfig.

    Returns ``(email, by_source)`` where ``by_source`` is
    ``"explicit_by_flag"`` or ``"gitconfig_auto"``.
    Raises nothing — empty string means unresolved (caller exits).
    """
    by_flag = getattr(args, "by", None)
    if by_flag:
        return by_flag.strip(), "explicit_by_flag"
    fn = lookup or default_gitconfig_email_lookup
    return fn().strip(), "gitconfig_auto"


# ---------------------------------------------------------------------------
# Pure handler
# ---------------------------------------------------------------------------


def run_approve(
    args,
    *,
    scratch: Path,
    harness_dir: Path,
    audit_path: Path,
    install_record_path: Path,
    stdin_isatty: bool,
    consumer_tty: str,
    gitconfig_email_lookup: Optional[Callable[[], str]] = None,
    env_vars: Optional[Mapping[str, str]] = None,
    repo_root: Optional[Path] = None,
) -> ApproveResult:
    """Execute the approval sequence. Returns a structured result.

    Dependency injection points (all default to real OS/git when not
    provided) make the function unit-testable without TTY allocation or
    real ~/.harness contents.

    Note on `env_vars`: passed in explicitly so tests can verify that
    `HARNESS_BY_TRUST` / `HARNESS_HUMAN` do NOT influence the path —
    this verb has zero env-trust (ADR-0002).
    """
    scratch = Path(scratch)
    harness_dir = Path(harness_dir)
    audit_path = Path(audit_path)
    install_record_path = Path(install_record_path)
    if env_vars is None:
        env_vars = os.environ
    # env_vars is intentionally never consulted for identity resolution.
    del env_vars

    # ---------- Smoke-test bypass ----------
    # ONLY active when BOTH env vars are set to "1". Production callers never
    # set HARNESS_SMOKE_TEST, so this branch is unreachable in production.
    # When active: TTY gate + [y/N] prompt are skipped; ALL other checks
    # (identity, audit) still run.
    if (
        os.environ.get("HARNESS_SMOKE_BYPASS_SPEED_BUMP") == "1"
        and os.environ.get("HARNESS_SMOKE_TEST") == "1"
    ):
        _smoke_bypass_active = True
    else:
        _smoke_bypass_active = False

    # ---------- Step 1: TTY gate ----------
    if not _smoke_bypass_active and not stdin_isatty:
        print(
            f"error: phase approve refused: non-TTY caller "
            f"(agent-spawned subprocess?). {_FIX_TTY}",
            file=sys.stderr,
        )
        return ApproveResult(exit_code=_exitcodes.EXIT_HUMAN_CONFIRMATION_REQUIRED, sub_reason="non_tty_approval_blocked")

    # ---------- Step 2: identity resolution ----------
    resolved, by_source = resolve_approval_identity(args, gitconfig_email_lookup)
    if not resolved:
        print(
            f"error: phase approve refused: gitconfig user.email is unset. "
            f"{_FIX_GITCONFIG}",
            file=sys.stderr,
        )
        return ApproveResult(exit_code=6, sub_reason="gitconfig_email_unset")

    # ---------- Step 3: install-record presence ----------
    # No membership gate (ADR-0002: no attacker model). File existence is still
    # checked because downstream forensic code reads it.
    try:
        _load_install_record(install_record_path)
    except FileNotFoundError:
        print(
            f"error: phase approve refused: {install_record_path} not found. "
            f"Fix: re-run `harness init` to recreate it",
            file=sys.stderr,
        )
        return ApproveResult(exit_code=6, sub_reason="install_record_missing")

    # ---------- Steps 4–8: under primary lock ----------
    lock = _phase_lock.acquire_primary(scratch, timeout_s=10.0)
    try:
        # Load canonical state.
        state_path = scratch / _phase_txn.STATE_NAME
        if not state_path.exists():
            print(
                "error: phase approve refused: no state file present. "
                "Fix: run `harness phase set discuss` to bootstrap",
                file=sys.stderr,
            )
            return ApproveResult(
                exit_code=6,
                sub_reason="state_missing",
                resolved_email=resolved,
                by_source=by_source,
            )
        before_state = json.loads(state_path.read_text(encoding="utf-8"))

        # ---------- Step 5: execution_mode gate ----------
        execution_mode = before_state.get("execution_mode", "manual")
        if execution_mode != "manual":
            print(
                f"error: phase approve refused: cannot approve while "
                f"execution_mode={execution_mode!r} (agents do not "
                f"approve during autopilot). {_FIX_AUTOPILOT}",
                file=sys.stderr,
            )
            return ApproveResult(
                exit_code=8,
                sub_reason="approve_during_autopilot",
                resolved_email=resolved,
                by_source=by_source,
            )

        # ---------- Step 6: idempotency ----------
        if before_state.get("approved") is True:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "verb": "phase.approve",
                        "noop": "already_approved",
                        "approved_by": before_state.get("approved_by"),
                        "approved_at": before_state.get("approved_at"),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return ApproveResult(
                exit_code=0,
                sub_reason="already_approved",
                resolved_email=resolved,
                by_source=by_source,
            )

        # ---------- Step 7: Phase-validity guard ----------
        current_phase = before_state.get("phase", "unknown")
        APPROVABLE_PHASES = {"plan", "execute"}
        if current_phase not in APPROVABLE_PHASES:
            if current_phase == "done":
                msg = (
                    "error: phase approve refused: current phase is already 'done'. "
                    "Nothing to approve."
                )
                sub = "approve_in_done"
            else:
                msg = (
                    f"error: phase approve refused: cannot approve in phase={current_phase!r}. "
                    f"Use 'phase set <next>' to advance first, then 'phase approve'. "
                    f"Approvable phases: {sorted(APPROVABLE_PHASES)}."
                )
                sub = f"approve_in_{current_phase}"
            print(msg, file=sys.stderr)
            return ApproveResult(
                exit_code=_exitcodes.EXIT_WRONG_PHASE_FOR_VERB,
                sub_reason=sub,
            )

        # ---------- Step 8: Speed-bump prompt ----------
        prompt = (
            f"Approve current phase={current_phase}? "
            f"Type y to confirm, N to cancel [y/N]: "
        )
        if not _smoke_bypass_active:
            try:
                response = input(prompt)
            except (EOFError, KeyboardInterrupt):
                print(
                    "\nphase approve cancelled (no stamp written).",
                    file=sys.stderr,
                )
                return ApproveResult(exit_code=_exitcodes.EXIT_OK, sub_reason="user_cancelled")
            if response.strip() not in ("y", "Y"):
                print(
                    f"phase approve cancelled (response {response.strip()!r}, no stamp written).",
                    file=sys.stderr,
                )
                return ApproveResult(exit_code=_exitcodes.EXIT_OK, sub_reason="user_cancelled")
        # If smoke bypass is active, skip prompt — proceed directly to audit + stamp.

        # ---------- Step 9: state + audit mutation ----------
        approved_at = (
            getattr(args, "at", None) or _now_iso_z()
        )
        after_state = dict(before_state)
        after_state["approved"] = True
        after_state["approved_by"] = resolved
        after_state["approved_at"] = approved_at

        proof_class_value = "smoke_bypass" if _smoke_bypass_active else "soft_tty"
        audit_draft = {
            "verb": "phase.approve",
            "by": resolved,
            "by_source": by_source,
            "confirmation_kind": "soft_tty",
            "proof_class": proof_class_value,
            "tty": consumer_tty,
            "response": "smoke_bypass" if _smoke_bypass_active else "y",
            "args": {
                "approved_at": approved_at,
            },
        }
        txn_id = _phase_txn.commit_transaction(
            scratch,
            lock=lock,
            request=_phase_txn.TxnRequest(
                action="phase.approve",
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
                    "verb": "phase.approve",
                    "approved_by": resolved,
                    "approved_at": approved_at,
                    "by_source": by_source,
                    "txn_id": txn_id,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return ApproveResult(
            exit_code=0,
            sub_reason="approved",
            resolved_email=resolved,
            by_source=by_source,
        )
    finally:
        _phase_lock.release_primary(lock)


__all__ = ["ApproveResult", "run_approve", "default_gitconfig_email_lookup", "resolve_approval_identity"]
