"""`phase approve` — human-only gate (design §3.1, §3.1.1).

Order of operations (any failure → typed `ApproveResult` with non-zero
`exit_code`; the CLI dispatcher maps to `sys.exit`):

  1. TTY gate (§3.1 step 1). `stdin_isatty=False` → exit 6
     `non_tty_approval_blocked`. HARNESS_BY_TRUST / HARNESS_HUMAN env are
     NEVER consulted on this path (Round-4 BLOCK fix #2).
  2. Identity resolution (§3.1 step 2). `--by` if provided, else
     `git config user.email`. Empty → exit 6 `gitconfig_email_unset`.
  3. install-record approvers membership (§3.1 step 3 + §6.1). Email
     must appear in `.harness/install-record.json approvers[].email`.
  4. Anchor preflight + state-trust preflight (§12.1 + §2.6).
     Anchor verified BEFORE state read; state preflight refuses on
     forged state with exit 10.
  5. `state.execution_mode != "manual"` → exit 8
     `approve_during_autopilot`.
  6. Idempotency check: `state.approved == True` → exit 0
     `already_approved`, no nonce burn, no state mutation, no audit.
  7. Human-presence proof (§3.1.1) — consume newest valid nonce for
     `audience="phase.approve"`. Failures: `human_proof_missing` /
     `human_proof_nonce_expired` / `human_proof_nonce_same_tty` /
     `human_proof_nonce_audience_mismatch` — all exit 6.
  8. State + audit mutation via `phase_txn.commit_transaction`.

The CLI dispatcher in `scripts/harness.py` translates `ApproveResult`
into an exit. The pure-function shape is so tests can drive the helper
without spinning a real PTY or real `~/.harness`.

Spec: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`
ADR : `docs/adr/2026-05-17-approver-provenance-and-execution-mode.md`
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

from . import approval_nonce as _approval_nonce
from . import audit_anchor as _audit_anchor
from . import phase_lock as _phase_lock
from . import phase_txn as _phase_txn
from . import state_trust as _state_trust


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
    by_source: Optional[str] = None  # "gitconfig_auto" | "explicit_by_flag" | "override_identity"
    nonce_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Fix-line messages (§3.9 — every error MUST carry a remediation)
# ---------------------------------------------------------------------------


_FIX_TTY = (
    "Fix: run `harness phase approve` from a real terminal "
    "(not via a piped or agent-spawned subprocess)"
)
_FIX_GITCONFIG = (
    "Fix: run `git config user.email <your-email>` "
    "or pass `harness phase approve --by <your-email>`"
)
_FIX_APPROVER_MEMBERSHIP = (
    "Fix: only emails listed in `.harness/install-record.json approvers[]` "
    "may approve; re-run `harness install` or pass "
    "`--override-identity --reason <text>`"
)
_FIX_NONCE_MISSING = (
    "Fix: in a separate terminal run `harness approve-nonce mint`, "
    "then re-run `harness phase approve`"
)
_FIX_NONCE_EXPIRED = (
    "Fix: nonces expire after 120s; re-mint via `harness approve-nonce mint`"
)
_FIX_NONCE_SAME_TTY = (
    "Fix: mint the nonce from a different terminal "
    "(same-TTY mint+consume is rejected as agent-impersonation defense)"
)
_FIX_AUTOPILOT = (
    "Fix: run `harness phase autopilot stop --reason \"<text>\"` "
    "first, then re-approve"
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
# Helpers — git config lookup + identity resolution
# ---------------------------------------------------------------------------


def default_gitconfig_email_lookup() -> str:
    """Run `git config user.email`. Empty string on any failure."""
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
    nonce_dir: Path,
    stdin_isatty: bool,
    consumer_tty: str,
    gitconfig_email_lookup: Optional[Callable[[], str]] = None,
    env_vars: Optional[Mapping[str, str]] = None,
    repo_root: Optional[Path] = None,
    skip_anchor_preflight: bool = False,
) -> ApproveResult:
    """Execute the §3.1 + §3.1.1 sequence. Returns a structured result.

    Dependency injection points (all default to real OS/git when not
    provided) make the function unit-testable without TTY allocation or
    real ~/.harness contents.

    Note on `env_vars`: passed in explicitly so tests can verify that
    `HARNESS_BY_TRUST` / `HARNESS_HUMAN` do NOT influence the path —
    this verb has zero env-trust per Round-4 BLOCK fix #2.
    """
    scratch = Path(scratch)
    harness_dir = Path(harness_dir)
    audit_path = Path(audit_path)
    install_record_path = Path(install_record_path)
    nonce_dir = Path(nonce_dir)
    if env_vars is None:
        env_vars = os.environ
    # env_vars is intentionally never consulted for identity resolution
    # below. The test `test_env_vars_byte_identical_to_empty_env` proves
    # the byte-identical-output property by injecting `HARNESS_BY_TRUST`
    # and comparing against an empty-env baseline.
    del env_vars

    # ---------- Step 1: TTY gate ----------
    if not stdin_isatty:
        print(
            f"error: phase approve refused: non-TTY caller "
            f"(agent-spawned subprocess?). {_FIX_TTY}",
            file=sys.stderr,
        )
        return ApproveResult(exit_code=6, sub_reason="non_tty_approval_blocked")

    # ---------- Step 2: identity resolution ----------
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
            f"error: phase approve refused: gitconfig user.email is unset. "
            f"{_FIX_GITCONFIG}",
            file=sys.stderr,
        )
        return ApproveResult(exit_code=6, sub_reason="gitconfig_email_unset")

    # ---------- Step 3: install-record approvers membership ----------
    try:
        install_record = _load_install_record(install_record_path)
    except FileNotFoundError:
        print(
            f"error: phase approve refused: {install_record_path} not found. "
            f"Fix: re-run `harness install`",
            file=sys.stderr,
        )
        return ApproveResult(exit_code=6, sub_reason="install_record_missing")

    approvers = _approvers_emails(install_record)
    if resolved.lower() not in approvers and not getattr(
        args, "override_identity", False
    ):
        print(
            f"error: phase approve refused: {resolved!r} is not in "
            f"install-record approvers[]. {_FIX_APPROVER_MEMBERSHIP}",
            file=sys.stderr,
        )
        return ApproveResult(
            exit_code=6,
            sub_reason="approver_not_in_install_record",
            resolved_email=resolved,
            by_source=by_source,
        )

    # ---------- Steps 4+5+6+7+8: under primary lock ----------
    lock = _phase_lock.acquire_primary(scratch, timeout_s=10.0)
    try:
        # Anchor preflight (§12.1). The §12.1 trust chain REQUIRES that
        # `state_trust.preflight` be invoked with `anchor_verified=True`
        # only AFTER the out-of-repo audit-tip anchor has been verified.
        # Three paths:
        #   1. skip_anchor_preflight=True — controlled test paths that
        #      stand up the in-memory environment without minting a real
        #      ~/.harness anchor. Accepted; anchor_verified=True passed
        #      downstream by deliberate test contract.
        #   2. repo_root provided + anchor verifies → anchor_verified=True.
        #   3. repo_root provided + anchor missing/mismatched →
        #      AnchorMissingError / AnchorMismatchError → exit 6 with the
        #      §3.9 Fix line. Distinct sub_reasons for forensic taxonomy.
        # The default repo_root=None + skip_anchor_preflight=False case
        # FAILS CLOSED (review fix P1-1 — prior code silently set
        # anchor_verified=True, bypassing the §12.1 chain entirely).
        if skip_anchor_preflight:
            anchor_verified = True
        elif repo_root is None:
            print(
                f"error: phase approve refused: anchor preflight cannot "
                f"run without repo_root. {_FIX_ANCHOR_UNVERIFIABLE}",
                file=sys.stderr,
            )
            return ApproveResult(
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
                    f"error: phase approve refused: audit-tip anchor not "
                    f"found ({exc}). {_FIX_ANCHOR_MISSING}",
                    file=sys.stderr,
                )
                return ApproveResult(
                    exit_code=6,
                    sub_reason="anchor_missing",
                    resolved_email=resolved,
                    by_source=by_source,
                )
            except _audit_anchor.AnchorMismatchError as exc:
                sub = exc.sub_reason or "anchor_verification_failed"
                print(
                    f"error: phase approve refused: audit-tip anchor "
                    f"verification failed ({sub}: {exc}). "
                    f"{_FIX_ANCHOR_MISMATCH}",
                    file=sys.stderr,
                )
                return ApproveResult(
                    exit_code=6,
                    sub_reason=sub,
                    resolved_email=resolved,
                    by_source=by_source,
                )
            except _audit_anchor.AnchorError as exc:
                # Schema/unreadable/etc. — surface verbatim.
                sub = exc.sub_reason or "anchor_error"
                print(
                    f"error: phase approve refused: audit-tip anchor "
                    f"unreadable ({sub}: {exc}). {_FIX_ANCHOR_MISMATCH}",
                    file=sys.stderr,
                )
                return ApproveResult(
                    exit_code=6,
                    sub_reason=sub,
                    resolved_email=resolved,
                    by_source=by_source,
                )

        # State-trust preflight (§2.6). Refuses forged state with exit 10.
        try:
            _state_trust.preflight(
                scratch,
                audit_path=audit_path,
                lock=lock,
                anchor_verified=anchor_verified,
            )
        except _state_trust.StateAuditMismatchError as exc:
            print(
                f"error: phase approve refused: state trust preflight "
                f"failed: {exc}. {_FIX_STATE_TRUST}",
                file=sys.stderr,
            )
            return ApproveResult(
                exit_code=10,
                sub_reason="state_audit_tip_mismatch",
                resolved_email=resolved,
                by_source=by_source,
            )
        except _state_trust.StateEmptyError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return ApproveResult(
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
            return ApproveResult(
                exit_code=5,
                sub_reason="state_unparseable",
                resolved_email=resolved,
                by_source=by_source,
            )

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

        # ---------- Step 7: human-presence proof ----------
        consume = _approval_nonce.consume_newest_valid(
            nonce_dir=nonce_dir,
            audience="phase.approve",
            consumer_tty=consumer_tty,
        )
        if consume.outcome != "consumed":
            mapping = {
                "missing": ("human_proof_missing", _FIX_NONCE_MISSING),
                "expired": ("human_proof_nonce_expired", _FIX_NONCE_EXPIRED),
                "same_tty": ("human_proof_nonce_same_tty", _FIX_NONCE_SAME_TTY),
                "audience_mismatch": (
                    "human_proof_nonce_audience_mismatch",
                    _FIX_NONCE_MISSING,
                ),
            }
            sub, fix = mapping.get(
                consume.outcome, ("human_proof_missing", _FIX_NONCE_MISSING)
            )
            print(
                f"error: phase approve refused: human-presence proof "
                f"failed ({consume.outcome}). {fix}",
                file=sys.stderr,
            )
            return ApproveResult(
                exit_code=6,
                sub_reason=sub,
                resolved_email=resolved,
                by_source=by_source,
            )
        nonce = consume.nonce

        # ---------- Step 8: state + audit mutation ----------
        approved_at = (
            getattr(args, "at", None) or _now_iso_z()
        )
        after_state = dict(before_state)
        after_state["approved"] = True
        after_state["approved_by"] = resolved
        after_state["approved_at"] = approved_at

        # Audit entry shape:
        #   * Top-level (survives audit_append truncation): verb, by,
        #     by_source, confirmation_kind, nonce_id, nonce_minter_tty,
        #     nonce_consumer_tty, at, before/after_sha256, txn_id.
        #   * `args` carries the verbose timestamps. If the encoded line
        #     exceeds AUDIT_MAX_LINE_BYTES (512), `audit.audit_append`
        #     archives the full record to `.harness/audit.overflow/`
        #     and replaces `args` with `{"truncated": true}` — the
        #     top-level provenance fields are preserved, so state_trust
        #     and forensic readers still see the proof shape.
        #
        # TODO(S06-verifier): audit-line truncation layout — the
        # adversarial reviewer of S02 noted that the current shape
        # promotes provenance to top-level but `args` truncation still
        # silently elides the `nonce_minted_at` / `nonce_consumed_at`
        # timestamps. The S06 verifier surface MUST honor the overflow
        # file as part of the chain; design §3.1.1 + reviewer P2.
        #
        # TODO(later-slice): clock-backwards `approval_epoch` counter.
        # If wall-clock moves backward between mints, two distinct
        # nonces could end up with identical `minted_at` values; a
        # monotonic per-install counter would defend against the
        # corner case. Reviewer P2-3; deferred until clock-skew bites.
        #
        # Design decision (under-specified): §3.1 step 6 says
        # `confirmation_kind="human_cli"` for manual mode; §3.1.1 says
        # `confirmation_kind="human_nonce"` for nonce path. We use
        # `"human_nonce"` because §3.1.1 is the more specific (Round-5
        # BLOCK #2) rule and the value carries strictly more proof
        # information than "human_cli" (it implies TTY + manual + nonce).
        nonce_consumed_at = _now_iso_z()
        nonce_minted_at_iso = (
            datetime.fromtimestamp(nonce.minted_at, tz=timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        audit_draft = {
            "verb": "phase.approve",
            "by": resolved,
            "by_source": by_source,
            "confirmation_kind": "human_nonce",
            "nonce_id": nonce.nonce_id,
            "nonce_minter_tty": nonce.minter_tty,
            "nonce_consumer_tty": consumer_tty,
            "args": {
                "nonce_minted_at": nonce_minted_at_iso,
                "nonce_consumed_at": nonce_consumed_at,
                "approved_at": approved_at,
            },
        }
        # NOTE: `commit_transaction` reads `_phase_txn` via module-level
        # symbol; tests that monkeypatch `phase_txn.commit_transaction`
        # also monkeypatch `phase_approve._phase_txn` to the live module
        # so the spy is honored.
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
                    "nonce_id": nonce.nonce_id,
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
            nonce_id=nonce.nonce_id,
        )
    finally:
        _phase_lock.release_primary(lock)


__all__ = ["ApproveResult", "run_approve", "default_gitconfig_email_lookup"]
