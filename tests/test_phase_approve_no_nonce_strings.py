"""User-facing strings emitted on the phase.approve code path must not contain 'nonce'."""
from __future__ import annotations

from pathlib import Path


def test_phase_approve_module_has_no_user_facing_nonce_strings():
    source = Path("scripts/lib/phase_approve.py").read_text()
    # Allow comments and the unused-parameter del statement; reject any
    # remaining quoted string containing 'nonce' that is user-visible.
    user_visible_lines = [
        line for line in source.splitlines()
        if ('print(' in line or '"error:' in line or "'error:" in line)
        and 'nonce' in line.lower()
    ]
    assert user_visible_lines == [], (
        f"phase_approve.py still emits user-visible nonce strings: "
        f"{user_visible_lines}"
    )
