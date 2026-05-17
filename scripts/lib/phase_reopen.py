"""`phase reopen` — TTY-only rewind to plan/discuss boundary (design §3.2).

Order of operations (any failure → typed `ReopenResult` with non-zero
`exit_code`; the CLI dispatcher maps to `sys.exit`):

  1. TTY gate (§3.2). `stdin_isatty=False` → exit 6 `non_tty_reopen_blocked`.
  2. `--reason` mandatory; missing/empty → exit 6 `reopen_missing_reason`.
  3. `--to` validation; not in {plan, discuss} → exit 6 `reopen_invalid_target`.
  4. Identity resolution (§3.1 step 2) — gitconfig auto-read; `--by` override.
     Empty → exit 6 `gitconfig_email_unset`.
  5. install-record approvers membership (§3.1 step 3 + §6.1) unless
     `--override-identity` (rejected here as out-of-scope for S04; the
     override extension lives in S05's `run_approve`. `phase reopen`
     accepts only listed approvers for v0.7).
  6. Anchor preflight + state-trust preflight (§12.1 + §2.6) under the
     primary lock. Default `repo_root=None` + `skip_anchor_preflight=False`
     fails closed (exit 6 `anchor_preflight_unwired`).
  7. State mutation:
       - phase → target
       - approved=False, approved_at=None, approved_by=None
       - verification → draft_verification, allowed_paths → draft_allowed_paths
       - execute_attempt_started_at=None
       - If `execution_mode != manual`: populate `last_halt` per §5.3, push
         the prior `last_halt` (if any) onto `last_halt_history[-5:]`, clear
         all `autopilot_*` fields, set `execution_mode = "manual"`.
  8. Audit entry: `verb=phase.reopen` with `from_phase`, `to_phase`,
     `reason`, `preserved_as_draft=true`, `halted_autopilot_run_id`
     (if any). Top-level provenance fields mirror `phase_approve`.

Spec: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

from . import audit_anchor as _audit_anchor
from . import phase_lock as _phase_lock
from . import phase_txn as _phase_txn
from . import state_trust as _state_trust


_VALID_TARGETS = frozenset({"plan", "discuss"})


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
# Fix-line messages
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
_FIX_STATE_TRUST = (
    "Fix: run `harness verify --audit`; "
    "if intentional, restore via `git checkout -- .scratch/phase-state.json` "
    "or re-run `harness install`"
)
_FIX_ANCHOR_MISSING = (
    "Fix: run `harness anchor repair` from a TTY to mint the "
    "out-of-repo audit-tip anchor (design §12.1)"
)
_FIX_ANCHOR_MISMATCH = (
    "Fix: investigate audit/install-record tampering, then "
    "`harness anchor repair` from a TTY (design §12.1)"
)
_FIX_ANCHOR_UNVERIFIABLE = (
    "Fix: caller must pass `repo_root=` so the §12.1 trust chain can "
    "verify the out-of-repo audit-tip anchor before reading state; "
    "or pass `skip_anchor_preflight=True` ONLY from controlled test paths"
)


# ---------------------------------------------------------------------------
# Helpers (mirror phase_approve)
# ---------------------------------------------------------------------------


def default_gitconfig_email_lookup() -> str:
    try:
        r = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _load_install_record(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _approvers_emails(install_record: Mapping) -> list[str]:
    out = []
    for entry in install_record.get("approvers", []) or []:
        if isinstance(entry, dict) and entry.get("email"):
            out.append(str(entry["email"]).strip().lower())
    return out


def _now_iso_z() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


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
        lookup = gitconfig_email_lookup or default_gitconfig_email_lookup
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
        install_record = _load_install_record(install_record_path)
    except FileNotFoundError:
        print(
            f"error: phase reopen refused: {install_record_path} not found. "
            f"Fix: re-run `harness install`",
            file=sys.stderr,
        )
        return ReopenResult(exit_code=6, sub_reason="install_record_missing")

    approvers = _approvers_emails(install_record)
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
        if skip_anchor_preflight:
            anchor_verified = True
        elif repo_root is None:
            print(
                f"error: phase reopen refused: anchor preflight cannot "
                f"run without repo_root. {_FIX_ANCHOR_UNVERIFIABLE}",
                file=sys.stderr,
            )
            return ReopenResult(
                exit_code=6,
                sub_reason="anchor_preflight_unwired",
                resolved_email=resolved,
                by_source=by_source,
            )
        else:
            try:
                _audit_anchor.verify_existing_anchor_for_repo(repo_root)
                anchor_verified = True
            except _audit_anchor.AnchorMissingError as exc:
                print(
                    f"error: phase reopen refused: audit-tip anchor not "
                    f"found ({exc}). {_FIX_ANCHOR_MISSING}",
                    file=sys.stderr,
                )
                return ReopenResult(
                    exit_code=6,
                    sub_reason="anchor_missing",
                    resolved_email=resolved,
                    by_source=by_source,
                )
            except _audit_anchor.AnchorMismatchError as exc:
                sub = exc.sub_reason or "anchor_verification_failed"
                print(
                    f"error: phase reopen refused: audit-tip anchor "
                    f"verification failed ({sub}: {exc}). "
                    f"{_FIX_ANCHOR_MISMATCH}",
                    file=sys.stderr,
                )
                return ReopenResult(
                    exit_code=6,
                    sub_reason=sub,
                    resolved_email=resolved,
                    by_source=by_source,
                )
            except _audit_anchor.AnchorError as exc:
                sub = exc.sub_reason or "anchor_error"
                print(
                    f"error: phase reopen refused: audit-tip anchor "
                    f"unreadable ({sub}: {exc}). {_FIX_ANCHOR_MISMATCH}",
                    file=sys.stderr,
                )
                return ReopenResult(
                    exit_code=6,
                    sub_reason=sub,
                    resolved_email=resolved,
                    by_source=by_source,
                )

        # State-trust preflight.
        try:
            _state_trust.preflight(
                scratch,
                audit_path=audit_path,
                lock=lock,
                anchor_verified=anchor_verified,
            )
        except _state_trust.StateAuditMismatchError as exc:
            print(
                f"error: phase reopen refused: state trust preflight "
                f"failed: {exc}. {_FIX_STATE_TRUST}",
                file=sys.stderr,
            )
            return ReopenResult(
                exit_code=10,
                sub_reason="state_audit_tip_mismatch",
                resolved_email=resolved,
                by_source=by_source,
            )
        except _state_trust.StateEmptyError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return ReopenResult(
                exit_code=14,
                sub_reason="state_empty_crash_artefact",
                resolved_email=resolved,
                by_source=by_source,
            )
        except (
            _state_trust.StateBomError,
            _state_trust.StateCrlfError,
            _state_trust.StateMalformedJsonError,
        ) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return ReopenResult(
                exit_code=5,
                sub_reason="state_unparseable",
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

        # Active autopilot halt (§3.5.2 + §5.3).
        halted_run_id: Optional[str] = None
        prev_mode = before_state.get("execution_mode", "manual")
        if prev_mode != "manual":
            halted_run_id = before_state.get("autopilot_run_id")
            now_iso = _now_iso_z()
            new_diary = {
                "run_id": halted_run_id,
                "mode": before_state.get("autopilot_mode"),
                "phase_slug": before_state.get("autopilot_phase_slug"),
                "last_successful_transition": None,
                "halt_reason": "reopen",
                "halt_at_iso": now_iso,
                "suggested_next_command": (
                    f"harness phase set {target}"
                ),
                "verb": "phase.reopen",
            }
            # Push previous last_halt onto history (cap last 5 per §5.3).
            prior_diary = before_state.get("last_halt")
            history = list(before_state.get("last_halt_history") or [])
            if prior_diary:
                history.append(prior_diary)
                history = history[-5:]
            after_state["last_halt"] = new_diary
            after_state["last_halt_history"] = history
            # Clear all autopilot_* fields (§3.5.2).
            after_state["execution_mode"] = "manual"
            after_state["autopilot_run_id"] = None
            after_state["autopilot_mode"] = None
            after_state["autopilot_phase_slug"] = None
            after_state["autopilot_start_entry_hash"] = None
            after_state["autopilot_allow_network"] = False
            after_state["cli_budgets_remaining"] = None
        # If already manual, do NOT touch last_halt / last_halt_history
        # (avoid clobbering user-facing diary on a no-op halt).

        # ---------- Step 8: audit entry ----------
        # Top-level fields survive `audit_append`'s 512-byte truncation
        # (which replaces `args` with `{"truncated": true}` and archives
        # the full record to `.harness/audit.overflow/`). The forensic
        # halt-diary fields therefore live at the top level so reviewers
        # can correlate the halted run id without paging the overflow file.
        audit_draft = {
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
        txn_id = _phase_txn.commit_transaction(
            scratch,
            lock=lock,
            request=_phase_txn.TxnRequest(
                action="phase.reopen",
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
