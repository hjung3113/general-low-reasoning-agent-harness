"""S01-C review-fix (P2): boot-id stability across calls.

Per design §3.7 the boot identifier is consumed by `classify()` to detect
post-reboot stale locks. The identifier MUST be byte-stable across calls
within a single boot — otherwise a live lock taken in call N classifies
as "stale" in call N+1 because the *current* boot id drifted.

The original Windows fallback computed `int(time.time()) - GetTickCount64 // 1000`
which separately truncated both sides and could disagree by one second
between successive invocations. This regression test pins the contract.
"""

from __future__ import annotations

from unittest import mock

from lib import phase_lock


def test_current_boot_id_returns_stable_value_across_repeated_calls():
    """Five back-to-back calls MUST yield the same string."""
    values = {phase_lock._current_boot_id() for _ in range(5)}
    assert len(values) == 1, f"boot_id drifted across calls: {values}"


def test_current_boot_id_uses_psutil_boot_time_as_stable_source(monkeypatch):
    """The fallback path (Windows + unknown OS) MUST be derived from
    `psutil.boot_time()`, which is a fixed float per boot session, not
    from `int(time.time()) - ticks` that drifts."""
    import psutil

    # Force the non-linux/non-darwin fallback branch.
    monkeypatch.setattr(phase_lock.sys, "platform", "win32")
    monkeypatch.setattr(phase_lock.os, "name", "nt")
    monkeypatch.setattr(psutil, "boot_time", lambda: 1_700_000_000.123)

    first = phase_lock._current_boot_id()
    second = phase_lock._current_boot_id()
    assert first == second
    assert "1700000000" in first or "1.7" in first
