"""T0-4 migrator: relocate non-conforming verification entries into review.

Owning plan: .planning/phases/02b-hardening/plans/02b-05-T0-4-PLAN.md (T0-4).
ADR: docs/adr/2026-05-16-hardening-bundle.md ADR-004 (G4-A, G4-B).
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1.

Pure function — no I/O. Caller (T0-1 forward migrator) wires it into the
``scripts.lib.atomic_io.atomic_write_text`` pipeline. Idempotent on
already-migrated input (re-running on the post-slice shape yields
``==``-equal output the second time).
"""
from __future__ import annotations

from typing import Any

from .check import VERIFICATION_PREFIXES


__all__ = ["migrate_verification_to_review"]


def _actor_token(command: str) -> str:
    """Return the first whitespace-delimited token, or 'migration' fallback.

    The pre-slice schema required ``minLength: 1`` on each entry, so the
    fallback is a defensive guard only; in practice every input has at
    least one token.
    """
    stripped = command.strip()
    if not stripped:
        return "migration"
    return stripped.split(None, 1)[0]


def migrate_verification_to_review(state: dict, *, migration_time: str) -> dict:
    """Move soft-prefix ``verification[*]`` entries into ``review`` losslessly.

    Args:
        state: input v0/v2 dict. NOT mutated.
        migration_time: ISO-8601-UTC timestamp used when ``state['updated_at']``
            is absent; matches the schema's ``at`` pattern.

    Returns:
        New dict with ``verification`` filtered to allowlist-passing entries
        only, and a ``review`` list extended with one object per moved entry.
        Existing ``review`` items are preserved (order: existing first, then
        newly-moved entries in original verification order).

    Each moved entry becomes::

        {actor: <first-whitespace-token, or "migration" if empty>,
         at: <state['updated_at'] or migration_time>,
         evidence_path: "",
         summary: <original string verbatim>}

    Idempotence: when every ``verification[*]`` already passes the
    allowlist, the function returns a dict ``==``-equal to the input
    (modulo a no-op deep-copy of mutable lists).
    """
    out = dict(state)
    raw = state.get("verification", [])
    if not isinstance(raw, list):
        raw = []
    at_value = state.get("updated_at") or migration_time
    if not isinstance(at_value, str):
        at_value = migration_time

    keepers: list[str] = []
    movers: list[dict[str, Any]] = []
    for command in raw:
        if isinstance(command, str) and command.startswith(VERIFICATION_PREFIXES):
            keepers.append(command)
        elif isinstance(command, str):
            movers.append(
                {
                    "actor": _actor_token(command),
                    "at": at_value,
                    "evidence_path": "",
                    "summary": command,
                }
            )
        # Non-string verification entries are dropped (the validator would
        # have rejected them anyway; migrator does not synthesize evidence
        # for them).

    existing_review = state.get("review")
    if not isinstance(existing_review, list):
        existing_review = []
    review_out = list(existing_review) + movers

    out["verification"] = keepers
    out["review"] = review_out
    return out
