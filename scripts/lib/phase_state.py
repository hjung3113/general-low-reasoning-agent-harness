"""Phase-state schema v2 — new fields, defaults, read-time legacy migration.

This module is intentionally *pure* — no filesystem, no audit log, no locking.
Filesystem orchestration (atomic write + audit entry) is handled by callers.

Public API:
    NEW_V2_FIELDS                  -- field-name → default-value mapping
    apply_v2_defaults(state) -> state
"""

from __future__ import annotations

from typing import Any, Mapping


# Design §1.1 — defaults for every new v2 field. The ordering of keys is
# stable (Python 3.7+ dict insertion order) so reviewers can grep the file
# top-to-bottom against the design doc table.
NEW_V2_FIELDS: dict[str, Any] = {
    "execute_attempt_started_at": None,
    "plan_finalized_at": None,
    "draft_verification": None,
    "draft_allowed_paths": None,
}


def coerce_legacy_execution_mode(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new dict with execution_mode normalized to 'manual'.

    Backward compat: previously supported autopilot modes; now always
    collapses to manual since autopilot is removed.
    """
    out = dict(state)
    # Drop legacy automation_mode if present — always use manual.
    out["execution_mode"] = "manual"
    return out


def apply_v2_defaults(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new dict with every NEW_V2_FIELD populated.

    Existing values win — defaults are only inserted for missing keys.
    Mutable defaults (``list``) are deep-copied so callers cannot share
    references via the module-level constant.

    Idempotent: applying twice yields an ``==``-equal dict.
    """
    out = dict(state)
    for key, default in NEW_V2_FIELDS.items():
        if key in out:
            continue
        if isinstance(default, list):
            out[key] = list(default)
        elif isinstance(default, dict):
            out[key] = dict(default)
        else:
            out[key] = default
    return out


def strip_v2_only_fields(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new dict with every NEW_V2_FIELD removed.

    Returns a new dict with every NEW_V2_FIELD removed. Non-v2 fields
    (including the deprecated legacy ``automation_mode`` alias) are
    preserved unchanged.
    """
    out = dict(state)
    for key in NEW_V2_FIELDS:
        out.pop(key, None)
    return out


def stamp_transition_timestamps(
    state: Mapping[str, Any],
    *,
    to_phase: str,
    now_iso: str,
) -> dict[str, Any]:
    """Return a copy of *state* with §3.6 timestamp fields stamped per
    *to_phase* (review-fix P1-2 — the validator extensions in
    `transition.validate_transition_with_state` reject
    `plan_finalized_at_missing` / `execute_attempt_started_at_missing`,
    so the producer side MUST also stamp them or the forward path
    bricks).

    Stamping rules (anchored on design §1.1 + §3.6):

      - `to_phase == "plan"`: stamp `plan_finalized_at = now_iso`. The
        boundary is "entering plan finalizes plan body" — every fresh
        entry into plan resets the floor for `(plan → execute)`'s
        stale-approval check. (Re-entry from execute/done via
        `--reset-approval` also passes through here.)
      - `to_phase == "execute"`: stamp
        `execute_attempt_started_at = now_iso`. Every entry counts as a
        new execute attempt; combined with the existing approval-reset
        in `_do_phase_set` this means `(execute → done)` correctly
        requires a fresh post-execute-entry approval.
      - other phases: no stamp.

    *now_iso* MUST be in canonical `YYYY-MM-DDTHH:MM:SS[.fff]Z` form
    (the same producer used elsewhere — `timestamps.now_iso_nanos`).
    The validator's `_iso_lt` accepts both seconds- and fractional-
    precision shapes; the producer is free to pick either.

    Pure function: no I/O, no mutation of the input mapping.
    """
    out = dict(state)
    if to_phase == "plan":
        out["plan_finalized_at"] = now_iso
    elif to_phase == "execute":
        out["execute_attempt_started_at"] = now_iso
    return out


__all__ = [
    "NEW_V2_FIELDS",
    "coerce_legacy_execution_mode",
    "apply_v2_defaults",
    "strip_v2_only_fields",
    "stamp_transition_timestamps",
]
