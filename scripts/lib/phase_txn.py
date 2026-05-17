"""Crash-safe state+audit transaction protocol (design §3.8).

Spec: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`

Holding the state lock prevents concurrent writers; it does NOT make
two-file (state + audit) mutation crash-atomic. A power loss between
`os.replace(state)` and audit append, or between audit append and the
replace, can leave them divergent. This module provides the 5-step
protocol that closes that gap.

Slice S01-D.1 implements `commit_transaction` (steps 1-5). The 12-row
recovery matrix (`recover()`) lives in S01-D.2 and consumes the same
journal/tmp/audit artefacts written here.

Public surface
--------------
    TxnError                       -- base OSError subclass
    TxnLockMissingError(TxnError)  -- caller did not hold a live LockHandle
    TxnRequest                     -- dataclass(action, before_state,
                                                after_state, audit_entry_draft)
    JOURNAL_NAME, TMP_NAME         -- on-disk filenames inside `.scratch/`
    commit_transaction(scratch, *, lock, request, audit_path) -> txn_id

The function MUST be called with a live `LockHandle` from
`scripts.lib.phase_lock.acquire_primary`. All five steps run while that
lock is held; the caller releases it after the transaction returns.
Failure between steps 1-5 leaves the journal+tmp on disk so the recovery
matrix (S01-D.2) can resolve the partial state on next CLI start.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Mapping, Optional, Union

from . import audit as _audit
from . import durable_fs as _durable_fs
from . import phase_lock as _phase_lock


JOURNAL_NAME = "phase-state.json.journal"
TMP_NAME = "phase-state.json.tmp"
STATE_NAME = "phase-state.json"


class TxnError(OSError):
    """Base class for phase_txn failures. Callers map to exit 14
    (`crash_recovery_undecidable` family) unless a more specific
    subclass dictates otherwise."""


class TxnLockMissingError(TxnError):
    """Caller invoked commit_transaction without an acquired LockHandle."""


class BudgetExhaustedError(TxnError):
    """Raised by commit_transaction when a count-based budget is exhausted.

    Design decision (§3.4 + §5.3): exit code 9, sub_reason
    "budget_exhausted:<capability>".  Raised BEFORE any journal write so no
    partial artefacts are left on disk.

    Caller-contract: the commit is NOT attempted — the caller should either
    apply_budget_halt and commit the halted state (which will pass because
    execution_mode will be "manual" by then), or propagate exit 9.
    """

    def __init__(self, *, capability: str, remaining: int, message: str) -> None:
        super().__init__(message)
        self.exit_code: int = 9
        self.sub_reason: str = f"budget_exhausted:{capability}"
        self.capability: str = capability
        self.remaining: int = remaining


@dataclasses.dataclass
class TxnRequest:
    """Inputs to one commit. `before_state` may be `None` for a from-
    nothing insert; `after_state` is the canonical post-state dict.

    Audit drafts: most verbs emit ONE audit entry per transaction
    (`audit_entry_draft`). The S04+S05 review-fix (P1-3) extended this to
    accept a LIST of drafts (`audit_entry_drafts`) so a single atomic
    transaction can emit multiple correlated audit rows (e.g. a reopen
    that halts active autopilot emits `phase.autopilot.halt` followed by
    `phase.reopen` under one `txn_id`). The singular `audit_entry_draft`
    field is preserved as the backward-compat path; if both are set, the
    plural list wins. All drafts share the same `txn_id` and
    `before/after_sha256` decorations.
    """

    action: str
    before_state: Optional[Mapping[str, Any]]
    after_state: Mapping[str, Any]
    audit_entry_draft: Optional[Mapping[str, Any]] = None
    audit_entry_drafts: Optional[list] = None

    def resolved_drafts(self) -> list:
        """Return the canonical list of drafts to write. Plural wins over
        singular. Empty/missing -> empty list (callers should not invoke
        commit_transaction with zero audit rows, but the helper is safe)."""
        if self.audit_entry_drafts:
            return list(self.audit_entry_drafts)
        if self.audit_entry_draft is not None:
            return [self.audit_entry_draft]
        return []


def _canonical_bytes(state: Optional[Mapping[str, Any]]) -> bytes:
    """Canonical serialization for hashing AND for the state file body.

    Pinned to `json.dumps(..., sort_keys=True, indent=2,
    separators=(',', ': '))` with a trailing LF, matching the existing
    `state_migrate.serialize` shape (recovery matrix in S01-D.2 depends
    on byte-equality with prior writes). For audit-chain canonicalization
    (rfc8785) see §2.3 — that lives in S06.
    """
    if state is None:
        return b""
    text = json.dumps(dict(state), sort_keys=True, indent=2, separators=(",", ": "))
    return (text + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _new_txn_id() -> str:
    return secrets.token_hex(16)


def _check_lock(lock: Optional[_phase_lock.LockHandle], scratch: Path) -> None:
    if lock is None:
        raise TxnLockMissingError(
            "commit_transaction requires an acquired phase_lock.LockHandle"
        )
    if getattr(lock, "_released", False):
        raise TxnLockMissingError(
            "commit_transaction was passed an already-released LockHandle"
        )
    expected = scratch / _phase_lock.PRIMARY_NAME
    if Path(lock.path) != expected:
        raise TxnLockMissingError(
            f"LockHandle path {lock.path!r} does not match expected {expected!r}"
        )


def commit_transaction(
    scratch: Union[str, "os.PathLike[str]"],
    *,
    lock: Optional[_phase_lock.LockHandle],
    request: TxnRequest,
    audit_path: Union[str, "os.PathLike[str]"],
) -> str:
    """Execute steps 1-5 of design §3.8 in order. Returns the assigned `txn_id`.

    Budget check (§3.5 + §5.3 caller-contract):
    BEFORE step 1 (journal write), if request.before_state has
    execution_mode != "manual" AND cli_budgets_remaining is set, check the
    "file_mutation_ops" budget. If exhausted, raise BudgetExhaustedError
    (exit_code=9, sub_reason="budget_exhausted:file_mutation_ops") before any
    artefact is written.

    Caller-contract for decrement: callers that want the after_state to reflect
    the decremented budget MUST apply `with_budget_decrement(after_state)`
    themselves before building the TxnRequest.  See `with_budget_decrement`
    below.  This keeps commit_transaction free of budget-semantics coupling.

    Step 1: write journal {txn_id, action, before_sha256, after_sha256,
            audit_entry_draft, started_at_monotonic}; fsync(journal_fd);
            fsync_parent_dir(scratch).
    Step 2: write state.json.tmp with `after_state` canonical bytes;
            fsync(tmp_fd); fsync_parent_dir(scratch). (Round-5 BLOCK #4:
            the tmp's parent-dir fsync MUST precede step 3.)
    Step 3: append audit entry with `txn_id` and content sha256s to
            `audit.log` (audit_append fsyncs the fd internally).
    Step 4: os.replace(state.json.tmp, state.json) via replace_with_retry;
            fsync_parent_dir(scratch).
    Step 5: os.unlink(journal); fsync_parent_dir(scratch).
    """
    scratch = Path(scratch)
    audit_path = Path(audit_path)
    _check_lock(lock, scratch)

    # Budget pre-check (BEFORE journal write — no artefacts written yet).
    # Only applied when autopilot is active AND budgets are configured.
    #
    # EXEMPTED actions (P1-3 fix): internal-finalize commits that are
    # follow-up bookkeeping to a prior user-driven mutation. These must
    # complete to satisfy §1.1 invariants; exempting them prevents a
    # wedged PENDING sentinel when file_mutation_ops=0.
    _FINALIZE_EXEMPT_ACTIONS = frozenset({
        "phase.autopilot.start_hash_finalized",
    })
    if request.before_state is not None and request.action not in _FINALIZE_EXEMPT_ACTIONS:
        _exec_mode = request.before_state.get("execution_mode", "manual")
        if _exec_mode != "manual":
            _budgets = request.before_state.get("cli_budgets_remaining")
            if _budgets is not None:
                _remaining = _budgets.get("file_mutation_ops")
                if _remaining is not None and _remaining <= 0:
                    raise BudgetExhaustedError(
                        capability="file_mutation_ops",
                        remaining=0,
                        message=(
                            f"commit_transaction rejected: file_mutation_ops budget "
                            f"exhausted (remaining={_remaining}). "
                            "Apply apply_budget_halt and commit the halted state, "
                            "or let the caller exit 9. (§3.5 caller-contract)"
                        ),
                    )

    journal_path = scratch / JOURNAL_NAME
    tmp_path = scratch / TMP_NAME
    state_path = scratch / STATE_NAME

    before_bytes = _canonical_bytes(request.before_state)
    after_bytes = _canonical_bytes(request.after_state)
    before_sha = _sha256(before_bytes) if request.before_state is not None else ""
    after_sha = _sha256(after_bytes)
    txn_id = _new_txn_id()

    drafts = request.resolved_drafts()
    # Journal captures the FIRST draft only (the recovery oracle uses the
    # journal solely to learn the planned action; the audit log itself
    # records all drafts after step 3 completes).
    journal_first_draft = dict(drafts[0]) if drafts else {}

    # --- Step 1: journal -----------------------------------------------------
    journal_payload = {
        "txn_id": txn_id,
        "action": request.action,
        "before_sha256": before_sha,
        "after_sha256": after_sha,
        "audit_entry_draft": journal_first_draft,
        "started_at_monotonic": time.monotonic(),
    }
    journal_bytes = (
        json.dumps(journal_payload, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    fd = os.open(
        str(journal_path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        os.write(fd, journal_bytes)
        os.fsync(fd)
    finally:
        os.close(fd)
    _durable_fs.fsync_parent_dir(scratch)

    # --- Step 2: state.json.tmp ---------------------------------------------
    fd = os.open(
        str(tmp_path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        os.write(fd, after_bytes)
        os.fsync(fd)
    finally:
        os.close(fd)
    # Round-5 BLOCK #4: tmp directory entry MUST be durable before audit
    # references it (otherwise recovery oracle points at non-existent tmp).
    _durable_fs.fsync_parent_dir(scratch)

    # --- Step 3: audit append ----------------------------------------------
    # P1-3 extension: append ALL drafts inside step 3 so a multi-row
    # transaction (e.g. autopilot.halt + reopen) is atomic — a crash
    # between rows still leaves the journal+tmp on disk for the recovery
    # oracle, which keys off the journal's `txn_id` (== shared by all
    # rows). The §3.8 "one txn = one audit row" invariant is widened to
    # "one txn = one audit txn_id span"; every row carries the same
    # decorations.
    if not drafts:
        raise TxnError(
            "commit_transaction requires at least one audit_entry_draft "
            "(set request.audit_entry_draft or request.audit_entry_drafts)"
        )
    now_iso = _now_iso()
    for draft in drafts:
        entry = dict(draft)
        entry.setdefault("at", now_iso)
        entry["txn_id"] = txn_id
        entry["before_sha256"] = before_sha
        entry["after_sha256"] = after_sha
        _audit.audit_append(entry, audit_path=audit_path)
    # §12.5 #3 (Round-7 amendment): after `fsync(audit_fd)` inside
    # `audit_append`, the harness MUST `fsync_parent_dir(scratch)`
    # before proceeding to step 4. Without this the scratch dir entry
    # for tmp could still be undurable in a crash window even though
    # audit already references it.
    _durable_fs.fsync_parent_dir(scratch)

    # --- Step 4: atomic replace --------------------------------------------
    # `replace_with_retry` raises DurableFsError on Windows AV pin
    # exhaustion. The journal + tmp are left in place so the recovery
    # matrix (S01-D.2 rows 7 / 8a / 8b) can resolve on next start.
    _durable_fs.replace_with_retry(tmp_path, state_path)
    _durable_fs.fsync_parent_dir(scratch)
    # §12.5 #4: step 4 now requires `fsync_file_durable` of the renamed
    # state.json IN ADDITION to the directory fsync above. On APFS this
    # promotes the dir fsync to `F_FULLFSYNC` on the file's bytes; on
    # Windows it FlushFileBuffers the file via a re-open. Without this
    # the rename can be durable while the file's data pages still sit
    # in volatile cache, defeating the §3.8 crash guarantee.
    fd = os.open(str(state_path), os.O_RDONLY)
    try:
        _durable_fs.fsync_file_durable(fd, path=state_path)
    finally:
        os.close(fd)

    # --- Step 5: unlink journal --------------------------------------------
    os.unlink(journal_path)
    _durable_fs.fsync_parent_dir(scratch)

    return txn_id


# ---------------------------------------------------------------------------
# Recovery — 12-row matrix (design §3.8 + §12.5 #2)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class RecoveryResult:
    """Outcome of one `recover()` pass. The `row` field maps directly to
    the design §3.8 table (1-11) or §12.5 #2 row 12. `decision` is a
    short machine-readable string for logging / audit; `exit_code` is 0
    for the eight self-healing rows and 14 for the four fault rows."""

    row: int
    decision: str
    exit_code: int


def _state_sha_of_disk(state_path: Path) -> str:
    if not state_path.exists():
        return ""
    return _sha256(state_path.read_bytes())


def _file_sha(path: Path) -> str:
    return _sha256(path.read_bytes()) if path.exists() else ""


def _audit_tail_partial_write(audit_path: Path) -> bool:
    """Return True if the last non-empty line of `audit_path` fails
    JSON-parse — the §12.5 #2 row-12 predicate. The per-entry hash-chain
    check (S06) is intentionally NOT performed here; chain verification
    is a S06 responsibility and would mis-flag every entry written
    before S06 lands."""
    if not audit_path.exists():
        return False
    text = audit_path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    try:
        json.loads(lines[-1])
    except json.JSONDecodeError:
        return True
    return False


def _audit_tail_entry(audit_path: Path) -> Optional[dict]:
    """Return the last well-formed audit entry (full dict), or None."""
    if not audit_path.exists():
        return None
    text = audit_path.read_text(encoding="utf-8")
    for line in reversed(text.splitlines()):
        if not line.strip():
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def _audit_tail_txn_id(audit_path: Path) -> Optional[str]:
    """Return the `txn_id` field of the last well-formed audit entry, if any."""
    entry = _audit_tail_entry(audit_path)
    return entry.get("txn_id") if entry else None


class _MalformedJournal(Exception):
    """Sentinel raised when a present journal file fails JSON-parse.

    Surfaced by `recover()` as `row=13 decision=malformed_journal exit=14`
    — a real fault separate from a missing journal (J=0). Prior to the
    S01-D.2 review-fix the parse failure was silently swallowed.
    """


def _read_journal(scratch: Path) -> Optional[dict]:
    journal = scratch / JOURNAL_NAME
    if not journal.exists():
        return None
    try:
        return json.loads(journal.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _MalformedJournal(str(exc)) from exc


def recover(
    scratch: Union[str, "os.PathLike[str]"],
    *,
    audit_path: Union[str, "os.PathLike[str]"],
    lock: Optional[_phase_lock.LockHandle],
) -> RecoveryResult:
    """Dispatch one of the 12 design §3.8 matrix rows and execute its
    decision. Returns a `RecoveryResult`. The caller MUST hold the
    state lock (handed in via `lock`); recovery mutates artefacts.

    Row 12 (`audit_partial_write`, §12.5 #2) takes precedence — if the
    audit oracle itself is corrupt, no other matrix decision is safe.
    """
    scratch = Path(scratch)
    audit_path = Path(audit_path)
    _check_lock(lock, scratch)

    state_path = scratch / STATE_NAME
    journal_path = scratch / JOURNAL_NAME
    tmp_path = scratch / TMP_NAME

    # Row 12 — audit oracle untrustworthy.
    if _audit_tail_partial_write(audit_path):
        return RecoveryResult(row=12, decision="audit_partial_write", exit_code=14)

    # Out-of-band row 13 — journal file exists but fails JSON-parse.
    # Surfaced separately from J=0 so we don't fall into rows 1/2/3/4
    # and erroneously unlink tmp while a real journal sits on disk.
    try:
        journal = _read_journal(scratch)
    except _MalformedJournal:
        return RecoveryResult(row=13, decision="malformed_journal", exit_code=14)

    J = journal is not None
    T = tmp_path.exists()
    state_hash = _state_sha_of_disk(state_path)
    audit_entry = _audit_tail_entry(audit_path)
    audit_txn = audit_entry.get("txn_id") if audit_entry else None
    audit_after_sha = audit_entry.get("after_sha256") if audit_entry else None

    # J = 0 (rows 1-4)
    if not J:
        if not T:
            if audit_txn is None:
                return RecoveryResult(row=1, decision="quiescent", exit_code=0)
            # Row 3 review-fix: only accept when the on-disk state hash
            # matches the audit tail's `after_sha256`. Otherwise the
            # state file has drifted (corruption / out-of-band edit) and
            # we MUST exit 14 rather than silently report "accept".
            if audit_after_sha and state_hash == audit_after_sha:
                return RecoveryResult(
                    row=3, decision="post_finalize_no_tmp_accept", exit_code=0
                )
            return RecoveryResult(
                row=9, decision="undecidable_state_hash_mismatch_audit", exit_code=14
            )
        # T = 1, J = 0 — orphan tmp.
        if audit_txn is None:
            # No audit info to corroborate — historical "orphan_tmp" path.
            os.unlink(tmp_path)
            _durable_fs.fsync_parent_dir(scratch)
            return RecoveryResult(row=2, decision="orphan_tmp_unlinked", exit_code=0)
        # Row 4 review-fix: audit claims a transition; require state hash
        # match before treating the tmp as discardable. Tampered state
        # must NOT cause us to delete a potentially-recoverable tmp.
        if audit_after_sha and state_hash == audit_after_sha:
            os.unlink(tmp_path)
            _durable_fs.fsync_parent_dir(scratch)
            return RecoveryResult(
                row=4, decision="orphan_tmp_unlinked_post_finalize", exit_code=0
            )
        return RecoveryResult(
            row=9, decision="undecidable_state_hash_mismatch_audit", exit_code=14
        )

    # J = 1 — journal present (rows 5-11)
    assert journal is not None
    before_sha = journal.get("before_sha256", "")
    after_sha = journal.get("after_sha256", "")
    journal_txn = journal.get("txn_id", "")
    A = audit_txn is not None and audit_txn == journal_txn

    if not A:
        # Audit never observed this txn (step 3 didn't complete).
        if state_hash == before_sha:
            # Rollback: state untouched; drop journal (+ tmp if present).
            if T:
                os.unlink(tmp_path)
            os.unlink(journal_path)
            _durable_fs.fsync_parent_dir(scratch)
            row = 6 if T else 5
            decision = "rollback_journal_and_tmp" if T else "rollback_journal_only"
            return RecoveryResult(row=row, decision=decision, exit_code=0)
        # state != before AND audit never recorded -> corruption.
        row = 10 if T else 11
        return RecoveryResult(row=row, decision="corruption", exit_code=14)

    # A = 1 — audit confirms the txn.
    if state_hash == after_sha:
        # Finalize: state already updated, just remove leftovers.
        if T:
            os.unlink(tmp_path)
        os.unlink(journal_path)
        _durable_fs.fsync_parent_dir(scratch)
        return RecoveryResult(row=8, decision="finalize", exit_code=0)

    if state_hash == before_sha and T and _file_sha(tmp_path) == after_sha:
        # Roll forward: replace state with tmp, drop journal.
        _durable_fs.replace_with_retry(tmp_path, state_path)
        _durable_fs.fsync_parent_dir(scratch)
        fd = os.open(str(state_path), os.O_RDONLY)
        try:
            _durable_fs.fsync_file_durable(fd, path=state_path)
        finally:
            os.close(fd)
        os.unlink(journal_path)
        _durable_fs.fsync_parent_dir(scratch)
        return RecoveryResult(row=7, decision="roll_forward", exit_code=0)

    # Audit confirms but state matches neither before nor after.
    return RecoveryResult(row=9, decision="undecidable", exit_code=14)


def _now_iso() -> str:
    import datetime

    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# with_budget_decrement — caller-contract helper
# ---------------------------------------------------------------------------


def with_budget_decrement(
    after_state: Mapping[str, Any],
    *,
    capability: str = "file_mutation_ops",
) -> dict:
    """Caller-contract helper: return a copy of `after_state` with the named
    capability decremented by 1 (clamped to 0).

    Design decision (§3.5 caller-contract): commit_transaction does NOT
    auto-decrement budgets to keep it free of budget semantics.  Callers that
    want the persisted state to reflect consumption MUST apply this helper to
    `after_state` before building the TxnRequest.  Opt-in, not mandatory —
    callers that don't decrement will hit the budget check on the next commit
    (the check uses `before_state.cli_budgets_remaining`).

    No-op when:
      - after_state.execution_mode == "manual" (no autopilot → no budget)
      - after_state.cli_budgets_remaining is None (no budgets configured)
      - capability not in cli_budgets_remaining (capability not tracked)
      - capability == "wall_seconds" (wall_seconds is time-checked, not counted)
    """
    # Lazy import to avoid circular at module load time.
    from . import cli_budgets as _cli_budgets

    exec_mode = after_state.get("execution_mode", "manual")
    if exec_mode == "manual":
        return dict(after_state)

    budgets = after_state.get("cli_budgets_remaining")
    if budgets is None:
        return dict(after_state)

    return _cli_budgets.decrement(dict(after_state), capability=capability)  # type: ignore[arg-type]


__all__ = [
    "TxnError",
    "TxnLockMissingError",
    "BudgetExhaustedError",
    "TxnRequest",
    "RecoveryResult",
    "JOURNAL_NAME",
    "TMP_NAME",
    "STATE_NAME",
    "commit_transaction",
    "with_budget_decrement",
    "recover",
]
