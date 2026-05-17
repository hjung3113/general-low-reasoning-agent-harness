"""S01-C: classify() decision matrix (design §3.7).

A record is one of:
  * "live"          -- same host + boot + alive pid + matching start time
  * "foreign_host"  -- different hostname; never auto-recover
  * "stale"         -- same host + boot + dead pid OR mismatched start time
  * "ambiguous"     -- cannot read process info reliably

The decision MUST be deterministic given fixed inputs; we inject
`now/boot_id/hostname/proc_lookup` so the test is independent of the
runner's actual processes.
"""

from __future__ import annotations

import os

import pytest

from lib import phase_lock


def _record(**overrides):
    base = {
        "pid": 12345,
        "hostname": "host-a",
        "process_start_time": 1000.0,
        "boot_id": "boot-X",
        "monotonic_acquired_at": 42.0,
        "acquired_iso": "2026-05-17T03:14:15Z",
        "owner_token": "deadbeef" * 4,
    }
    base.update(overrides)
    return base


def test_classify_foreign_host_when_hostname_differs():
    rec = _record(hostname="host-other")
    v = phase_lock.classify(
        rec,
        current_hostname="host-a",
        current_boot_id="boot-X",
        proc_lookup=lambda pid: (True, 1000.0),
    )
    assert v == "foreign_host"


def test_classify_stale_when_boot_id_differs_same_host():
    """Reboot happened — pid namespace is fresh; record is stale."""
    rec = _record()
    v = phase_lock.classify(
        rec,
        current_hostname="host-a",
        current_boot_id="boot-Y",
        proc_lookup=lambda pid: (True, 1000.0),
    )
    assert v == "stale"


def test_classify_live_when_pid_alive_and_start_time_matches():
    rec = _record()
    v = phase_lock.classify(
        rec,
        current_hostname="host-a",
        current_boot_id="boot-X",
        proc_lookup=lambda pid: (True, 1000.0),
    )
    assert v == "live"


def test_classify_stale_when_pid_dead():
    rec = _record()
    v = phase_lock.classify(
        rec,
        current_hostname="host-a",
        current_boot_id="boot-X",
        proc_lookup=lambda pid: (False, None),
    )
    assert v == "stale"


def test_classify_stale_when_pid_alive_but_start_time_mismatched():
    """PID reuse defense — alive pid but different process."""
    rec = _record(process_start_time=1000.0)
    v = phase_lock.classify(
        rec,
        current_hostname="host-a",
        current_boot_id="boot-X",
        proc_lookup=lambda pid: (True, 2000.0),
    )
    assert v == "stale"


def test_classify_ambiguous_when_proc_lookup_raises():
    rec = _record()

    def lookup(pid):
        raise PermissionError("cannot read /proc")

    v = phase_lock.classify(
        rec,
        current_hostname="host-a",
        current_boot_id="boot-X",
        proc_lookup=lookup,
    )
    assert v == "ambiguous"


def test_classify_returns_only_one_of_four_verdicts():
    """Pin the public enum so callers can rely on a fixed set."""
    assert phase_lock.LOCK_VERDICTS == frozenset({"live", "foreign_host", "stale", "ambiguous"})


# ---------------------------------------------------------------------------
# S01-C review-fix (P1, 2026-05-17): psutil.Error is NOT a subclass of OSError
# (psutil 7.x: psutil.Error(Exception)). classify() MUST catch both families,
# otherwise NoSuchProcess / AccessDenied / ZombieProcess bubble out and a
# transient lookup failure surfaces as an unhandled traceback instead of the
# documented "ambiguous" verdict (design §3.7 ambiguous → exit 3 force-recover).
# ---------------------------------------------------------------------------


def test_classify_ambiguous_when_psutil_no_such_process_raised():
    import psutil

    rec = _record()

    def lookup(pid):
        raise psutil.NoSuchProcess(pid)

    v = phase_lock.classify(
        rec,
        current_hostname="host-a",
        current_boot_id="boot-X",
        proc_lookup=lookup,
    )
    assert v == "ambiguous"


def test_classify_ambiguous_when_psutil_access_denied_raised():
    import psutil

    rec = _record()

    def lookup(pid):
        raise psutil.AccessDenied(pid)

    v = phase_lock.classify(
        rec,
        current_hostname="host-a",
        current_boot_id="boot-X",
        proc_lookup=lookup,
    )
    assert v == "ambiguous"


def test_classify_ambiguous_when_psutil_zombie_process_raised():
    import psutil

    rec = _record()

    def lookup(pid):
        raise psutil.ZombieProcess(pid)

    v = phase_lock.classify(
        rec,
        current_hostname="host-a",
        current_boot_id="boot-X",
        proc_lookup=lookup,
    )
    assert v == "ambiguous"


def test_classify_propagates_unexpected_exceptions():
    """Any *other* exception (not OSError or psutil.Error) is a bug and must
    propagate, not silently downgrade to ambiguous — that would mask real
    problems (KeyboardInterrupt, programmer errors)."""
    rec = _record()

    def lookup(pid):
        raise ValueError("bug in caller")

    with pytest.raises(ValueError):
        phase_lock.classify(
            rec,
            current_hostname="host-a",
            current_boot_id="boot-X",
            proc_lookup=lookup,
        )
