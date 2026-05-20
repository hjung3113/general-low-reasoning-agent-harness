#!/usr/bin/env python3
"""Lint: scan test corpus for forbidden false-rc patterns (smoke contract).

Contract documented in tests/SMOKE_CONTRACT.md.

Exit 0  — no violations found.
Exit 1  — one or more violations; table printed to stdout.

Run:  python3 scripts/test_smoke_contract.py
"""

from __future__ import annotations

import re
import sys
import textwrap
import tempfile
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SCAN_GLOBS = [
    "scripts/test_*.py",
    "tests/**/*.py",
    ".github/workflows/*.yml",
    "scripts/*.sh",
]

ALLOWLIST_SUFFIX = re.compile(r"#\s*smoke-contract:\s*allow\s+\S")

# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------

# Rule 1 / 2: pipe into tail or head followed by echo $? on the same line
# Catches:  cmd 2>&1 | tail ...; echo $?
#           cmd 2>&1 | head ...; echo $?
RULE_PIPE_TAIL_HEAD = re.compile(
    r"2>&1\s*\|\s*(?:tail|head)\b.*;\s*echo\s+\$\?"
)

# Rule 3: pipeline with echo $? but no pipefail declaration on the line
# Catches:  cmd 2>&1 | <anything>; echo $?  (when line lacks set -o pipefail
# or ${PIPESTATUS[0]}).  We check per-line; broader pipefail presence is noted
# in the contract docs but per-line detection is the lint's job here.
RULE_PIPE_ECHO_RC = re.compile(
    r"2>&1\s*\|[^|].*;\s*echo\s+\$\?"
)

# Rule 4: || true without allowlist comment
RULE_OR_TRUE = re.compile(r"\|\|\s*true\b")

# Rule 5: subprocess.run with check=False (Python)
# Enforced below in multi-line window scan, not as a simple regex.
RULE_CHECK_FALSE = re.compile(r"\bcheck\s*=\s*False\b")

# Rule 6: eval $(...) rc loss
RULE_EVAL_SUBSHELL = re.compile(r"\beval\s+\$\(")

# Returncode reference used to clear Rule 5 false positives
RETURNCODE_REF = re.compile(r"\breturncode\b")


def _allowlisted(line: str) -> bool:
    return bool(ALLOWLIST_SUFFIX.search(line))


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return list of (lineno, rule_id, line_text) violations."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    lines = text.splitlines()
    violations: list[tuple[int, str, str]] = []
    is_python = path.suffix == ".py"

    for i, raw in enumerate(lines):
        lineno = i + 1
        stripped = raw.rstrip("\n")

        if _allowlisted(stripped):
            continue

        # Skip pure comment lines — they can't be live code violations.
        # Python: lines whose first non-whitespace char is '#'.
        # Shell: same convention.
        if stripped.lstrip().startswith("#"):
            continue

        # Rule 1 / 2 (shell)
        if RULE_PIPE_TAIL_HEAD.search(stripped):
            violations.append((lineno, "R1/R2-pipe-tail-head-rc-clobber", stripped.strip()))
            continue

        # Rule 3 (shell) — pipeline + echo $? without pipefail on same line
        if not is_python and RULE_PIPE_ECHO_RC.search(stripped):
            if "pipefail" not in stripped and "PIPESTATUS" not in stripped:
                violations.append((lineno, "R3-pipeline-rc-clobber", stripped.strip()))
                continue

        # Rule 4 — || true
        if RULE_OR_TRUE.search(stripped):
            violations.append((lineno, "R4-or-true-silences-failure", stripped.strip()))
            continue

        # Rule 5 (Python) — check=False without returncode within 10 lines after
        if is_python and RULE_CHECK_FALSE.search(stripped):
            window = "\n".join(lines[i : i + 11])
            if not RETURNCODE_REF.search(window):
                violations.append((lineno, "R5-check-false-no-rc-assert", stripped.strip()))
                continue

        # Rule 6 (shell) — eval $(...)
        if not is_python and RULE_EVAL_SUBSHELL.search(stripped):
            violations.append((lineno, "R6-eval-subshell-rc-loss", stripped.strip()))

    return violations


