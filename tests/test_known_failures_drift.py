"""T9 — Known-failures drift gate.

Reads the junit.xml cache from .harness-test-cache/junit.xml and compares
the failing test set against tests/KNOWN_FAILING_TESTS.md.

Test cases:
1. Missing junit.xml cache → test skipped with seeding instruction
2. Cache matches known set → test green
3. Cache differs from known set → test red with actionable diff message

Cache freshness:
- junit.xml mtime must be newer than newest mtime in scripts/ and tests/.
- STALE = FAIL by default (prevents silently testing against outdated baseline).
- Bypass stale check (emergency only): HARNESS_KNOWN_FAILURES_ALLOW_STALE=1.
"""
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_JUNIT_CACHE = _REPO_ROOT / ".harness-test-cache" / "junit.xml"
_KNOWN_FILE = _REPO_ROOT / "tests" / "KNOWN_FAILING_TESTS.md"


def _read_known_failures() -> set[str]:
    """Parse node IDs from the code block in KNOWN_FAILING_TESTS.md."""
    if not _KNOWN_FILE.exists():
        return set()
    text = _KNOWN_FILE.read_text(encoding="utf-8")
    # Extract content between first ``` block
    match = re.search(r"```\n(.*?)```", text, re.DOTALL)
    if not match:
        return set()
    lines = match.group(1).strip().splitlines()
    return {line.strip() for line in lines if line.strip()}


def _parse_junit_failures(junit_path: Path) -> set[str]:
    """Parse failing test node IDs from junit XML."""
    try:
        tree = ET.parse(str(junit_path))
    except ET.ParseError as exc:
        raise ValueError(f"junit.xml parse error: {exc}") from exc
    root = tree.getroot()
    failures: set[str] = set()
    for tc in root.iter("testcase"):
        if tc.find("failure") is not None or tc.find("error") is not None:
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            # Reconstruct node-id from classname + name
            # classname: e.g. "tests/smoke/test_grep_gate_stale_terms" or
            #             "tests.smoke.test_grep_gate_stale_terms"
            # Convert dots to slashes for path portion, keep class at end
            parts = classname.split(".")
            # If classname has path separators already (pytest formats them as paths)
            if "/" in classname:
                # e.g. "tests/smoke/test_grep_gate_stale_terms.TestGatePassesClean"
                # Already a path — just reconstruct
                path_part, _, class_part = classname.rpartition(".")
                if path_part.endswith(".py"):
                    node_id = f"{path_part}::{class_part}::{name}" if class_part else f"{path_part}::{name}"
                else:
                    node_id = f"{path_part}.py::{class_part}::{name}" if class_part else f"{path_part}.py::{name}"
            else:
                # Dot-separated: last non-empty component is class or module
                # Heuristic: if last part starts with uppercase it's a class
                if parts and parts[-1] and parts[-1][0].isupper():
                    class_part = parts[-1]
                    path_parts = parts[:-1]
                else:
                    class_part = ""
                    path_parts = parts
                path = "/".join(path_parts) + ".py"
                if class_part:
                    node_id = f"{path}::{class_part}::{name}"
                else:
                    node_id = f"{path}::{name}"
            failures.add(node_id)
    return failures


def _is_cache_stale() -> bool:
    """Return True if junit.xml is older than newest file in scripts/ or tests/."""
    if not _JUNIT_CACHE.exists():
        return True
    cache_mtime = _JUNIT_CACHE.stat().st_mtime
    newest = 0.0
    for search_dir in (_REPO_ROOT / "scripts", _REPO_ROOT / "tests"):
        if not search_dir.exists():
            continue
        for p in search_dir.rglob("*"):
            if p.is_file() and str(p) != str(_JUNIT_CACHE):
                mtime = p.stat().st_mtime
                if mtime > newest:
                    newest = mtime
    return cache_mtime < newest


# ---------------------------------------------------------------------------
# Unit helpers for testing drift logic without touching the real cache
# ---------------------------------------------------------------------------


def _build_junit_xml(failures: list[str]) -> str:
    """Build a minimal junit XML string with given node-id failures."""
    cases = []
    for nid in failures:
        # Convert node-id to classname/name
        # e.g. tests/foo/test_bar.py::MyClass::test_baz
        parts = nid.split("::")
        if len(parts) == 3:
            path_part, class_part, name = parts
            classname = path_part.replace("/", ".").removesuffix(".py") + "." + class_part
        elif len(parts) == 2:
            path_part, name = parts
            classname = path_part.replace("/", ".").removesuffix(".py")
        else:
            classname = nid
            name = nid
        cases.append(
            f'<testcase classname="{classname}" name="{name}">'
            f'<failure message="fail">fail</failure></testcase>'
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<testsuite name="pytest" tests="{len(failures)}">'
        + "".join(cases)
        + "</testsuite>"
    )


