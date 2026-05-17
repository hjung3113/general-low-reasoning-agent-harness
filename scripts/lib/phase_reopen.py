"""`phase reopen` — TTY-only rewind to plan/discuss boundary (design §3.2).

Order of operations (any failure → typed `ReopenResult` with non-zero
`exit_code`; the CLI dispatcher maps to `sys.exit`):

  1. TTY gate (§3.2). `stdin_isatty=False` → exit 6 `non_tty_reopen_blocked`.
  2. `--reason` mandatory; missing/empty → exit 6 `reopen_missing_reason`.
  3. `--to` validation; not in {plan, discuss} → exit 6 `reopen_invalid_target`.
  4. Identity resolution (§3.1 step 2) — gitconfig auto-read; `--by` override.
     Empty → exit 6 `gitconfig_email_unset`.
  5. install-record approvers membership (§3.1 step 3 + §6.1).
  6. Anchor preflight + state-trust preflight (§12.1 + §2.6) under the
     primary lock. Default `repo_root=None` + `skip_anchor_preflight=False`
     fails closed (exit 6 `anchor_preflight_unwired`).
  6b. Source-phase validation (S04+S05 review-fix P2-1): `--to plan`
      permitted only from execute/done; `--to discuss` permitted from any
      phase (design §3.2 line 250).
  7. State mutation:
       - phase → target
       - approved=False, approved_at=None, approved_by=None
       - verification → draft_verification, allowed_paths → draft_allowed_paths
       - execute_attempt_started_at=None
       - If `execution_mode != manual`: populate `last_halt` per §5.3, push
         the prior `last_halt` (if any) onto `last_halt_history[-5:]`, clear
         all `autopilot_*` fields, set `execution_mode = "manual"`.
       - Else (manual mode) + target=="plan" + stale `last_halt`: MOVE the
         stale diary onto `last_halt_history[-5:]` and set `last_halt=None`
         (§5.3 line 946 + S04+S05 review-fix P1-2). For target=="discuss"
         the stale diary is RETAINED but its `acknowledged_at` is stamped
         (the user has seen and explicitly handled the halt via reopen).
       - Whichever halt diary survives in `after_state.last_halt` MUST
         have `acknowledged_at` set (§1.1 line 67 + P1-1).
  8. Audit entries: `verb=phase.reopen` always; when reopen halts active
     autopilot a `verb=phase.autopilot.halt` row is also emitted inside
     the same atomic transaction (§3.2 line 253 + S04+S05 review-fix P1-3).

Spec: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`
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
_HALT_HISTORY_CAP = 5


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
# Fix-line messages (verb-specific; shared anchor/state-trust messages
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
_FIX_APPROVER_MEMBERSHIP = (
    "Fix: only emails listed in `.harness/install-record.json approvers[]` "
    "may reopen; re-run `harness install`"
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


# ---------------------------------------------------------------------------
# Backward-compat re-export — pre-refactor tests import this name.
# ---------------------------------------------------------------------------


def default_gitconfig_email_lookup() -> str:
    """Thin wrapper over `phase_preflight.default_gitconfig_email_lookup`."""
    return _phase_preflight.default_gitconfig_email_lookup()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rotate_last_halt_history(
    state: dict,
    new_entry: Optional[Mapping],
    *,
    cap: int = _HALT_HISTORY_CAP,
) -> list:
    """Return a new `last_halt_history` list with `new_entry` appended
    (if non-empty) and tail-capped at `cap`. Pure: does not mutate
    `state`. Shared between the autopilot-halt branch and the
    manual `--to plan` clearing branch (P2-6)."""
    history = list(state.get("last_halt_history") or [])
    if new_entry:
        history.append(dict(new_entry))
        history = history[-cap:]
    return history


def _ack_diary(diary: Optional[Mapping], *, now_iso: str) -> Optional[dict]:
    """Return a copy of `diary` with `acknowledged_at` set to `now_iso`
    if `diary` is non-empty; else None. P1-1: `phase reopen` is the verb
    that user-initiates the acknowledgement (spec §1.1 line 67)."""
    if not diary:
        return None
    d = dict(diary)
    d["acknowledged_at"] = now_iso
    return d


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
    skip_anchor_preflight: bool = False,
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
    # env_vars not consulted for identity resolution (mirror approve).
    del env_vars

    # Step 1: TTY gate
    if not stdin_isatty:
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

    # Step 5: install-record approvers membership
    try:
        install_record = _phase_preflight.load_install_record(install_record_path)
    except FileNotFoundError:
        print(
            f"error: phase reopen refused: {install_record_path} not found. "
            f"Fix: re-run `harness install`",
            file=sys.stderr,
        )
        return ReopenResult(exit_code=6, sub_reason="install_record_missing")

    approvers = _phase_preflight.approvers_emails(install_record)
    if resolved.lower() not in approvers:
        print(
            f"error: phase reopen refused: {resolved!r} is not in "
            f"install-record approvers[]. {_FIX_APPROVER_MEMBERSHIP}",
            file=sys.stderr,
        )
        return ReopenResult(
            exit_code=6,
            sub_reason="approver_not_in_install_record",
            resolved_email=resolved,
            by_source=by_source,
        )

    # Steps 6+7+8 under primary lock.
    lock = _phase_lock.acquire_primary(scratch, timeout_s=10.0)
    try:
        # Anchor preflight.
        try:
            anchor_verified = _phase_preflight.run_anchor_preflight(
                skip_anchor_preflight=skip_anchor_preflight,
                repo_root=repo_root,
            )
        except _phase_preflight.AnchorPreflightError as exc:
            print(
                f"error: phase reopen refused: {exc.message}. {exc.fix_line}",
                file=sys.stderr,
            )
            return ReopenResult(
                exit_code=6,
                sub_reason=exc.sub_reason,
                resolved_email=resolved,
                by_source=by_source,
            )

        # State-trust preflight.
        try:
            _phase_preflight.run_state_trust_preflight(
                scratch=scratch,
                audit_path=audit_path,
                lock=lock,
                anchor_verified=anchor_verified,
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

        # P1-2: wall-seconds budget check AFTER state load, BEFORE any mutation.
        from . import cli_budgets as _cli_budgets
        _halt_exit = _cli_budgets.wall_seconds_check_and_maybe_halt(
            before_state=before_state,
            scratch_root=scratch,
            audit_path=audit_path,
            lock_handle=lock,
        )
        if _halt_exit is not None:
            return ReopenResult(
                exit_code=_halt_exit,
                sub_reason="budget_exhausted:wall_seconds",
                resolved_email=resolved,
                by_source=by_source,
                from_phase=from_phase,
            )

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

        # Active autopilot halt (§3.5.2 + §5.3) AND stale-diary handling
        # (P1-2 + P1-1).
        halted_run_id: Optional[str] = None
        emit_halt_audit = False
        halt_audit_payload: Optional[dict] = None
        prev_mode = before_state.get("execution_mode", "manual")
        if prev_mode != "manual":
            # ---- A. active autopilot halt branch ----
            halted_run_id = before_state.get("autopilot_run_id")
            new_diary = {
                "run_id": halted_run_id,
                "mode": before_state.get("autopilot_mode"),
                "phase_slug": before_state.get("autopilot_phase_slug"),
                "last_successful_transition": None,
                "halt_reason": "reopen",
                "halt_at_iso": now_iso,
                "suggested_next_command": f"harness phase set {target}",
                # Round-7 BLOCK fix (Adapter C-19) — P1-4: `harness phase
                # set {target}` is non-TTY-only (it routes through the
                # standard transition validator, not an approval gate),
                # so the suggested next command does NOT require human
                # interaction. This flag is False here; verbs that point
                # at `phase approve` / `phase reopen` would set True.
                "suggested_next_command_requires_human": False,
                # P1-1: reopen IS the user-initiated ack; stamp it now so
                # §3.6 (execute→done) does not refuse on `acknowledged_at
                # is None`. Mirrors `phase autopilot start` and
                # `halt-diary clear`.
                "acknowledged_at": now_iso,
            }
            # Push the PRIOR diary onto history (cap-5 helper, P2-6).
            after_state["last_halt_history"] = _rotate_last_halt_history(
                before_state, before_state.get("last_halt")
            )
            after_state["last_halt"] = new_diary
            # Clear all autopilot_* fields (§3.5.2).
            after_state["execution_mode"] = "manual"
            after_state["autopilot_run_id"] = None
            after_state["autopilot_mode"] = None
            after_state["autopilot_phase_slug"] = None
            after_state["autopilot_start_entry_hash"] = None
            after_state["autopilot_allow_network"] = False
            after_state["cli_budgets_remaining"] = None

            # Emit `phase.autopilot.halt` audit row inside the same txn
            # (P1-3 + §3.2 line 253). The halt row carries the diary
            # fields at top-level so reviewers can correlate without
            # opening the overflow archive.
            emit_halt_audit = True
            halt_audit_payload = {
                "verb": "phase.autopilot.halt",
                "by": resolved,
                "by_source": by_source,
                "confirmation_kind": "human_cli",
                "run_id": halted_run_id,
                "mode": before_state.get("autopilot_mode"),
                "phase_slug": before_state.get("autopilot_phase_slug"),
                "halt_reason": "reopen",
                "halt_at_iso": now_iso,
                # NOTE: the forensic fields (run_id, mode, phase_slug,
                # halt_reason, halt_at_iso) are ALL promoted to the top
                # level so they survive audit_append's 512-byte truncation
                # of the `args` carrier. A redundant `args` sub-dict is
                # intentionally omitted — it would push the truncated line
                # over AUDIT_MAX_LINE_BYTES and trigger the minimal fallback
                # that strips txn_id (see P2-4 sentinel + §3.2 line 253
                # atomicity contract). The `commit_transaction` loop adds
                # txn_id, before/after_sha256 at step 3; with no `args`
                # the total entry is ~489 bytes, safely under 512.
            }
        else:
            # ---- B. manual mode: handle stale `last_halt` per §5.3 ----
            prior_diary = before_state.get("last_halt")
            if prior_diary:
                if target == "plan":
                    # §5.3 line 946: --to plan CLEARS last_halt because the
                    # user has explicitly handled it. The cleared diary
                    # moves onto last_halt_history (cap-5), ack-stamped
                    # so forensic readers can see when it was handled.
                    acked = _ack_diary(prior_diary, now_iso=now_iso)
                    after_state["last_halt_history"] = _rotate_last_halt_history(
                        before_state, acked
                    )
                    after_state["last_halt"] = None
                else:
                    # target == "discuss": leave diary populated but
                    # stamp acknowledged_at so the §3.6 (execute→done)
                    # gate does not refuse on a later run.
                    after_state["last_halt"] = _ack_diary(
                        prior_diary, now_iso=now_iso
                    )
            # else: no diary to handle; leave last_halt / history alone.

        # P1-1: apply file_mutation_ops decrement (caller-contract per §3.5).
        after_state = _phase_txn.with_budget_decrement(after_state)

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
        # P1-3: when halting active autopilot, emit halt row FIRST then
        # reopen row (logical order: halt the prior thing, then the verb
        # that caused it). Both share the same txn_id.
        if emit_halt_audit:
            assert halt_audit_payload is not None
            drafts = [halt_audit_payload, reopen_draft]
        else:
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
