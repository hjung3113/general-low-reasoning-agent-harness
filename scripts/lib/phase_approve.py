"""`phase approve` — interactive speed-bump gate (spec 2026-05-19-phase-approve-speed-bump-design.md).

Stamps the *current* phase as approved. Does NOT advance to the next phase;
use ``phase set <next>`` to advance after stamping.

Order of operations (any failure → typed ``ApproveResult`` with non-zero
``exit_code``; the CLI dispatcher maps to ``sys.exit``):

  1. TTY gate. ``stdin_isatty=False`` → exit 17 ``non_tty_approval_blocked``.
     HARNESS_BY_TRUST / HARNESS_HUMAN are NEVER consulted on this path.
  2. Phase guard. Current phase ``done`` → refuses with a clear error.
  3. Identity resolution. ``--by`` if provided, else ``git config user.email``.
     Empty → exit 6 ``gitconfig_email_unset``.
  4. install-record approvers membership check.
  5. Anchor preflight + state-trust preflight. Anchor verified BEFORE state
     read; forged state → exit 10.
  6. ``state.execution_mode != "manual"`` → exit 8 ``approve_during_autopilot``.
  7. Idempotency check: ``state.approved == True`` → exit 0 ``already_approved``.
  8. Prompt ``[y/N]`` on TTY. Non-``y`` answer → exit 1 (user declined).
  9. State + audit mutation via ``phase_txn.commit_transaction``.
     Audit row records ``proof_class: soft_tty``.

Spec: ``docs/superpowers/specs/2026-05-19-phase-approve-speed-bump-design.md``
ADR : ``docs/adr/2026-05-17-approver-provenance-and-execution-mode.md``
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

from . import audit_anchor as _audit_anchor  # kept for tests that monkeypatch
from . import exitcodes as _exitcodes
from . import phase_lock as _phase_lock
from . import phase_preflight as _phase_preflight
from . import phase_txn as _phase_txn
from . import state_trust as _state_trust  # kept for tests that monkeypatch


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
_FIX_GITCONFIG_MUTATED = (
    "Fix: pass `--by <email>` explicitly OR re-run `harness install` "
    "to record the updated gitconfig email (§12.6 gitconfig fingerprint)"
)
_FIX_OVERRIDE_REASON_MISSING = (
    "Fix: pass `--reason \"<text>\"` together with `--override-identity` "
    "(the reason is mandatory and audited per ADR-001)"
)
_FIX_OVERRIDE_REASON_CHARS = (
    "Fix: --override-reason must not contain NUL / newlines / control "
    "chars / Unicode bidi controls (audit-line framing hazard)"
)
_FIX_OVERRIDE_REASON_LEN = (
    "Fix: --override-reason is capped at 1024 chars (design §3.1.1)"
)
_FIX_OVERRIDE_IDENTITY_CHARS = (
    "Fix: --override-identity must not contain NUL / newlines / "
    "control chars / Unicode bidi controls"
)


# ---------------------------------------------------------------------------
# TTY kind label helper (§3 Fix 3 audit redaction)
# ---------------------------------------------------------------------------

def _tty_kind(tty_path: str) -> str:
    """Return the kind label for a TTY path string.

    Labels: ``win-synthetic`` | ``posix-fallback`` | ``posix-real``.
    """
    if tty_path.startswith("win:"):
        return "win-synthetic"
    if tty_path.startswith("posix:"):
        return "posix-fallback"
    return "posix-real"


# ---------------------------------------------------------------------------
# Sanitization (§3.1.1 final paragraph + §12.6)
# ---------------------------------------------------------------------------


_SANITIZE_MAX_LEN = 1024
# C0 controls (0x00-0x1f), DEL (0x7f). We accept ordinary space (0x20+).
_C0_CONTROLS = frozenset(chr(c) for c in range(0x00, 0x20))
# Unicode bidi/isolate formatting controls — visual-spoof hazard
# (Trojan-Source class). LRM/RLM/LRE/RLE/PDF/LRO/RLO/LRI/RLI/FSI/PDI.
_BIDI_CONTROLS = frozenset([
    "‎", "‏",  # LRM, RLM
    "‪", "‫", "‬", "‭", "‮",  # LRE/RLE/PDF/LRO/RLO
    "⁦", "⁧", "⁨", "⁩",  # LRI/RLI/FSI/PDI
])
# S04+S05 review-fix P2-2: parity with §12.6 Trojan-Source intent. Add
# zero-width joiners (ZWJ/ZWNJ), Arabic Letter Mark (ALM), and Unicode
# line/paragraph separators (LS/PS). All five are visual-spoof or
# audit-line-framing hazards that the original set missed.
_EXTRA_INVISIBLES = frozenset([
    "‌",  # ZERO WIDTH NON-JOINER (ZWNJ)
    "‍",  # ZERO WIDTH JOINER (ZWJ)
    "؜",  # ARABIC LETTER MARK (ALM)
    " ",  # LINE SEPARATOR (LS)
    " ",  # PARAGRAPH SEPARATOR (PS)
])
# P3-P2-1 (cycle-1 review fix): extend forbidden chars to cover homograph /
# confusable vectors not blocked by the existing sets:
#   - Variation selectors (VS1-VS16, U+FE00-U+FE0F) -- silently alter glyph
#     without changing the base character; audit log records the combined form.
#   - Variation selectors supplement (VS17-VS256, U+E0100-U+E01EF).
#   - Unicode tag characters (U+E0020-U+E007E) -- invisible control plane tags
#     used in Trojan-Source-class payloads.
#   - Unpaired UTF-16 surrogates (U+D800-U+DFFF) -- Python str can hold these
#     via surrogate escape; reject explicitly to avoid encode/decode hazards.
# Math Alphanumeric and compatibility forms are handled by NFKC normalization
# (applied in _sanitize_string before the forbidden-char scan), which folds
# them to their ASCII equivalents so the audit log records the canonical form.
_VARIATION_SELECTORS = frozenset(chr(c) for c in range(0xFE00, 0xFE10))
_VARIATION_SELECTORS_SUPPLEMENT = frozenset(chr(c) for c in range(0xE0100, 0xE01F0))
_TAG_CHARS = frozenset(chr(c) for c in range(0xE0020, 0xE007F))
_SURROGATES = frozenset(chr(c) for c in range(0xD800, 0xE000))
_FORBIDDEN_CHARS = (
    _C0_CONTROLS | {"\x7f"} | _BIDI_CONTROLS | _EXTRA_INVISIBLES
    | _VARIATION_SELECTORS | _VARIATION_SELECTORS_SUPPLEMENT
    | _TAG_CHARS | _SURROGATES
)


def _sanitize_string(s: str) -> str:
    """Apply NFKC normalization and return the normalized string.

    NFKC folds compatibility forms (Mathematical Alphanumeric Symbols,
    full-width Latin, etc.) to their ASCII equivalents before the
    forbidden-char scan.  This means e.g. '\U0001d41a\U0000646d\U0000696e' (math-bold
    "adm") -> "adm" in the audit log -- the normalized canonical form is
    stored, removing the homograph spoof while preserving semantic content.

    The caller passes the normalized form to _has_forbidden_chars and to
    the audit entry.  Spec: §3.1.1 + cycle-1 review P3-P2-1.
    Length cap (1024 chars) applies POST-NFKC normalization; characters that
    expand under NFKC (e.g. '½' -> '1⁄2') can cause near-cap input to balloon past it.
    """
    import unicodedata
    return unicodedata.normalize("NFKC", s)


def _has_forbidden_chars(s: str) -> bool:
    return any(c in _FORBIDDEN_CHARS for c in s)


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


def _approvers_emails(install_record: Mapping) -> list[str]:
    return _phase_preflight.approvers_emails(install_record)


def _now_iso_z() -> str:
    return _phase_preflight.now_iso_z()


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
    skip_state_trust_preflight: bool = False,
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

    # nonce_dir intentionally unused — phase.approve is now a workflow
    # speed bump (spec 2026-05-19). Release path uses ~/.harness/approval-nonces/
    # via its own handler, not this one.
    del nonce_dir

    # ---------- Step 1: TTY gate ----------
    if not stdin_isatty:
        print(
            f"error: phase approve refused: non-TTY caller "
            f"(agent-spawned subprocess?). {_FIX_TTY}",
            file=sys.stderr,
        )
        return ApproveResult(exit_code=_exitcodes.EXIT_HUMAN_CONFIRMATION_REQUIRED, sub_reason="non_tty_approval_blocked")

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

    # ---------- Step 2a: gitconfig fingerprint check (§12.6) ----------
    # Only runs when --by is NOT passed (gitconfig_auto path). If the
    # install-record recorded git_user_email_at_install_sha256 and the
    # current gitconfig email no longer matches that fingerprint, exit 6
    # so a rotated/shared-workstation gitconfig cannot silently approve.
    # When by_source == "explicit_by_flag" the user has explicitly asserted
    # their identity; the fingerprint check is skipped (--by is opt-in bypass).
    if by_source == "gitconfig_auto":
        try:
            _ir_for_fingerprint = _load_install_record(install_record_path)
            stored_fingerprint = _ir_for_fingerprint.get("git_user_email_at_install_sha256")
            if stored_fingerprint is not None:
                import hashlib as _hashlib
                current_fingerprint = _hashlib.sha256(
                    resolved.lower().encode("utf-8")
                ).hexdigest()
                if current_fingerprint != stored_fingerprint:
                    print(
                        f"error: phase approve refused: current gitconfig user.email "
                        f"sha256 does not match install-record fingerprint "
                        f"(gitconfig_mutated_post_install). {_FIX_GITCONFIG_MUTATED}",
                        file=sys.stderr,
                    )
                    return ApproveResult(
                        exit_code=6,
                        sub_reason="gitconfig_mutated_post_install",
                        resolved_email=resolved,
                        by_source=by_source,
                    )
        except FileNotFoundError:
            # install_record missing — caught at step 3; skip fingerprint here
            pass

    # ---------- Step 2b: override-identity handling (§3.1 step 4 + ADR-001) ----------
    # Design decision (under-specified clarification): §3.1 step 4 says
    # `--override-identity` "bypasses step 3". We read this as "the
    # AUDIT-DISPLAYED identity differs from the resolved one", NOT "the
    # gate is removed". The resolved email (gitconfig or --by) MUST
    # still be in approvers — otherwise the override flag is just an
    # env-spoof rename. The override changes the audit `by` field
    # (forensic display) and flips `by_source=override_identity` so
    # reviewers can grep for unusual provenance. The `override_reason`
    # is mandatory and audited.
    override_identity_raw = getattr(args, "override_identity", None)
    override_identity: Optional[str] = None
    override_reason_clean: Optional[str] = None
    if override_identity_raw not in (None, False, ""):
        if not isinstance(override_identity_raw, str):
            override_identity_raw = str(override_identity_raw)
        # Reason mandatory.
        raw_reason = getattr(args, "override_reason", None)
        if raw_reason is None or not str(raw_reason).strip():
            print(
                f"error: phase approve refused: --override-identity requires "
                f"--reason. {_FIX_OVERRIDE_REASON_MISSING}",
                file=sys.stderr,
            )
            return ApproveResult(
                exit_code=6,
                sub_reason="override_reason_missing",
                resolved_email=resolved,
                by_source="override_identity",
            )
        # P3-P2-1: NFKC-normalize before length/charset checks.
        # Folds Math Alphanumeric and other compatibility forms to ASCII.
        reason_str = _sanitize_string(str(raw_reason))
        # Length cap.
        if len(reason_str) > _SANITIZE_MAX_LEN:
            print(
                f"error: phase approve refused: --override-reason exceeds "
                f"{_SANITIZE_MAX_LEN} chars. {_FIX_OVERRIDE_REASON_LEN}",
                file=sys.stderr,
            )
            return ApproveResult(
                exit_code=6,
                sub_reason="override_reason_too_long",
                resolved_email=resolved,
                by_source="override_identity",
            )
        # Charset.
        if _has_forbidden_chars(reason_str):
            print(
                f"error: phase approve refused: --override-reason contains "
                f"forbidden chars. {_FIX_OVERRIDE_REASON_CHARS}",
                file=sys.stderr,
            )
            return ApproveResult(
                exit_code=6,
                sub_reason="override_reason_invalid_chars",
                resolved_email=resolved,
                by_source="override_identity",
            )
        # Identity itself sanitized too (same charset).
        override_identity_raw = _sanitize_string(override_identity_raw)
        if _has_forbidden_chars(override_identity_raw) or \
                len(override_identity_raw) > _SANITIZE_MAX_LEN:
            print(
                f"error: phase approve refused: --override-identity contains "
                f"forbidden chars. {_FIX_OVERRIDE_IDENTITY_CHARS}",
                file=sys.stderr,
            )
            return ApproveResult(
                exit_code=6,
                sub_reason="override_identity_invalid_chars",
                resolved_email=resolved,
                by_source="override_identity",
            )
        override_identity = override_identity_raw.strip()
        override_reason_clean = reason_str.strip()
        by_source = "override_identity"

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
    # Note: prior code had a bypass `and not getattr(args, "override_identity", False)`.
    # S05 removes that bypass — the resolved identity (gitconfig or --by)
    # MUST still be a listed approver even when `--override-identity` is
    # set. The override changes only the audit-displayed identity; the
    # GATE remains "humans listed in install-record approve". See the
    # design decision comment in the override branch above.
    if resolved.lower() not in approvers:
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
        # skip_state_trust_preflight=True is a separate test-only bypass for
        # tests that do not wire up a real audit chain (e.g. speed-bump prompt
        # tests seeded via seed_scratch without an audit entry).
        # skip_anchor_preflight=True does NOT imply skipping state_trust;
        # tests such as _trigger_exit14_crash_recovery pass skip_anchor_preflight
        # while still relying on state_trust to fire exit 14.
        if not skip_state_trust_preflight:
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

        # P1-2: wall-seconds budget check AFTER state load, BEFORE any mutation.
        from . import cli_budgets as _cli_budgets
        _halt_exit = _cli_budgets.wall_seconds_check_and_maybe_halt(
            before_state=before_state,
            scratch_root=scratch,
            audit_path=audit_path,
            lock_handle=lock,
        )
        if _halt_exit is not None:
            return ApproveResult(
                exit_code=_halt_exit,
                sub_reason="budget_exhausted:wall_seconds",
                resolved_email=resolved,
                by_source=by_source,
            )

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

        # ---------- Step 7: Speed-bump prompt ----------
        # Per spec 2026-05-19-phase-approve-speed-bump-design.md §4.1, prompt
        # names the *current* phase being stamped (not the next phase) to avoid
        # users misreading approve as auto-advance.
        current_phase = before_state.get("phase", "unknown")

        # Phase-validity guard: approving in 'done' is meaningless — there is
        # no further state to stamp. All other non-terminal phases are valid
        # under the speed-bump model (user is the gate, not the harness).
        if current_phase == "done":
            print(
                "error: phase approve refused: current phase is already 'done'. "
                "Nothing to approve.",
                file=sys.stderr,
            )
            return ApproveResult(
                exit_code=_exitcodes.EXIT_WRONG_PHASE_FOR_VERB,
                sub_reason="approve_in_done",
            )

        prompt = (
            f"Approve current phase={current_phase}? "
            f"Type y to confirm, N to cancel [y/N]: "
        )
        try:
            response = input(prompt)
        except (EOFError, KeyboardInterrupt):
            return ApproveResult(exit_code=_exitcodes.EXIT_OK, sub_reason="user_cancelled")
        if response.strip() not in ("y", "Y"):
            return ApproveResult(exit_code=_exitcodes.EXIT_OK, sub_reason="user_cancelled")

        # ---------- Step 8: state + audit mutation ----------
        approved_at = (
            getattr(args, "at", None) or _now_iso_z()
        )
        after_state = dict(before_state)
        after_state["approved"] = True
        # State `approved_by` records the AUDIT-DISPLAYED identity
        # (override when set; resolved otherwise) so `harness status`
        # surfaces the same value the audit log carries.
        after_state["approved_by"] = override_identity or resolved
        after_state["approved_at"] = approved_at

        # P1-1: apply file_mutation_ops decrement (caller-contract per §3.5).
        after_state = _phase_txn.with_budget_decrement(after_state)

        # Audit entry: proof_class=soft_tty records that the human confirmed
        # via interactive [y/N] prompt on a TTY (speed-bump design §4.1).
        # S05: when override_identity is set, the audit `by` field is the
        # override (forensic-displayed identity); `by_source` is
        # "override_identity"; `confirmation_kind` is also
        # "override_identity" so reviewers can detect this branch from
        # either field (truncation-resilient cross-check).
        audit_by = override_identity or resolved
        if override_identity is not None:
            confirmation_kind = "override_identity"
        else:
            confirmation_kind = "soft_tty"
        audit_extra = {
            "proof_class": "soft_tty",
            "tty": consumer_tty,
            "response": "y",
        }
        audit_draft = {
            "verb": "phase.approve",
            "by": audit_by,
            "by_source": by_source,
            "confirmation_kind": confirmation_kind,
            **audit_extra,
            "args": {
                "approved_at": approved_at,
            },
        }
        if override_identity is not None:
            audit_draft["args"]["override_reason"] = override_reason_clean
            audit_draft["args"]["override_identity"] = override_identity
            audit_draft["args"]["resolved_email"] = resolved
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


__all__ = ["ApproveResult", "run_approve", "default_gitconfig_email_lookup"]