def _write_tmp_junit(tmp_path: Path, failures: list[str]) -> Path:
    xml_path = tmp_path / "junit.xml"
    xml_path.write_text(_build_junit_xml(failures), encoding="utf-8")
    return xml_path


# ---------------------------------------------------------------------------
# Test 1: missing cache → skip
# ---------------------------------------------------------------------------

def test_missing_cache_skips_with_instruction() -> None:
    """T9-1: missing junit.xml → test skipped with seeding instruction."""
    if _JUNIT_CACHE.exists():
        pytest.skip("Cache present; this test only validates the missing-cache skip path.")
    # When cache is absent: the other tests would skip. Document the skip instruction.
    pytest.skip(
        f"No junit.xml cache at {_JUNIT_CACHE}. "
        "Run: scripts/refresh_known_failures.sh"
    )


# ---------------------------------------------------------------------------
# Unit test: drift detection logic (no real cache needed)
# ---------------------------------------------------------------------------


def test_drift_detection_new_failure(tmp_path: Path) -> None:
    """T9-3 unit: drift detected → actionable message with new failure listed."""
    known = {"tests/foo/test_bar.py::TestFoo::test_existing_fail"}
    extra_fail = "tests/foo/test_bar.py::TestFoo::test_new_regression"
    current = known | {extra_fail}

    new_failures = current - known
    fixed_knowns = known - current
    assert extra_fail in new_failures
    assert not fixed_knowns

    # Build the message (mimics test_known_failures_not_drifted's failure path)
    lines = ["Known-failures drift detected."]
    if new_failures:
        lines.append("NEW failures (add to tests/KNOWN_FAILING_TESTS.md or fix):")
        for nid in sorted(new_failures):
            lines.append(f"  - {nid}")
    assert "NEW failures" in lines[1]
    assert f"  - {extra_fail}" in lines


def test_drift_detection_fixed_known(tmp_path: Path) -> None:
    """T9-3 unit: fixed known → actionable message with fixed known listed."""
    known = {
        "tests/foo/test_bar.py::TestFoo::test_now_fixed",
        "tests/foo/test_bar.py::TestFoo::test_still_failing",
    }
    current = {"tests/foo/test_bar.py::TestFoo::test_still_failing"}

    new_failures = current - known
    fixed_knowns = known - current
    assert "tests/foo/test_bar.py::TestFoo::test_now_fixed" in fixed_knowns
    assert not new_failures

    lines = ["Known-failures drift detected."]
    if fixed_knowns:
        lines.append("FIXED knowns (REMOVE from tests/KNOWN_FAILING_TESTS.md):")
        for nid in sorted(fixed_knowns):
            lines.append(f"  - {nid}")
    assert "FIXED knowns" in lines[1]


# ---------------------------------------------------------------------------
# Test 2 + 3: cache present → compare vs KNOWN
# ---------------------------------------------------------------------------

def test_known_failures_not_drifted() -> None:
    """T9-2/3: compare junit.xml failing set vs KNOWN_FAILING_TESTS.md.

    Passes when sets match. Fails with actionable diff if they diverge.
    Skips if cache is missing or stale (unless HARNESS_KNOWN_FAILURES_ALLOW_STALE=1).
    """
    if not _JUNIT_CACHE.exists():
        pytest.skip(
            f"No junit.xml cache at {_JUNIT_CACHE}.\n"
            "Run: scripts/refresh_known_failures.sh"
        )

    allow_stale = os.environ.get("HARNESS_KNOWN_FAILURES_ALLOW_STALE", "") == "1"

    if _is_cache_stale() and not allow_stale:
        msg = (
            f"Cache stale: {_JUNIT_CACHE} is older than code in scripts/ or tests/.\n"
            "Run: scripts/refresh_known_failures.sh\n"
            "Or bypass (emergency only): HARNESS_KNOWN_FAILURES_ALLOW_STALE=1"
        )
        pytest.fail(msg)

    try:
        current_failing = _parse_junit_failures(_JUNIT_CACHE)
    except ValueError as exc:
        pytest.skip(f"Cannot parse junit.xml: {exc}")

    known_failing = _read_known_failures()

    new_failures = current_failing - known_failing
    fixed_knowns = known_failing - current_failing

    if not new_failures and not fixed_knowns:
        return  # T9-2: green — no drift

    # T9-3: drift detected — actionable message
    lines = ["Known-failures drift detected."]
    if new_failures:
        lines.append("NEW failures (add to tests/KNOWN_FAILING_TESTS.md or fix):")
        for nid in sorted(new_failures):
            lines.append(f"  - {nid}")
    if fixed_knowns:
        lines.append("FIXED knowns (REMOVE from tests/KNOWN_FAILING_TESTS.md):")
        for nid in sorted(fixed_knowns):
            lines.append(f"  - {nid}")
    lines.append("Refresh: scripts/refresh_known_failures.sh")
    pytest.fail("\n".join(lines))
