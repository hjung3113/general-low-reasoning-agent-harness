#!/usr/bin/env python3
"""Lint: assert every `from lib.X` / `import lib.X` in harness.py + lib/**/*.py
has a corresponding entry in harness/manifest.json.

Exit 0  — all referenced lib modules present in manifest.
Exit 1  — one or more modules missing; missing paths printed to stdout.

Run:  python3 scripts/test_manifest_completeness.py

Allowlist:  add ``# manifest-allow: <reason>`` on the import line to opt out.
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO / "harness" / "manifest.json"
SCRIPTS = REPO / "scripts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _module_to_source_path(module: str) -> str:
    """Convert a lib module dotted name to its expected manifest source path.

    Examples:
        lib.state            → scripts/lib/state.py
        lib.project_dashboard.core → scripts/lib/project_dashboard/core.py
    """
    parts = module.split(".")  # e.g. ['lib', 'state'] or ['lib', 'pd', 'core']
    return "scripts/" + "/".join(parts) + ".py"


def _allowlisted(source_lines: list[str], lineno: int) -> bool:
    """Return True if the import line carries a manifest-allow comment."""
    line = source_lines[lineno - 1] if 0 < lineno <= len(source_lines) else ""
    return "# manifest-allow:" in line


def _collect_lib_imports(path: Path) -> list[tuple[str, int]]:
    """AST-walk *path* and return (module_dotted_name, lineno) for every
    ``from lib.X import …`` / ``from lib import X`` / ``import lib.X`` found.

    Handles all AST positions including inside ``if``/``try`` blocks.
    Relative imports (``from . import …``) are skipped.
    """
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(path))
    except (OSError, SyntaxError):
        return []

    lines = src.splitlines()
    results: list[tuple[str, int]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # relative import — skip
                continue
            mod = node.module or ""
            if mod == "lib":
                # from lib import X  →  treat X as a top-level lib module
                for alias in node.names:
                    full = f"lib.{alias.name}"
                    if not _allowlisted(lines, node.lineno):
                        results.append((full, node.lineno))
            elif mod.startswith("lib."):
                if not _allowlisted(lines, node.lineno):
                    results.append((mod, node.lineno))

        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == "lib" or name.startswith("lib."):
                    if not _allowlisted(lines, node.lineno):
                        results.append((name, node.lineno))

    return results


def _load_manifest_source_paths(manifest_path: Path) -> set[str]:
    """Return the set of ``source`` field values from manifest.json."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = data.get("files", [])
    return {entry["source"] for entry in files if "source" in entry}


def _source_files() -> list[Path]:
    """Return harness.py + all scripts/lib/**/*.py (sorted, deduplicated)."""
    seen: set[Path] = set()
    results: list[Path] = []

    candidates = [SCRIPTS / "harness.py"] + sorted(
        (SCRIPTS / "lib").rglob("*.py")
    )
    for p in candidates:
        resolved = p.resolve()
        if resolved not in seen and resolved.is_file():
            seen.add(resolved)
            results.append(p)
    return results


# ---------------------------------------------------------------------------
# Core lint
# ---------------------------------------------------------------------------

def run_lint(
    manifest_path: Path = MANIFEST_PATH,
) -> list[tuple[Path, int, str, str]]:
    """Return list of (file, lineno, module_name, expected_source_path) for
    every import whose manifest entry is absent.
    """
    manifest_sources = _load_manifest_source_paths(manifest_path)
    violations: list[tuple[Path, int, str, str]] = []

    for sf in _source_files():
        for module, lineno in _collect_lib_imports(sf):
            expected = _module_to_source_path(module)
            if expected not in manifest_sources:
                violations.append((sf, lineno, module, expected))

    return violations


def _format_table(violations: list[tuple[Path, int, str, str]]) -> str:
    rows = []
    for f, lineno, module, expected in violations:
        rel = f.relative_to(REPO) if f.is_absolute() else f
        rows.append(f"  {rel}:{lineno}  [{module}]  missing: {expected}")
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Self-test (sandboxed — never modifies real manifest.json)
# ---------------------------------------------------------------------------

