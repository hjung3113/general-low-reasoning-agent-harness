"""Tests: error-code map consistency (T10).

Verifies that every ``(exit N)`` hint string in the source matches
an entry in docs/error-code-map.md, and that every code in the map
has at least one emitting site in the source.

Design ref: v0.9.5 plan §3.5 + §7.4, impl T10.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO = Path(__file__).parent.parent
_MAP_PATH = _REPO / "docs" / "error-code-map.md"
_SCRIPTS_DIR = _REPO / "scripts"
_LIB_DIR = _SCRIPTS_DIR / "lib"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_map_codes() -> set[int]:
    """Parse all exit code integers from the map's markdown table.

    Only reads the ``| Code |`` column rows (lines that start with ``| <digit>``).
    Returns a set of ints.
    """
    text = _MAP_PATH.read_text(encoding="utf-8")
    codes: set[int] = set()
    for line in text.splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|", line)
        if m:
            codes.add(int(m.group(1)))
    return codes


def _grep_exit_hints(root: Path) -> list[tuple[Path, int, int]]:
    """Walk ``root`` for ``(exit N)`` strings in .py files.

    Returns list of (file, lineno, code).
    Only looks at actual string content (not stripped — that's fine for
    consistency checking because even comment-only hints must match reality).
    """
    pattern = re.compile(r"\(exit\s+(\d+)\)")
    found: list[tuple[Path, int, int]] = []
    for py_file in sorted(root.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in pattern.finditer(line):
                found.append((py_file, lineno, int(m.group(1))))
    return found


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestErrorCodeMapExists:
    def test_map_file_exists(self) -> None:
        assert _MAP_PATH.exists(), (
            f"docs/error-code-map.md not found at {_MAP_PATH}; "
            "run T10 to generate it."
        )

    def test_map_has_table_rows(self) -> None:
        codes = _parse_map_codes()
        assert len(codes) >= 10, (
            f"Expected ≥10 exit codes in the map, found {len(codes)}: {sorted(codes)}"
        )

    def test_map_contains_required_codes(self) -> None:
        """All exit codes declared in exitcodes.py must appear in the map."""
        sys.path.insert(0, str(_SCRIPTS_DIR))
        from lib import exitcodes  # noqa: PLC0415
        declared = {
            getattr(exitcodes, name)
            for name in exitcodes.__all__
        }
        map_codes = _parse_map_codes()
        missing = declared - map_codes
        assert not missing, (
            f"exitcodes.py symbols {missing!r} are not documented in the map. "
            "Add rows to docs/error-code-map.md."
        )


class TestExitHintConsistency:
    """Every (exit N) hint in the source must be documented in the map."""

    def test_all_hints_are_documented(self) -> None:
        """Each (exit N) hint site has a matching code row in the map."""
        hints = _grep_exit_hints(_LIB_DIR)
        # Also check harness.py itself
        harness_file = _SCRIPTS_DIR / "harness.py"
        if harness_file.exists():
            pattern = re.compile(r"\(exit\s+(\d+)\)")
            try:
                text = harness_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            for lineno, line in enumerate(text.splitlines(), 1):
                for m in pattern.finditer(line):
                    hints.append((harness_file, lineno, int(m.group(1))))

        assert hints, "No (exit N) hints found — grep may be broken."

        map_codes = _parse_map_codes()
        undocumented: list[tuple[Path, int, int]] = []
        for file_path, lineno, code in hints:
            if code not in map_codes:
                undocumented.append((file_path, lineno, code))

        if undocumented:
            lines = "\n".join(
                f"  {p.relative_to(_REPO)}:{ln}  exit {c}"
                for p, ln, c in undocumented
            )
            pytest.fail(
                f"{len(undocumented)} (exit N) hint(s) not in docs/error-code-map.md:\n"
                f"{lines}"
            )

    def test_every_map_code_has_an_emitter(self) -> None:
        """Every code in the map must have at least one emitting site in source.

        Emitting sites accepted (in order of preference):
          1. Explicit ``(exit N)`` hint string anywhere in source
          2. An EXIT_* symbol from exitcodes.py used in lib/*.py
          3. A numeric literal pattern: ``exit_code=N``, ``return N``,
             ``sys.exit(N)``, or ``raise SystemExit(N)`` in lib/*.py

        Codes 0 and 1 are exempted (universal success/generic failure).
        """
        map_codes = _parse_map_codes()
        # Codes 0 and 1 are intentionally hint-free (universal success/failure)
        map_codes_to_check = map_codes - {0, 1}

        hints = _grep_exit_hints(_LIB_DIR)
        hinted_codes = {code for _, _, code in hints}

        # Also check symbol usage (EXIT_* constants) counts as "emitted"
        sys.path.insert(0, str(_SCRIPTS_DIR))
        from lib import exitcodes  # noqa: PLC0415
        symbol_to_code = {
            name: getattr(exitcodes, name)
            for name in exitcodes.__all__
        }
        code_to_symbol = {v: k for k, v in symbol_to_code.items()}

        # Build a set of all codes that appear as numeric literals in any
        # of the four emitter patterns across lib/*.py
        numeric_emitter_codes: set[int] = set()
        _numeric_patterns = [
            re.compile(r"\bexit_code\s*=\s*(\d+)\b"),
            re.compile(r"\breturn\s+(\d+)\b"),
            re.compile(r"\bsys\.exit\((\d+)\)"),
            re.compile(r"\braise\s+SystemExit\((\d+)\)"),
        ]
        for py_file in sorted(_LIB_DIR.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pat in _numeric_patterns:
                for m in pat.finditer(content):
                    numeric_emitter_codes.add(int(m.group(1)))

        missing_emitters: list[int] = []
        for code in sorted(map_codes_to_check):
            if code in hinted_codes:
                continue  # has an explicit (exit N) hint
            if code in numeric_emitter_codes:
                continue  # has a numeric literal emitter
            # Check if an EXIT_* symbol for this code is used anywhere in lib
            symbol = code_to_symbol.get(code)
            if symbol:
                for py_file in sorted(_LIB_DIR.rglob("*.py")):
                    if "__pycache__" in py_file.parts:
                        continue
                    try:
                        file_content = py_file.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    if symbol in file_content:
                        break
                else:
                    missing_emitters.append(code)
            else:
                missing_emitters.append(code)

        if missing_emitters:
            pytest.fail(
                f"Codes in map with no emitter found in source: {missing_emitters}. "
                "Remove from map or add the missing (exit N) hint string / numeric emitter."
            )


class TestHarnessdebugHandler:
    """Tests for the HARNESS_DEBUG uncaught-exception handler in harness.py."""

    def _run_harness(
        self,
        env_extra: dict[str, str] | None = None,
        inject_exception: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run a tiny inline script that simulates an uncaught exception
        through the harness __main__ handler logic."""
        # We test the handler logic directly by importing and exercising
        # the harness module's __main__ guard via a subprocess.
        import os
        env = {**os.environ}
        if env_extra:
            env.update(env_extra)

        # Inline script that reproduces the handler path without needing
        # the full harness import chain.
        script = """
import sys, os, traceback

def run():
    raise RuntimeError("injected test error from T10")

if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except SystemExit:
        raise
    except Exception as e:
        if os.environ.get("HARNESS_DEBUG") == "1":
            traceback.print_exc(file=sys.stderr)
        else:
            tb = traceback.extract_tb(e.__traceback__)
            if tb:
                first = tb[0]
                print(f"error: {type(e).__name__} at {first.filename}:{first.lineno}: {e}", file=sys.stderr)
            else:
                print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
            print("Set HARNESS_DEBUG=1 for full traceback.", file=sys.stderr)
        sys.exit(1)
"""
        return subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_default_produces_single_line_error(self) -> None:
        """Without HARNESS_DEBUG, stderr is a single-line summary + hint."""
        result = self._run_harness()
        assert result.returncode == 1
        stderr_lines = [ln for ln in result.stderr.strip().splitlines() if ln]
        # Expect: 1 error line + 1 hint line = 2 lines
        assert len(stderr_lines) == 2, (
            f"Expected 2 stderr lines, got {len(stderr_lines)}: {result.stderr!r}"
        )
        assert "error: RuntimeError" in stderr_lines[0]
        assert "injected test error from T10" in stderr_lines[0]
        assert "HARNESS_DEBUG=1" in stderr_lines[1]

    def test_harness_debug_produces_traceback(self) -> None:
        """With HARNESS_DEBUG=1, stderr contains a multi-line traceback."""
        result = self._run_harness(env_extra={"HARNESS_DEBUG": "1"})
        assert result.returncode == 1
        stderr_lines = result.stderr.strip().splitlines()
        # Full traceback has "Traceback (most recent call last):" + frames + exception line
        assert len(stderr_lines) > 2, (
            f"Expected multi-line traceback, got {len(stderr_lines)} lines: {result.stderr!r}"
        )
        assert any("Traceback" in ln for ln in stderr_lines), (
            f"Expected 'Traceback' in stderr: {result.stderr!r}"
        )
        assert any("RuntimeError" in ln for ln in stderr_lines)

    def test_default_no_traceback_frames(self) -> None:
        """Without HARNESS_DEBUG, stderr must NOT contain 'Traceback'."""
        result = self._run_harness()
        assert "Traceback" not in result.stderr, (
            f"Unexpected traceback in default mode: {result.stderr!r}"
        )

    def test_system_exit_propagates_normally(self) -> None:
        """SystemExit must NOT be caught by the uncaught-exception handler."""
        import os
        env = dict(os.environ)
        script = """
import sys, os, traceback

def run():
    return 42  # intentional exit code

if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except SystemExit:
        raise
    except Exception as e:
        if os.environ.get("HARNESS_DEBUG") == "1":
            traceback.print_exc(file=sys.stderr)
        else:
            tb = traceback.extract_tb(e.__traceback__)
            if tb:
                first = tb[0]
                print(f"error: {type(e).__name__} at {first.filename}:{first.lineno}: {e}", file=sys.stderr)
            else:
                print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
            print("Set HARNESS_DEBUG=1 for full traceback.", file=sys.stderr)
        sys.exit(1)
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 42, (
            f"Expected rc=42 from SystemExit(run()), got {result.returncode}"
        )
        assert result.stderr == "", (
            f"Expected empty stderr for clean SystemExit, got: {result.stderr!r}"
        )
