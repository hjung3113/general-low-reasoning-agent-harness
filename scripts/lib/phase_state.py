"""Phase-state schema v2 — new fields, defaults, read-time legacy migration.

Slice S01-A.1 of `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`
(§1.1 schema delta, §1.2 read-time migration, §12.15 amendments).

This module is intentionally *pure* — no filesystem, no audit log, no locking.
Filesystem orchestration (atomic write + `verb=migrate.state_v2` audit entry)
lives in S01-A.2 (`state_migrate.forward`). Locking + durable fsync land in
S01-B/S01-C/S01-D. State trust preflight lands in S01-E.

Public API:
    EXECUTION_MODES                -- frozenset of permitted enum values
    LEGACY_AUTOMATION_TO_EXECUTION -- mapping used by the read-time migrator
    NEW_V2_FIELDS                  -- field-name → default-value mapping
    coerce_legacy_execution_mode(state) -> state
    apply_v2_defaults(state) -> state
"""

from __future__ import annotations

from typing import Any, Mapping


EXECUTION_MODES: frozenset[str] = frozenset({
    "manual",
    "phase_autopilot",
    "chain_autopilot",
})


# Design §1.2 — read-time alias mapping.
LEGACY_AUTOMATION_TO_EXECUTION: dict[str, str] = {
    "manual": "manual",
    "chain": "phase_autopilot",
    "auto": "chain_autopilot",
}


# Design §1.1 — defaults for every new v2 field. The ordering of keys is
# stable (Python 3.7+ dict insertion order) so reviewers can grep the file
# top-to-bottom against the design doc table.
NEW_V2_FIELDS: dict[str, Any] = {
    "execution_mode": "manual",
    "autopilot_run_id": None,
    "autopilot_mode": None,
    "autopilot_phase_slug": None,
    "autopilot_start_entry_hash": None,
    "autopilot_allow_network": False,
    # S10a step 2: wall-clock anchor for wall_seconds budget enforcement.
    # Stamped by cli_budgets.stamp_autopilot_started_at on run_start;
    # cleared by cli_budgets.clear_autopilot_started_at on run_stop/halt.
    # Existing v2 state files lacking this field default to None on read.
    "autopilot_started_at_iso": None,
    "cli_budgets_remaining": None,
    "last_halt": None,
    "last_halt_history": [],
    "execute_attempt_started_at": None,
    "plan_finalized_at": None,
    "draft_verification": None,
    "draft_allowed_paths": None,
}


def coerce_legacy_execution_mode(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new dict where ``execution_mode`` is derived per design §1.2.

    Precedence:
      1. If the ``execution_mode`` **key is present** in ``state`` → keep it
         (authoritative; legacy alias is ignored to match design §1.1
         "Single source of truth"). An explicit JSON ``null`` is treated as
         an invalid explicit value and rejected.
      2. Else if the ``automation_mode`` **key is present** → translate via
         ``LEGACY_AUTOMATION_TO_EXECUTION``. An explicit ``null`` here is
         likewise rejected — only true absence is the v0.6.1 shape.
      3. Else (pristine v0.6.1 install: both keys absent) → ``manual``.

    Raises ``ValueError`` on unrecognised explicit values to fail closed:
    a forged or hand-edited state file should NOT silently degrade to a
    permissive default. Filesystem-level forgery defence is the state-trust
    preflight (S01-E); this is the in-memory equivalent.

    Key-presence (``in``) is intentional rather than ``.get(...) is None``:
    design §1.2 distinguishes "absent" from "explicit null" — only the
    former triggers the default path.
    """
    out = dict(state)
    if "execution_mode" in out:
        explicit = out["execution_mode"]
        if explicit not in EXECUTION_MODES:
            raise ValueError(
                f"unknown execution_mode={explicit!r}; "
                f"expected one of {sorted(EXECUTION_MODES)}"
            )
        return out

    if "automation_mode" not in out:
        out["execution_mode"] = "manual"
        return out

    legacy = out["automation_mode"]
    if legacy not in LEGACY_AUTOMATION_TO_EXECUTION:
        raise ValueError(
            f"unknown legacy automation_mode={legacy!r}; "
            f"expected one of {sorted(LEGACY_AUTOMATION_TO_EXECUTION)}"
        )
    out["execution_mode"] = LEGACY_AUTOMATION_TO_EXECUTION[legacy]
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

    Mirror of ``apply_v2_defaults`` — used by ``state_migrate.reverse`` so
    that ``reverse(forward(s)) == s`` round-trip equality holds for legacy
    v0 inputs that do not know about the v2 schema fields. Non-v2 fields
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
    "EXECUTION_MODES",
    "LEGACY_AUTOMATION_TO_EXECUTION",
    "NEW_V2_FIELDS",
    "coerce_legacy_execution_mode",
    "apply_v2_defaults",
    "strip_v2_only_fields",
    "stamp_transition_timestamps",
]