def _self_test() -> None:
    """Verify lint correctly detects missing and present manifest entries.

    Uses in-memory temp files; never touches harness/manifest.json.
    Raises AssertionError on failure.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Build a minimal fake manifest with one lib entry
        fake_manifest = tmp / "manifest.json"
        fake_manifest.write_text(
            json.dumps({
                "version": "test",
                "files": [
                    {"source": "scripts/lib/present_module.py", "path": "x"},
                ],
            }),
            encoding="utf-8",
        )

        # Case 1: import whose module IS in manifest → no violation
        good_py = tmp / "good.py"
        good_py.write_text(
            "from lib.present_module import Foo\n",
            encoding="utf-8",
        )

        # Case 2: import whose module is NOT in manifest → violation
        bad_py = tmp / "bad.py"
        bad_py.write_text(
            "from lib.absent_module import Bar\n",
            encoding="utf-8",
        )

        # Case 3: allowlisted import → no violation even if absent
        allowed_py = tmp / "allowed.py"
        allowed_py.write_text(
            "from lib.absent_but_allowed import Baz  # manifest-allow: dynamic\n",
            encoding="utf-8",
        )

        # Case 4: import lib.X (direct import style)
        direct_py = tmp / "direct.py"
        direct_py.write_text(
            "import lib.absent_direct\n",
            encoding="utf-8",
        )

        manifest_sources = _load_manifest_source_paths(fake_manifest)

        # good.py: should have 0 violations
        good_imports = _collect_lib_imports(good_py)
        good_violations = [
            (m, _module_to_source_path(m))
            for m, _ in good_imports
            if _module_to_source_path(m) not in manifest_sources
        ]
        assert good_violations == [], (
            f"Self-test: good.py should have no violations, got {good_violations!r}"
        )

        # bad.py: should have 1 violation
        bad_imports = _collect_lib_imports(bad_py)
        bad_violations = [
            (m, _module_to_source_path(m))
            for m, _ in bad_imports
            if _module_to_source_path(m) not in manifest_sources
        ]
        assert len(bad_violations) == 1, (
            f"Self-test: bad.py should have 1 violation, got {bad_violations!r}"
        )
        assert bad_violations[0][1] == "scripts/lib/absent_module.py", (
            f"Self-test: unexpected path {bad_violations[0][1]!r}"
        )

        # allowed.py: _collect_lib_imports returns nothing (allowlisted)
        allowed_imports = _collect_lib_imports(allowed_py)
        assert allowed_imports == [], (
            f"Self-test: allowed.py should be empty after allowlist, got {allowed_imports!r}"
        )

        # direct.py: import lib.absent_direct → 1 violation
        direct_imports = _collect_lib_imports(direct_py)
        direct_violations = [
            (m, _module_to_source_path(m))
            for m, _ in direct_imports
            if _module_to_source_path(m) not in manifest_sources
        ]
        assert len(direct_violations) == 1, (
            f"Self-test: direct.py should have 1 violation, got {direct_violations!r}"
        )


# ---------------------------------------------------------------------------
# Pytest entry points
# ---------------------------------------------------------------------------

def test_manifest_completeness_self_test() -> None:
    """pytest: lint self-test passes (sandboxed fixtures)."""
    _self_test()


def test_manifest_completeness_corpus_clean() -> None:
    """pytest: no manifest-missing imports in harness.py + lib/**/*.py."""
    violations = run_lint()
    if violations:
        table = _format_table(violations)
        raise AssertionError(
            f"manifest-completeness violations ({len(violations)}):\n{table}"
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    _self_test()

    violations = run_lint()

    if not violations:
        n = len(_source_files())
        print(f"manifest-completeness: OK ({n} source files scanned, 0 violations)")
        return 0

    print(
        f"manifest-completeness: FAIL — {len(violations)} import(s) lack a manifest entry:\n"
    )
    print(_format_table(violations))
    print(
        textwrap.dedent("""
        Each listed module must appear in harness/manifest.json as a "source" entry.
        To opt out of the check add a trailing comment on the import line:
          # manifest-allow: <reason>
        """).rstrip()
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