def _collect_files() -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    this_file = Path(__file__).resolve()
    for pattern in SCAN_GLOBS:
        for p in sorted(REPO.glob(pattern)):
            resolved = p.resolve()
            if resolved == this_file:
                # Exclude this linter from scanning itself — its self-test
                # strings intentionally contain forbidden patterns.
                continue
            if resolved not in seen and resolved.is_file():
                seen.add(resolved)
                files.append(p)
    return files


def run_lint(files: list[Path]) -> list[tuple[Path, int, str, str]]:
    """Return list of (file, lineno, rule_id, line_text)."""
    results = []
    for f in files:
        for lineno, rule, line in _scan_file(f):
            results.append((f, lineno, rule, line))
    return results


def _format_table(violations: list[tuple[Path, int, str, str]]) -> str:
    rows = []
    for f, lineno, rule, line in violations:
        rel = f.relative_to(REPO) if f.is_absolute() else f
        snippet = line[:80] + ("..." if len(line) > 80 else "")
        rows.append(f"  {rel}:{lineno}  [{rule}]  {snippet!r}")
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Self-test: verify lint catches each rule in a temp dir
# ---------------------------------------------------------------------------

def _self_test() -> None:
    """Raise AssertionError if lint fails to catch a known bad snippet."""

    cases: list[tuple[str, str, bool]] = [
        # (label, source_text, expect_violation)
        (
            "R1-pipe-tail-rc",
            "out=$(cmd 2>&1 | tail -n 10); echo $?\n",
            True,
        ),
        (
            "R1-pipe-head-rc",
            "out=$(cmd 2>&1 | head -n 5); echo $?\n",
            True,
        ),
        (
            "R4-or-true",
            "risky_cmd || true\n",
            True,
        ),
        (
            "R4-or-true-allowed",
            "risky_cmd || true  # smoke-contract: allow cleanup step\n",
            False,
        ),
        (
            "R5-check-false-no-rc",
            "subprocess.run(['cmd'], check=False)\n",
            True,
        ),
        (
            "R5-check-false-with-rc",
            "result = subprocess.run(['cmd'], check=False)\nassert result.returncode == 0\n",
            False,
        ),
        (
            "R6-eval-subshell",
            "eval $(some-generator)\n",
            True,
        ),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for label, source, expect_violation in cases:
            suffix = ".py" if "subprocess" in source else ".sh"
            fp = tmp / f"fake_{label}{suffix}"
            fp.write_text(source, encoding="utf-8")
            violations = _scan_file(fp)
            got_violation = len(violations) > 0
            if got_violation != expect_violation:
                raise AssertionError(
                    f"Self-test {label!r}: expected violation={expect_violation}, "
                    f"got violations={violations!r}"
                )


# ---------------------------------------------------------------------------
# Pytest entry points (so pytest discovers this file as a test module too)
# ---------------------------------------------------------------------------

def test_smoke_contract_self_test() -> None:
    """pytest: lint self-test passes for all rule samples."""
    _self_test()


def test_smoke_contract_corpus_clean() -> None:
    """pytest: no violations in the test corpus."""
    files = _collect_files()
    violations = run_lint(files)
    if violations:
        table = _format_table(violations)
        raise AssertionError(
            f"Smoke contract violations found ({len(violations)}):\n{table}"
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    _self_test()

    files = _collect_files()
    violations = run_lint(files)

    if not violations:
        print(f"smoke-contract: OK ({len(files)} files scanned, 0 violations)")
        return 0

    print(f"smoke-contract: FAIL — {len(violations)} violation(s) found:\n")
    print(_format_table(violations))
    print(
        textwrap.dedent("""
        Fix each violation or add a trailing comment to opt out:
          # smoke-contract: allow <reason>
        See tests/SMOKE_CONTRACT.md for details.
        """).rstrip()
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
