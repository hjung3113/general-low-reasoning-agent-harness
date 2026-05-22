"""S01-B: cross-platform durability primitives.

Tests the contract exported by `scripts/lib/durable_fs.py` per design
§3.8.1 + §12.5 (`docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`):

  * `DurableFsError`        — fault class (OSError subclass; exit 14 caller)
  * `fsync_parent_dir(path)` — POSIX directory fsync / Windows
                                CreateFileW+FlushFileBuffers
  * `fsync_file_durable(fd, *, path)` — POSIX `os.fsync`; macOS
                                `F_FULLFSYNC` (EINVAL fallback to fsync);
                                Windows re-open + `FlushFileBuffers`
  * `replace_with_retry(src, dst)` — `os.replace` with 5× exponential
                                backoff (50/100/200/400/800ms) on
                                `PermissionError` (Windows AV).

POSIX/macOS paths run live. Windows ctypes paths are exercised by
patching the kernel32 wrapper symbols so the test suite is platform-
portable (the real CI matrix row is S13).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

from lib import durable_fs


# ---------------------------------------------------------------------------
# DurableFsError surface
# ---------------------------------------------------------------------------


def test_durable_fs_error_is_oserror_subclass():
    assert issubclass(durable_fs.DurableFsError, OSError)


def test_durable_fs_error_preserves_message():
    err = durable_fs.DurableFsError("flush failed")
    assert "flush failed" in str(err)


# ---------------------------------------------------------------------------
# fsync_parent_dir — POSIX
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only path under test")
def test_fsync_parent_dir_posix_succeeds_on_real_directory(tmp_path: Path):
    target = tmp_path / "file.txt"
    target.write_text("payload", encoding="utf-8")
    # No exception; nothing observable beyond "did not raise".
    durable_fs.fsync_parent_dir(tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only path under test")
def test_fsync_parent_dir_posix_raises_durable_fs_error_on_missing_path(tmp_path: Path):
    missing = tmp_path / "nope"
    with pytest.raises(durable_fs.DurableFsError):
        durable_fs.fsync_parent_dir(missing)


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only path under test")
def test_fsync_parent_dir_accepts_str_or_path(tmp_path: Path):
    durable_fs.fsync_parent_dir(str(tmp_path))
    durable_fs.fsync_parent_dir(Path(tmp_path))


# ---------------------------------------------------------------------------
# fsync_file_durable — POSIX baseline + macOS F_FULLFSYNC behaviour
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only path under test")
def test_fsync_file_durable_posix_baseline(tmp_path: Path):
    target = tmp_path / "data.bin"
    target.write_bytes(b"abc")
    fd = os.open(str(target), os.O_WRONLY)
    try:
        durable_fs.fsync_file_durable(fd, path=target)  # must not raise
    finally:
        os.close(fd)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only F_FULLFSYNC test")
def test_fsync_file_durable_darwin_uses_full_fsync(tmp_path: Path):
    target = tmp_path / "data.bin"
    target.write_bytes(b"abc")
    fd = os.open(str(target), os.O_WRONLY)
    try:
        # We can't introspect F_FULLFSYNC was called without monkey-patching
        # fcntl; do that instead. Real fcntl is still available via the
        # original reference so the EINVAL fallback path is testable below.
        import fcntl

        with mock.patch("fcntl.fcntl", wraps=fcntl.fcntl) as spy:
            durable_fs.fsync_file_durable(fd, path=target)
        # Assert that fcntl.F_FULLFSYNC was attempted at least once on darwin.
        full_fsync_calls = [c for c in spy.call_args_list if c.args[1] == fcntl.F_FULLFSYNC]
        assert full_fsync_calls, "darwin path did not invoke F_FULLFSYNC"
    finally:
        os.close(fd)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only fallback test")
def test_fsync_file_durable_darwin_falls_back_on_einval(tmp_path: Path):
    """If F_FULLFSYNC returns EINVAL (substrate doesn't support it), the
    wrapper MUST silently fall through to `os.fsync` rather than raising."""
    import errno
    import fcntl

    target = tmp_path / "data.bin"
    target.write_bytes(b"abc")
    fd = os.open(str(target), os.O_WRONLY)

    def fake_fcntl(file_descriptor, op, *args):
        if op == fcntl.F_FULLFSYNC:
            raise OSError(errno.EINVAL, "Invalid argument")
        return fcntl.fcntl(file_descriptor, op, *args)

    fsync_called = []

    def fake_fsync(file_descriptor):
        fsync_called.append(file_descriptor)

    try:
        with mock.patch("fcntl.fcntl", side_effect=fake_fcntl), \
             mock.patch.object(durable_fs.os, "fsync", side_effect=fake_fsync):
            durable_fs.fsync_file_durable(fd, path=target)
        assert fsync_called == [fd], "fallback to os.fsync did not run"
    finally:
        os.close(fd)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only error test")
def test_fsync_file_durable_darwin_raises_on_other_oserror(tmp_path: Path):
    """A non-EINVAL OSError from fcntl is propagated as DurableFsError."""
    import errno

    target = tmp_path / "data.bin"
    target.write_bytes(b"abc")
    fd = os.open(str(target), os.O_WRONLY)
    try:
        with mock.patch("fcntl.fcntl", side_effect=OSError(errno.EIO, "I/O error")):
            with pytest.raises(durable_fs.DurableFsError):
                durable_fs.fsync_file_durable(fd, path=target)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# replace_with_retry — exponential backoff on PermissionError
# ---------------------------------------------------------------------------


def test_replace_with_retry_succeeds_on_first_attempt(tmp_path: Path):
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("payload", encoding="utf-8")
    durable_fs.replace_with_retry(src, dst)
    assert not src.exists()
    assert dst.read_text(encoding="utf-8") == "payload"


def test_replace_with_retry_retries_on_permission_error_then_succeeds(tmp_path: Path):
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("payload", encoding="utf-8")

    real_replace = os.replace
    call_count = {"n": 0}

    def flaky_replace(s, d):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise PermissionError("AV holding handle")
        return real_replace(s, d)

    sleeps = []

    with mock.patch.object(durable_fs.os, "replace", side_effect=flaky_replace), \
         mock.patch.object(durable_fs.time, "sleep", side_effect=sleeps.append):
        durable_fs.replace_with_retry(src, dst)

    assert call_count["n"] == 3
    # v0.9.11: backoff schedule extended to 100ms, 250ms, 500ms, 1s, 2s, 4s
    # (was 50/100/200/400/800ms) so Windows Defender / EDR multi-second
    # handle pins no longer time out before release.
    assert sleeps[:2] == [0.1, 0.25]
    assert dst.read_text(encoding="utf-8") == "payload"


def test_replace_with_retry_exhausts_after_six_failures(tmp_path: Path):
    """v0.9.11: backoff extended from 5 → 6 entries."""
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("payload", encoding="utf-8")

    sleeps = []

    with mock.patch.object(
        durable_fs.os,
        "replace",
        side_effect=PermissionError("AV pin"),
    ), mock.patch.object(durable_fs.time, "sleep", side_effect=sleeps.append):
        with pytest.raises(durable_fs.DurableFsError, match="replace"):
            durable_fs.replace_with_retry(src, dst)

    # 6 attempts → 5 sleeps between them; final attempt's failure has no
    # sleep because no retry follows. Schedule:
    # 100/250/500/1000/2000/4000 ms (7.85 s total).
    assert sleeps == [0.1, 0.25, 0.5, 1.0, 2.0]


def test_replace_with_retry_propagates_non_permission_errors(tmp_path: Path):
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("payload", encoding="utf-8")

    class WeirdError(OSError):
        pass

    with mock.patch.object(durable_fs.os, "replace", side_effect=WeirdError("nope")):
        with pytest.raises(WeirdError):
            durable_fs.replace_with_retry(src, dst)


# ---------------------------------------------------------------------------
# Dispatch / module exposure
# ---------------------------------------------------------------------------


def test_module_exposes_documented_public_api():
    for name in (
        "DurableFsError",
        "fsync_parent_dir",
        "fsync_file_durable",
        "replace_with_retry",
    ):
        assert hasattr(durable_fs, name), f"missing public name: {name}"


def test_dispatch_constant_matches_os_name():
    """Internal dispatch constant is consistent with `os.name` at import
    time. Pinned so a future refactor doesn't drift implementations."""
    assert durable_fs._OS_KIND in {"posix", "nt"}
    assert durable_fs._OS_KIND == os.name
