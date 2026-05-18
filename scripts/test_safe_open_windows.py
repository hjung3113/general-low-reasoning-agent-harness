"""
scripts/test_safe_open_windows.py — Unit tests for the Windows safe_open path (§12.2).

All tests run on POSIX CI by patching safe_open._IS_WINDOWS = True and mocking
ctypes / os.lstat so no real Win32 calls are made.

Test cases:
  1. Happy path: normal file, no reparse point → succeeds (returns fd int).
  2. Reparse point set → FenceWindowsReparsePointRefused.
  3. Path escapes sandbox via GetFinalPathNameByHandle resolved-path → FenceAnchorEscape.
  4. CreateFileW returns INVALID_HANDLE_VALUE → FenceWindowsUnsupported.
  5. ctypes.windll unavailable → FenceWindowsUnsupported.
  6. '..' in path → FenceAnchorEscape.
  7. Absolute path argument → ValueError.
  8. msvcrt absent falls back to returning handle int directly.
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
import importlib
import os

# Ensure scripts/lib is importable
_LIB = Path(__file__).parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import safe_open as _safe_open_mod
from safe_open import (
    _windows_open,
    FenceAnchorEscape,
    FenceWindowsReparsePointRefused,
    FenceWindowsUnsupported,
)

# ---------------------------------------------------------------------------
# Helpers to build a mock ctypes / kernel32
# ---------------------------------------------------------------------------

FAKE_HANDLE = 0x00000ABC          # sentinel "valid" HANDLE value
INVALID_HANDLE_VALUE = 0xFFFFFFFF  # ctypes.c_void_p(-1).value on 32-bit; we also check -1

FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400


def _make_kernel32(
    *,
    create_file_return=FAKE_HANDLE,
    get_final_path_return_val=None,   # string written into buf; None → defaults to anchor/file
    get_final_path_ret_count=None,    # how many chars GetFinalPathNameByHandleW "returns"
    get_last_error=0,
):
    """Return a mock kernel32 object wired for _windows_open tests."""
    k = mock.MagicMock(name="kernel32")
    k.CreateFileW.return_value = create_file_return
    k.GetLastError.return_value = get_last_error
    k.CloseHandle.return_value = 1

    def _get_final_path(handle, buf, buf_size, flags):
        path_str = get_final_path_return_val or r"C:\sandbox\file.txt"
        # Write into the ctypes unicode buffer
        buf.value = path_str
        return len(path_str)

    if get_final_path_ret_count == 0:
        # Simulate failure
        def _get_final_path_fail(handle, buf, buf_size, flags):
            return 0
        k.GetFinalPathNameByHandleW.side_effect = _get_final_path_fail
    else:
        k.GetFinalPathNameByHandleW.side_effect = _get_final_path

    return k


def _make_ctypes_module(kernel32):
    """Return a mock ctypes module that exposes windll.kernel32."""
    ctypes_mod = mock.MagicMock(name="ctypes")
    ctypes_mod.windll.kernel32 = kernel32
    ctypes_mod.c_void_p.return_value.value = INVALID_HANDLE_VALUE

    # create_unicode_buffer must return an object with a .value attribute
    def _make_buf(size):
        buf = mock.MagicMock(name=f"ctypes.buffer[{size}]")
        buf.value = ""
        return buf

    ctypes_mod.create_unicode_buffer.side_effect = _make_buf
    return ctypes_mod


# ---------------------------------------------------------------------------
# Shared anchor / path constants
# ---------------------------------------------------------------------------
ANCHOR = r"C:\sandbox"
REL_PATH = "file.txt"
FINAL_PATH_INSIDE = r"C:\sandbox\file.txt"
FINAL_PATH_OUTSIDE = r"C:\escape\elsewhere\file.txt"


def _lstat_no_reparse():
    """Return a mock stat_result with no reparse-point attribute."""
    st = mock.MagicMock(name="lstat_result")
    st.st_file_attributes = 0  # no reparse point
    return st


def _lstat_with_reparse():
    """Return a mock stat_result with FILE_ATTRIBUTE_REPARSE_POINT set."""
    st = mock.MagicMock(name="lstat_result_reparse")
    st.st_file_attributes = FILE_ATTRIBUTE_REPARSE_POINT
    return st


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestWindowsOpenHappyPath(unittest.TestCase):
    """1. Normal file, no reparse point — _windows_open should return an fd."""

    def test_happy_path_returns_fd(self):
        kernel32 = _make_kernel32(
            create_file_return=FAKE_HANDLE,
            get_final_path_return_val=FINAL_PATH_INSIDE,
        )
        ctypes_mod = _make_ctypes_module(kernel32)

        # msvcrt mock: open_osfhandle returns a fake fd
        msvcrt_mod = mock.MagicMock(name="msvcrt")
        msvcrt_mod.open_osfhandle.return_value = 42

        with mock.patch.object(_safe_open_mod, "_IS_WINDOWS", True), \
             mock.patch("builtins.__import__", side_effect=_import_side_effect(
                 {"ctypes": ctypes_mod, "ctypes.wintypes": ctypes_mod.wintypes,
                  "msvcrt": msvcrt_mod}
             )), \
             mock.patch("os.lstat", return_value=_lstat_no_reparse()), \
             mock.patch.object(Path, "resolve", return_value=Path(ANCHOR)):

            fd = _windows_open(REL_PATH, "r", anchor=ANCHOR)

        self.assertEqual(fd, 42)
        kernel32.CreateFileW.assert_called_once()
        kernel32.GetFinalPathNameByHandleW.assert_called_once()


class TestWindowsOpenReparsePoint(unittest.TestCase):
    """2. Reparse point set → FenceWindowsReparsePointRefused."""

    def test_reparse_point_refused(self):
        kernel32 = _make_kernel32(
            create_file_return=FAKE_HANDLE,
            get_final_path_return_val=FINAL_PATH_INSIDE,
        )
        ctypes_mod = _make_ctypes_module(kernel32)
        msvcrt_mod = mock.MagicMock(name="msvcrt")

        with mock.patch.object(_safe_open_mod, "_IS_WINDOWS", True), \
             mock.patch("builtins.__import__", side_effect=_import_side_effect(
                 {"ctypes": ctypes_mod, "ctypes.wintypes": ctypes_mod.wintypes,
                  "msvcrt": msvcrt_mod}
             )), \
             mock.patch("os.lstat", return_value=_lstat_with_reparse()), \
             mock.patch.object(Path, "resolve", return_value=Path(ANCHOR)):

            with self.assertRaises(FenceWindowsReparsePointRefused) as ctx:
                _windows_open(REL_PATH, "r", anchor=ANCHOR)

        self.assertEqual(ctx.exception.exit_code, 11)
        # CloseHandle must still be called (finally block)
        kernel32.CloseHandle.assert_called_once_with(FAKE_HANDLE)


class TestWindowsOpenSandboxEscape(unittest.TestCase):
    """3. GetFinalPathNameByHandle resolves outside anchor → FenceAnchorEscape."""

    def test_escape_refused(self):
        kernel32 = _make_kernel32(
            create_file_return=FAKE_HANDLE,
            get_final_path_return_val=FINAL_PATH_OUTSIDE,
        )
        ctypes_mod = _make_ctypes_module(kernel32)
        msvcrt_mod = mock.MagicMock(name="msvcrt")

        with mock.patch.object(_safe_open_mod, "_IS_WINDOWS", True), \
             mock.patch("builtins.__import__", side_effect=_import_side_effect(
                 {"ctypes": ctypes_mod, "ctypes.wintypes": ctypes_mod.wintypes,
                  "msvcrt": msvcrt_mod}
             )), \
             mock.patch("os.lstat", return_value=_lstat_no_reparse()), \
             mock.patch.object(Path, "resolve", return_value=Path(ANCHOR)):

            with self.assertRaises(FenceAnchorEscape) as ctx:
                _windows_open(REL_PATH, "r", anchor=ANCHOR)

        self.assertEqual(ctx.exception.exit_code, 4)
        kernel32.CloseHandle.assert_called_once_with(FAKE_HANDLE)


class TestWindowsOpenInvalidHandle(unittest.TestCase):
    """4. CreateFileW returns INVALID_HANDLE_VALUE → FenceWindowsUnsupported."""

    def test_invalid_handle_raises(self):
        # Use -1 which is the most common representation
        kernel32 = _make_kernel32(
            create_file_return=-1,
            get_last_error=0x00000002,  # ERROR_FILE_NOT_FOUND
        )
        ctypes_mod = _make_ctypes_module(kernel32)
        msvcrt_mod = mock.MagicMock(name="msvcrt")

        with mock.patch.object(_safe_open_mod, "_IS_WINDOWS", True), \
             mock.patch("builtins.__import__", side_effect=_import_side_effect(
                 {"ctypes": ctypes_mod, "ctypes.wintypes": ctypes_mod.wintypes,
                  "msvcrt": msvcrt_mod}
             )), \
             mock.patch("os.lstat", return_value=_lstat_no_reparse()):

            with self.assertRaises(FenceWindowsUnsupported) as ctx:
                _windows_open(REL_PATH, "r", anchor=ANCHOR)

        self.assertEqual(ctx.exception.exit_code, 11)
        self.assertIn("GetLastError", str(ctx.exception))


class TestWindowsOpenCtypesUnavailable(unittest.TestCase):
    """5. ctypes.windll absent → FenceWindowsUnsupported."""

    def test_no_ctypes_windll(self):
        def _bad_import(name, *args, **kwargs):
            if name == "ctypes":
                raise ImportError("no ctypes")
            return original_import(name, *args, **kwargs)

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        with mock.patch.object(_safe_open_mod, "_IS_WINDOWS", True), \
             mock.patch("builtins.__import__", side_effect=_bad_import):

            with self.assertRaises(FenceWindowsUnsupported) as ctx:
                _windows_open(REL_PATH, "r", anchor=ANCHOR)

        self.assertEqual(ctx.exception.exit_code, 11)


class TestWindowsOpenDotDotRejected(unittest.TestCase):
    """6. '..' in path → FenceAnchorEscape (no Win32 calls made)."""

    def test_dotdot_rejected(self):
        with mock.patch.object(_safe_open_mod, "_IS_WINDOWS", True):
            with self.assertRaises(FenceAnchorEscape):
                _windows_open("../escape.txt", "r", anchor=ANCHOR)


class TestWindowsOpenAbsolutePathRejected(unittest.TestCase):
    """7. Absolute path argument → ValueError."""

    def test_absolute_path_rejected(self):
        with mock.patch.object(_safe_open_mod, "_IS_WINDOWS", True):
            with self.assertRaises(ValueError):
                _windows_open(r"C:\absolute\path.txt", "r", anchor=ANCHOR)


class TestWindowsOpenNoMsvcrtFallback(unittest.TestCase):
    """8. msvcrt not available — falls back to returning handle int directly."""

    def test_no_msvcrt_returns_handle_int(self):
        kernel32 = _make_kernel32(
            create_file_return=FAKE_HANDLE,
            get_final_path_return_val=FINAL_PATH_INSIDE,
        )
        ctypes_mod = _make_ctypes_module(kernel32)

        def _import_no_msvcrt(name, *args, **kwargs):
            if name == "msvcrt":
                raise ImportError("no msvcrt")
            if name in ("ctypes", "ctypes.wintypes"):
                return ctypes_mod
            return original_import(name, *args, **kwargs)

        import builtins
        original_import = builtins.__import__

        with mock.patch.object(_safe_open_mod, "_IS_WINDOWS", True), \
             mock.patch("builtins.__import__", side_effect=_import_no_msvcrt), \
             mock.patch("os.lstat", return_value=_lstat_no_reparse()), \
             mock.patch.object(Path, "resolve", return_value=Path(ANCHOR)):

            fd = _windows_open(REL_PATH, "r", anchor=ANCHOR)

        # Without msvcrt, the raw HANDLE int is returned
        self.assertEqual(fd, FAKE_HANDLE)


# ---------------------------------------------------------------------------
# Helper: selective __import__ side-effect
# ---------------------------------------------------------------------------

def _import_side_effect(overrides: dict):
    """Return an __import__ side-effect that substitutes specific module names."""
    import builtins
    original = builtins.__import__

    def _import(name, *args, **kwargs):
        # Check overrides
        for key, mod in overrides.items():
            if name == key or name.startswith(key + "."):
                return mod
        return original(name, *args, **kwargs)

    return _import


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
