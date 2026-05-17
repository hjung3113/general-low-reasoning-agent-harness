"""`halt-diary clear` admin verb logic (design §5.3 + §12.7).

Order of operations for `run_clear` (any failure → `ClearResult` with non-zero
`exit_code`; the CLI dispatcher maps to `sys.exit`):

  1. TTY gate (§12.7). `stdin_is_tty=False` → exit 6 `non_tty_halt_diary_clear_blocked`.
  2. Anchor preflight guard: `anchor_verified=False` → exit 6 `anchor_preflight_unwired`
     (fail-closed default, mirrors §12.1 pattern).
  3. Load state. `last_halt is None` → exit 0 `nothing_to_clear` (no-op success, no audit).
  4. `last_halt` non-null:
     a. Stamp `acknowledged_at` on the diary (if not already set).
     b. Rotate prior `last_halt` onto `last_halt_history` (cap=5 via _rotate helper).
     c. Set `last_halt = None`.
     d. Commit via `commit_transaction` (chain-stamped S06).
     e. Emit `verb=halt_diary.clear` audit row.

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md
Sections: §5.3, §12.7, §1.1
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Optional

from . import phase_txn as _phase_txn
from . import phase_preflight as _phase_preflight
from .phase_reopen import _rotate_last_halt_history, _ack_diary

_HALT_HISTORY_CAP = 5


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class HaltDiaryError(OSError):
    """Base class for halt-diary admin verb failures."""


class HaltDiaryNothingToClear(HaltDiaryError):
    """last_halt is None — nothing to clear. exit_code = 0 (no-op success)."""

    exit_code = 0


class HaltDiaryNonTtyBlocked(HaltDiaryError):
    """stdin is not a TTY — admin clear refused. exit_code = 6."""

    exit_code = 6


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ClearResult:
    """Outcome of `run_clear`. The CLI dispatcher maps `exit_code` to sys.exit."""

    exit_code: int
    sub_reason: str
    message: str
    cleared: bool


# ---------------------------------------------------------------------------
# run_clear
# ---------------------------------------------------------------------------

_FIX_TTY = (
    "Fix: run `harness halt-diary clear` from a real terminal "
    "(not via a piped or agent-spawned subprocess)"
)
_FIX_ANCHOR = (
    "Fix: caller must pass anchor_verified=True (or skip_anchor_preflight=True "
    "in controlled test paths) so the §12.1 trust chain is satisfied before "
    "mutating state via an admin verb"
)


def run_clear(
    *,
    scratch_root: Path,
    audit_path: Path,
    lock_handle: Any,
    anchor_verified: bool,
    stdin_is_tty: bool,
    by: Optional[str] = None,
) -> ClearResult:
    """§5.3 + §12.7 TTY-required admin verb.

    Parameters
    ----------
    scratch_root : Path
        `.scratch/` directory (contains phase-state.json).
    audit_path : Path
        Audit log path (e.g. `.harness/audit.log`).
    lock_handle : LockHandle
        Must be an acquired, un-released LockHandle. None → TxnLockMissingError.
    anchor_verified : bool
        True when §12.1 anchor has been verified externally. Default False
        fails closed with exit 6 `anchor_preflight_unwired`.
    stdin_is_tty : bool
        Whether stdin is a real TTY. False → exit 6 `non_tty_halt_diary_clear_blocked`.
    by : str | None
        Human identity (email) performing the clear; embedded in audit row.
    """
    scratch = Path(scratch_root)
    audit_path = Path(audit_path)

    # Step 1: TTY gate (§12.7).
    if not stdin_is_tty:
        return ClearResult(
            exit_code=6,
            sub_reason="non_tty_halt_diary_clear_blocked",
            message=(
                f"halt-diary clear refused: non-TTY caller. {_FIX_TTY}"
            ),
            cleared=False,
        )

    # Step 2: Anchor preflight guard (fail-closed).
    if not anchor_verified:
        return ClearResult(
            exit_code=6,
            sub_reason="anchor_preflight_unwired",
            message=(
                f"halt-diary clear refused: anchor not verified. {_FIX_ANCHOR}"
            ),
            cleared=False,
        )

    # Step 3: Lock contract check.
    _phase_txn._check_lock(lock_handle, scratch)

    # Step 4: Load state.
    state_path = scratch / _phase_txn.STATE_NAME
    if not state_path.exists():
        return ClearResult(
            exit_code=0,
            sub_reason="nothing_to_clear",
            message="halt-diary clear: no state file present; nothing to clear.",
            cleared=False,
        )

    before_state = json.loads(state_path.read_text(encoding="utf-8"))
    prior_diary = before_state.get("last_halt")

    # Step 5: No diary present → no-op success (exit 0).
    if prior_diary is None:
        return ClearResult(
            exit_code=0,
            sub_reason="nothing_to_clear",
            message="halt-diary clear: last_halt is None; nothing to clear.",
            cleared=False,
        )

    # Step 6: Ack + rotate + clear.
    now_iso = _phase_preflight.now_iso_z()

    # Stamp acknowledged_at only if not already set (per §1.1 line 67 —
    # preserve existing ack timestamp if already present).
    if prior_diary.get("acknowledged_at") is None:
        acked_diary = _ack_diary(prior_diary, now_iso=now_iso)
    else:
        acked_diary = dict(prior_diary)  # already acked; preserve original timestamp

    # Rotate acked diary onto last_halt_history (cap=5).
    new_history = _rotate_last_halt_history(
        before_state, acked_diary, cap=_HALT_HISTORY_CAP
    )

    after_state = dict(before_state)
    after_state["last_halt"] = None
    after_state["last_halt_history"] = new_history
    after_state = _phase_txn.with_budget_decrement(after_state)

    # Build audit entry (§E spec).
    audit_draft: dict = {
        "verb": "halt_diary.clear",
        "by": by,
        "cleared_diary": dict(acked_diary) if acked_diary else None,
        "args": {
            "at": now_iso,
            "diary_run_id": prior_diary.get("run_id") if prior_diary else None,
            "diary_halt_reason": prior_diary.get("halt_reason") if prior_diary else None,
        },
    }

    txn_id = _phase_txn.commit_transaction(
        scratch,
        lock=lock_handle,
        request=_phase_txn.TxnRequest(
            action="halt_diary.clear",
            before_state=before_state,
            after_state=after_state,
            audit_entry_draft=audit_draft,
        ),
        audit_path=audit_path,
    )

    return ClearResult(
        exit_code=0,
        sub_reason="cleared",
        message=json.dumps(
            {
                "ok": True,
                "verb": "halt_diary.clear",
                "cleared": True,
                "by": by,
                "txn_id": txn_id,
                "diary_run_id": prior_diary.get("run_id") if prior_diary else None,
            },
            indent=2,
            sort_keys=True,
        ),
        cleared=True,
    )


__all__ = [
    "HaltDiaryError",
    "HaltDiaryNothingToClear",
    "HaltDiaryNonTtyBlocked",
    "ClearResult",
    "run_clear",
]
