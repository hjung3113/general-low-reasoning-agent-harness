"""`phase reopen` — TTY-only rewind to plan/discuss boundary (design §3.2).

Order of operations (any failure → typed `ReopenResult` with non-zero
`exit_code`; the CLI dispatcher maps to `sys.exit`):

  1. TTY gate (§3.2). `stdin_isatty=False` → exit 6 `non_tty_reopen_blocked`.
  2. `--reason` mandatory; missing/empty → exit 6 `reopen_missing_reason`.
  3. `--to` validation; not in {plan, discuss} → exit 6 `reopen_invalid_target`.
  4. Identity resolution (§3.1 step 2) — gitconfig auto-read; `--by` override.
     Empty → exit 6 `gitconfig_email_unset`.
  5. install-record approvers membership (§3.1 step 3 + §6.1).
  6. State-trust preflight (§2.6) under the primary lock.
  6b. Source-phase validation: `--to plan` permitted only from execute/done;
      `--to discuss` permitted from any phase (design §3.2 line 250).
  7. State mutation:
       - phase → target
       - approved=False, approved_at=None, approved_by=None
       - verification → draft_verification, allowed_paths → draft_allowed_paths
       - execute_attempt_started_at=None
  8. Audit entry: `verb=phase.reopen`.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Callable, Mapping, Optional

from . import phase_lock as _phase_lock
from . import phase_preflight as _phase_preflight
from . import phase_txn as _phase_txn
# Re-exported only so legacy tests that `monkeypatch.setattr(phase_reopen,
# "_state_trust", ...)` keep working. Runtime calls go through
# `phase_preflight.run_state_trust_preflight`, which imports
# `state_trust` itself; the monkeypatch flows because both module
# references point at the same module object.
from . import state_trust as _state_trust  # noqa: F401


_VALID_TARGETS = frozenset({"plan", "discuss"})
_PLAN_VALID_SOURCES = frozenset({"execute", "done"})


@dataclasses.dataclass(frozen=True)
class ReopenResult:
    exit_code: int
    sub_reason: str
    resolved_email: Optional[str] = None
    by_source: Optional[str] = None
    from_phase: Optional[str] = None
    to_phase: Optional[str] = None
    halted_autopilot_run_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Fix-line messages (verb-specific; shared state-trust messages
# come from `phase_preflight`).
# ---------------------------------------------------------------------------


_FIX_TTY = (
    "Fix: run `harness phase reopen` from a real terminal "
    "(not via a piped or agent-spawned subprocess)"
)
_FIX_GITCONFIG = (
    "Fix: run `git config user.email <your-email>` "
    "or pass `harness phase reopen --by <your-email>`"
)
_FIX_REASON = (
    "Fix: pass `--reason \"<text>\"` describing why you are rewinding "
    "(the reason is audited)"
)
_FIX_TARGET = (
    "Fix: pass `--to plan` or `--to discuss` "
    "(only these two targets are valid per design §3.2)"
)
_FIX_PLAN_SOURCE = (
    "Fix: `--to plan` is permitted only from execute/done; "
    "use `--to discuss` to rewind further (design §3.2 line 250)"
)
_FIX_BACKWARD_RESET = (
    "Fix: backward moves (to a phase earlier than the current approved phase) "
    "require `--reset-approval` to explicitly acknowledge that the prior "
    "approval will be revoked"
)


# ---------------------------------------------------------------------------
# Backward-compat re-export — pre-refactor tests import this name.
# ---------------------------------------------------------------------------


def default_gitconfig_email_lookup() -> str:
    """Thin wrapper over `phase_preflight.default_gitconfig_email_lookup`."""
    return _phase_preflight.default_gitconfig_email_lookup()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_reopen(
    args,
    *,
    scratch: Path,
    harness_dir: Path,
    audit_path: Path,
    install_record_path: Path,
    stdin_isatty: bool,
    gitconfig_email_lookup: Optional[Callable[[], str]] = None,
    env_vars: Optional[Mapping[str, str]] = None,
    repo_root: Optional[Path] = None,
) -> ReopenResult:
    # Design decision (deferred — S04+S05 review-fix P2-5): `phase reopen`
    # does NOT currently require a human-presence nonce (spec §3.2 leaves
    # it open). The adversarial reviewer raised a path-of-least-resistance
    # social-engineering vector — an agent could trick a human into a
    # quick `phase reopen` and then approve in the rewound state. This
    # is escalated as a design-doc clarification item; if §3.2 lands a
    # mandatory nonce, the consume call goes here (mirroring §3.1.1 of
    # `phase_approve.run_approve`). Tracked outside this commit.
    scratch = Path(scratch)
    harness_dir = Path(harness_dir)
    audit_path = Path(audit_path)
    install_record_path = Path(install_record_path)
    if env_vars is None:
        env_vars = os.environ

    # ---------- Smoke-test bypass (T12 — mirror phase_approve.py BLOCKER A-4) ----------
    # ONLY active when BOTH env vars are set to "1". Production callers never
    # set HARNESS_SMOKE_TEST, so this branch is unreachable in production.
    # When active: TTY gate is skipped; ALL other checks (identity, approver
    # allowlist, state_trust, audit) still run.
    # Audit row records proof_class=smoke_bypass so forensics can distinguish
    # smoke runs from real human reopens.
    if (
        env_vars.get("HARNESS_SMOKE_BYPASS_SPEED_BUMP") == "1"
        and env_vars.get("HARNESS_SMOKE_TEST") == "1"
    ):
        _smoke_bypass_active = True
    else:
        _smoke_bypass_active = False

    # env_vars not consulted for identity resolution (mirror approve).
    del env_vars

    # Step 1: TTY gate
    if not _smoke_bypass_active and not stdin_isatty:
        print(
            f"error: phase reopen refused: non-TTY caller. {_FIX_TTY}",
            file=sys.stderr,
        )
        return ReopenResult(exit_code=6, sub_reason="non_tty_reopen_blocked")

    # Step 2: reason mandatory
    reason = getattr(args, "reason", None)
    if reason is None or not str(reason).strip():
        print(
            f"error: phase reopen refused: --reason is mandatory. {_FIX_REASON}",
            file=sys.stderr,
        )
        return ReopenResult(exit_code=6, sub_reason="reopen_missing_reason")
    reason = str(reason).strip()

    # Step 3: target validation
    target = getattr(args, "to", None)
    if target not in _VALID_TARGETS:
        print(
            f"error: phase reopen refused: invalid --to {target!r}. {_FIX_TARGET}",
            file=sys.stderr,
        )
        return ReopenResult(exit_code=6, sub_reason="reopen_invalid_target")

    # Step 4: identity resolution
    by_flag = getattr(args, "by", None)
    if by_flag:
        resolved = by_flag.strip()
        by_source = "explicit_by_flag"
    else:
        lookup = gitconfig_email_lookup or _phase_preflight.default_gitconfig_email_lookup
        resolved = lookup().strip()
        by_source = "gitconfig_auto"
    if not resolved:
        print(
            f"error: phase reopen refused: gitconfig user.email is unset. "
            f"{_FIX_GITCONFIG}",
            file=sys.stderr,
        )
        return ReopenResult(exit_code=6, sub_reason="gitconfig_email_unset")

    # Step 5: install-record presence (membership check removed v0.9.13).
    try:
        _phase_preflight.load_install_record(install_record_path)
    except FileNotFoundError:
        print(
            f"error: phase reopen refused: {install_record_path} not found. "
            f"Fix: re-run `harness init` to bootstrap the install record",
            file=sys.stderr,
        )
        return ReopenResult(exit_code=6, sub_reason="install_record_missing")

    # Steps 6+7+8 under primary lock.
    lock = _phase_lock.acquire_primary(scratch, timeout_s=10.0)
    try:
        # State-trust preflight.
        try:
            _phase_preflight.run_state_trust_preflight(
                scratch=scratch,
                audit_path=audit_path,
                lock=lock,
            )
        except _phase_preflight.StateTrustPreflightError as exc:
            print(
                f"error: phase reopen refused: {exc.message}. {exc.fix_line}",
                file=sys.stderr,
            )
            return ReopenResult(
                exit_code=exc.exit_code,
                sub_reason=exc.sub_reason,
                resolved_email=resolved,
                by_source=by_source,
            )

        state_path = scratch / _phase_txn.STATE_NAME
        if not state_path.exists():
            print(
                "error: phase reopen refused: no state file present. "
                "Fix: run `harness phase set discuss` to bootstrap",
                file=sys.stderr,
            )
            return ReopenResult(
                exit_code=6,
                sub_reason="state_missing",
                resolved_email=resolved,
                by_source=by_source,
            )
        before_state = json.loads(state_path.read_text(encoding="utf-8"))
        from_phase = before_state.get("phase")

        # Step 6b: source-phase validation (P2-1).
        if target == "plan" and from_phase not in _PLAN_VALID_SOURCES:
            print(
                f"error: phase reopen refused: --to plan from phase "
                f"{from_phase!r} not permitted. {_FIX_PLAN_SOURCE}",
                file=sys.stderr,
            )
            return ReopenResult(
                exit_code=6,
                sub_reason="reopen_invalid_source_for_target",
                resolved_email=resolved,
                by_source=by_source,
                from_phase=from_phase,
                to_phase=target,
            )

        # Step 6c: backward-move guard (T12 / NEW-7).
        # A "backward move" is any reopen where the current state carries
        # approved=True.  The caller must pass `--reset-approval` to
        # explicitly acknowledge that the prior approval is being revoked.
        # This is a workflow speed-bump only (not a security gate); the TTY
        # gate / identity / approver-membership checks are sufficient for
        # security. Smoke-bypass does NOT skip this guard.
        _is_backward = before_state.get("approved") is True
        _reset_approval_flag = getattr(args, "reset_approval", False)
        if _is_backward and not _reset_approval_flag:
            print(
                f"error: phase reopen refused: current state is approved=True "
                f"(phase={from_phase!r}). {_FIX_BACKWARD_RESET}",
                file=sys.stderr,
            )
            return ReopenResult(
                exit_code=6,
                sub_reason="reopen_backward_requires_reset_approval",
                resolved_email=resolved,
                by_source=by_source,
                from_phase=from_phase,
                to_phase=target,
            )

        now_iso = _phase_preflight.now_iso_z()

        # ---------- Step 7: state mutation ----------
        after_state = dict(before_state)
        after_state["phase"] = target

        # Reset approval triplet (§3.2).
        after_state["approved"] = False
        after_state["approved_by"] = None
        after_state["approved_at"] = None

        # Field move (§3.2 Round-3 BLOCK refinement).
        prior_verification = before_state.get("verification")
        prior_allowed = before_state.get("allowed_paths")
        if prior_verification not in (None, []):
            after_state["draft_verification"] = prior_verification
        after_state["verification"] = None
        if prior_allowed not in (None, []):
            after_state["draft_allowed_paths"] = prior_allowed
        after_state["allowed_paths"] = None

        # Reset attempt clock (§1.1 / conductor brief).
        after_state["execute_attempt_started_at"] = None

        halted_run_id: Optional[str] = None

        # ---------- Step 8: audit entries ----------
        # Top-level fields survive `audit_append`'s 1024-byte truncation
        # (which replaces `args` with `{"truncated": true}` and archives
        # the full record to `.harness/audit.overflow/`). The forensic
        # fields therefore live at the top level so reviewers can
        # correlate without paging the overflow file.
        #
        # S06-chain RESOLVED: AUDIT_MAX_LINE_BYTES raised from 512→1024 to
        # accommodate ~140 bytes of per-entry chain fields (schema_version,
        # seq, seq_global, previous_entry_hash, entry_hash). The sentinel
        # test was updated to assert ≤1024 bytes (option (a) — raise limit).
        # All forensic top-level fields are preserved within the new budget.
        reopen_draft = {
            "verb": "phase.reopen",
            "by": resolved,
            "by_source": by_source,
            "confirmation_kind": "human_cli",
            "from_phase": from_phase,
            "to_phase": target,
            "halted_autopilot_run_id": halted_run_id,
            "args": {
                "from_phase": from_phase,
                "to_phase": target,
                "reason": reason,
                "preserved_as_draft": True,
                "halted_autopilot_run_id": halted_run_id,
            },
        }
        # T12: when smoke bypass is active, record proof_class so forensics
        # can distinguish smoke runs from real human reopens (mirrors
        # phase_approve.py convention — reuses proof_class=smoke_bypass).
        if _smoke_bypass_active:
            reopen_draft["proof_class"] = "smoke_bypass"
        drafts = [reopen_draft]

        txn_id = _phase_txn.commit_transaction(
            scratch,
            lock=lock,
            request=_phase_txn.TxnRequest(
                action="phase.reopen",
                before_state=before_state,
                after_state=after_state,
                audit_entry_drafts=drafts,
            ),
            audit_path=audit_path,
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "verb": "phase.reopen",
                    "from_phase": from_phase,
                    "to_phase": target,
                    "by": resolved,
                    "by_source": by_source,
                    "halted_autopilot_run_id": halted_run_id,
                    "txn_id": txn_id,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return ReopenResult(
            exit_code=0,
            sub_reason="reopened",
            resolved_email=resolved,
            by_source=by_source,
            from_phase=from_phase,
            to_phase=target,
            halted_autopilot_run_id=halted_run_id,
        )
    finally:
        _phase_lock.release_primary(lock)


__all__ = ["ReopenResult", "run_reopen", "default_gitconfig_email_lookup"]
