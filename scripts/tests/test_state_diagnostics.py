#!/usr/bin/env python3
"""Tests for scripts/lib/state_diagnostics.py (T1-M malformed-state helper).

Plan: .planning/phases/02b-hardening/plans/02b-09-T1-M-PLAN.md
Contract: .planning/phases/02b-hardening/CONTRACT-PIN.md §1, §3, §4, §5.1, §7
ADR: docs/adr/2026-05-16-hardening-bundle.md (ADR-005, ADR-003a Artifact 1)
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import state_diagnostics  # noqa: E402
from lib.exitcodes import EXIT_UNPARSEABLE_JSON  # noqa: E402


# ---------------------------------------------------------------------------
# load_state_json: happy + empty + truncated (plan tests 1-3)
# ---------------------------------------------------------------------------


class TestLoadStateJsonHappyPath(unittest.TestCase):
    def test_returns_dict_on_valid_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            payload = {"phase": "discuss", "approved": False}
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = state_diagnostics.load_state_json(path)
            self.assertEqual(result, payload)


class TestLoadStateJsonTruncated(unittest.TestCase):
    def test_truncated_raises_systemexit_5_with_file_line_col(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            # Truncated JSON: open string, no close brace.
            path.write_text('{"phase": "exec', encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.load_state_json(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            self.assertIn(str(path), err)
            # JSONDecodeError supplies line + col; the diagnostic surfaces them.
            self.assertRegex(err, r"line\s+\d+")
            self.assertRegex(err, r"col\s*\d+|column\s*\d+")
            # Remediation hint sentence per ADR-003a / ADR-005.
            self.assertIn("fix the JSON", err)


class TestLoadStateJsonEmptyFile(unittest.TestCase):
    def test_empty_file_raises_systemexit_5(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            path.write_text("", encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.load_state_json(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            self.assertIn(str(path), err)
            self.assertIn("empty file", err.lower())


# ---------------------------------------------------------------------------
# Remediation hint precedence: sidecar > backup-listing > default
# (plan tests 4-6)
# ---------------------------------------------------------------------------


def _write_broken_state(repo: Path) -> Path:
    state_dir = repo / ".scratch"
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "phase-state.json"
    path.write_text('{"phase":', encoding="utf-8")  # truncated
    return path


class TestRemediationHints(unittest.TestCase):
    def test_diagnostic_lists_backups_when_present_and_no_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            backups = repo / ".harness" / "backups"
            backups.mkdir(parents=True)
            for stamp in (
                "20260514T100000000000000Z.111.bak",
                "20260515T100000000000000Z.222.bak",
                "20260516T100000000000000Z.333.bak",
            ):
                (backups / f"phase-state.json.pre-repair.{stamp}").write_text("{}", encoding="utf-8")
            path = _write_broken_state(repo)
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit):
                    state_diagnostics.load_state_json(path)
            err = buf.getvalue()
            # Newest by lexical sort is the 20260516 one.
            self.assertIn(
                "phase-state.json.pre-repair.20260516T100000000000000Z.333.bak",
                err,
            )
            self.assertIn("restore from .harness/backups/", err)

    def test_diagnostic_omits_resume_and_backups_when_neither_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".scratch").mkdir()
            (repo / ".harness").mkdir()
            path = _write_broken_state(repo)
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit):
                    state_diagnostics.load_state_json(path)
            err = buf.getvalue()
            self.assertNotIn("restore from .harness/backups/", err)
            self.assertIn("fix the JSON", err)


# ---------------------------------------------------------------------------
# parse_state_markdown: duplicate slug + unbalanced + invalid slug
# (plan tests 7-9)
# ---------------------------------------------------------------------------


class TestParseStateMarkdownDuplicateSlug(unittest.TestCase):
    def test_duplicate_slug_raises_systemexit_5_with_two_line_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "STATE.md"
            text = (
                "# Title\n"
                "\n"
                "<!-- HARNESS:BEGIN managed:foo v1 -->\n"
                "first\n"
                "<!-- HARNESS:END managed:foo -->\n"
                "\n"
                "intermediate\n"
                "\n"
                "<!-- HARNESS:BEGIN managed:foo v1 -->\n"
                "second\n"
                "<!-- HARNESS:END managed:foo -->\n"
            )
            path.write_text(text, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.parse_state_markdown(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            self.assertIn(str(path), err)
            self.assertIn("foo", err)
            # Both BEGIN line numbers must appear: line 3 and line 9.
            self.assertIn("3", err)
            self.assertIn("9", err)


class TestParseStateMarkdownUnbalanced(unittest.TestCase):
    def test_unbalanced_markers_raises_systemexit_5(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "STATE.md"
            text = (
                "# Title\n"
                "\n"
                "<!-- HARNESS:BEGIN managed:foo v1 -->\n"
                "payload without close\n"
            )
            path.write_text(text, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.parse_state_markdown(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            self.assertIn(str(path), err)
            self.assertIn("3", err)  # BEGIN line number
            self.assertIn("unbalanced", err.lower())


class TestParseStateMarkdownInvalidSlug(unittest.TestCase):
    def test_invalid_slug_raises_systemexit_5(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "STATE.md"
            text = (
                "<!-- HARNESS:BEGIN managed:Foo_BAD v1 -->\n"
                "x\n"
                "<!-- HARNESS:END managed:Foo_BAD -->\n"
            )
            path.write_text(text, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.parse_state_markdown(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            self.assertIn(str(path), err)
            self.assertIn("Foo_BAD", err)


# ---------------------------------------------------------------------------
# Frontmatter delimiter validation (plan tests 10-11)
# ---------------------------------------------------------------------------


class TestParseStateMarkdownFrontmatter(unittest.TestCase):
    def test_unclosed_frontmatter_raises_systemexit_5(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "STATE.md"
            text = (
                "---\n"
                "phase: 1\n"
                "progress:\n"
                "  total_phases: 3\n"
                "# (no closing --- before body)\n"
                "\n"
                "## Section\n"
            )
            path.write_text(text, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.parse_state_markdown(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            self.assertIn(str(path), err)
            # Start line of the frontmatter is 1.
            self.assertIn("line 1", err)
            self.assertIn("closing", err.lower())
            self.assertIn("---", err)

    def test_valid_frontmatter_then_invalid_body_partial_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "STATE.md"
            text = (
                "---\n"
                "phase: 1\n"
                "---\n"
                "\n"
                "# Title\n"
                "\n"
                "<!-- HARNESS:BEGIN managed:foo v1 -->\n"
                "first\n"
                "<!-- HARNESS:END managed:foo -->\n"
                "\n"
                "<!-- HARNESS:BEGIN managed:foo v1 -->\n"
                "dup\n"
                "<!-- HARNESS:END managed:foo -->\n"
            )
            path.write_text(text, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.parse_state_markdown(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            # Body-section failure must cite the duplicate slug (one of the
            # duplicate BEGIN line numbers).
            self.assertIn("foo", err)
            self.assertIn("7", err)  # first BEGIN
            self.assertIn("11", err)  # second BEGIN
            # Frontmatter ack: the diagnostic must NOT discard the fact that
            # frontmatter parsed — operator should see context that the
            # failure is in the body, not the header.
            self.assertIn("body", err.lower())


# ---------------------------------------------------------------------------
# Fuzz sweep + diagnostic single-line constraint + grep gate (plan tests 12-16)
# ---------------------------------------------------------------------------


class TestStateReadRefusesSymlink(unittest.TestCase):
    """T1-M-SecM1: state readers must refuse to traverse symlinks."""

    def test_load_state_json_refuses_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            real = tmp / "real.json"
            real.write_text('{"phase": "discuss"}', encoding="utf-8")
            link = tmp / "phase-state.json"
            link.symlink_to(real)
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.load_state_json(link)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            self.assertIn("symlink not permitted", buf.getvalue())
            self.assertIn(str(link), buf.getvalue())

    def test_parse_state_markdown_refuses_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            real = tmp / "real.md"
            real.write_text("# title\n", encoding="utf-8")
            link = tmp / "STATE.md"
            link.symlink_to(real)
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.parse_state_markdown(link)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            self.assertIn("symlink not permitted", buf.getvalue())
            self.assertIn(str(link), buf.getvalue())


class TestWorkflowStaticChecksMigrated(unittest.TestCase):
    """T1-M-C3: workflow_static_checks.installed_scope_issues must route
    through state_diagnostics.load_state_json so malformed
    installed-manifest.json exits 5 with the structured diagnostic."""

    def test_installed_scope_issues_exits_5_on_malformed_manifest(self) -> None:
        from lib import workflow_static_checks
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "installed-manifest.json"
            path.write_text('{"adapters":', encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    workflow_static_checks.installed_scope_issues(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            self.assertIn("is unparseable", buf.getvalue())
            self.assertIn(str(path), buf.getvalue())


class TestStateReadRefusesOversized(unittest.TestCase):
    """T1-M-SecM2: refuse to read state files larger than 8 MiB."""

    _CAP = 8 * 1024 * 1024

    def test_load_state_json_refuses_oversized(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            # Sparse file just over the 8 MiB cap.
            with open(path, "wb") as fh:
                fh.seek(self._CAP + 1)
                fh.write(b"\0")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.load_state_json(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            self.assertIn("file too large", buf.getvalue())
            self.assertIn(str(path), buf.getvalue())

    def test_parse_state_markdown_refuses_oversized(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "STATE.md"
            with open(path, "wb") as fh:
                fh.seek(self._CAP + 1)
                fh.write(b"\0")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.parse_state_markdown(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            self.assertIn("file too large", buf.getvalue())


class TestNoUncaughtExceptionFuzz(unittest.TestCase):
    """Spec §7: 'diagnostic exit not traceback' sweep."""

    def test_no_uncaught_exception_on_any_malformed_input(self) -> None:
        # Note: "null", "[]" are VALID JSON; load_state_json returns them and
        # the caller is responsible for downstream type checks. We test only
        # payloads that are definitionally unparseable.
        malformed_payloads = (
            b"",
            b"\x00",
            b"{",
            b"]",
            b'{"phase":}',
            b"\xff\xfe",  # invalid UTF-8 BOM
            b"a" * (1 << 20),  # 1 MiB of "a"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            for payload in malformed_payloads:
                path.write_bytes(payload)
                buf = io.StringIO()
                with redirect_stderr(buf):
                    # The contract: ONLY SystemExit(5) is acceptable; nothing
                    # else may escape (no JSONDecodeError, no ValueError, no
                    # KeyError, no UnicodeDecodeError, etc.).
                    raised: BaseException | None = None
                    try:
                        state_diagnostics.load_state_json(path)
                    except SystemExit as exc:
                        raised = exc
                    except BaseException as exc:  # noqa: BLE001
                        self.fail(
                            f"payload {payload[:32]!r} raised "
                            f"{exc.__class__.__name__}: {exc}"
                        )
                    self.assertIsNotNone(raised, f"payload {payload[:32]!r} did not exit")
                    assert raised is not None  # for mypy
                    self.assertEqual(
                        raised.code,
                        EXIT_UNPARSEABLE_JSON,
                        f"payload {payload[:32]!r} exited with {raised.code}",
                    )


class TestDiagnosticFormatConstraint(unittest.TestCase):
    """Low-reasoning operator fit: diagnostics must fit on one line ≤200 chars."""

    def test_diagnostic_format_is_single_line_under_200_chars(self) -> None:
        cases = (
            b"",
            b'{"phase": "exec',
            b"]",
            b"\x00\x01",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            for payload in cases:
                path.write_bytes(payload)
                buf = io.StringIO()
                with redirect_stderr(buf):
                    try:
                        state_diagnostics.load_state_json(path)
                    except SystemExit:
                        pass
                err = buf.getvalue()
                if not err:
                    continue  # valid payload — no diagnostic to constrain
                # Allow continuation lines with two-space "hint:" indent;
                # the FIRST line must be ≤200 chars; any continuation ≤120.
                lines = err.rstrip("\n").split("\n")
                self.assertLessEqual(
                    len(lines[0]),
                    200,
                    f"diagnostic first line >200 chars: {lines[0]!r}",
                )
                for cont in lines[1:]:
                    self.assertLessEqual(
                        len(cont),
                        120,
                        f"continuation line >120 chars: {cont!r}",
                    )


class TestNoBareJsonLoadsOnStatePaths(unittest.TestCase):
    """Grep gate (AST-based): no bare json.loads on managed-state literals
    outside the sanctioned helper or the explicitly allowlisted doctor.

    Rationale (T1-M-C1):
      - state_diagnostics.py is the sole sanctioned call site.
      - doctor.py performs read-only diagnostics; it must continue producing
        findings (with try/except handlers) rather than exiting, so its
        bare json.loads call sites on managed-state paths are explicitly
        allowlisted by file path.
      - All OTHER modules must route through load_state_json.

    Algorithm (T1-M-M1): walks each .py file's AST, finds every
    json.loads(...) Call, and resolves its first argument via a one-pass
    intra-function constant assignment map. If the resolved string literal
    matches a known managed-state path, that call is a violation unless
    its file is on the allowlist.
    """

    _STATE_LITERALS = (
        "phase-state.json",
        "installed-manifest.json",
    )
    _ALLOWLISTED_FILES = (
        # state_diagnostics.py is the sanctioned reader; skipped upstream.
        "doctor.py",  # read-only diagnostics; intentionally tolerant of
                       # malformed JSON to produce findings rather than exit.
        "check.py",    # _is_trivial_phase_state + check_drift: read-only
                       # warnings on harness check that MUST NEVER exit.
                       # Wrapped in try/except, swallow on failure.
    )

    @staticmethod
    def _resolve_arg(node, const_map) -> str | None:
        """Resolve `node` to a string-literal arg, best effort."""
        import ast
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return const_map.get(node.id)
        # Path("...").read_text(...): the literal lives in the surrounding
        # statement; look for a sibling literal in the same Call's parent.
        # For our scope this case is handled by the line-window fallback.
        return None

    @classmethod
    def _scan_file(cls, py: Path) -> list[str]:
        """Walk AST, return violation strings for every json.loads(...) call
        whose enclosing function body contains a managed-state literal.

        Per T1-M-M1: this replaces the prior ±3 line window heuristic with
        function-scope literal lookup. Best-effort: we don't try to do
        true data-flow analysis; we just check whether the call appears in
        a function whose body mentions one of the managed-state literals.
        """
        import ast
        text = py.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []

        def is_json_loads_call(node: ast.AST) -> bool:
            if not isinstance(node, ast.Call):
                return False
            fn = node.func
            return (
                isinstance(fn, ast.Attribute)
                and fn.attr == "loads"
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "json"
            )

        def docstring_nodes(scope: ast.AST) -> set[int]:
            """Return id() of Constant nodes that are module/function/class
            docstrings (the first statement when it's a bare string Expr)."""
            ids: set[int] = set()
            for s in [scope] + [n for n in ast.walk(scope) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module))]:
                body = getattr(s, "body", None)
                if not body:
                    continue
                first = body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    ids.add(id(first.value))
            return ids

        def scope_string_literals(scope: ast.AST, doc_ids: set[int]) -> list[str]:
            out: list[str] = []
            for sub in ast.walk(scope):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and id(sub) not in doc_ids:
                    out.append(sub.value)
            return out

        violations: list[str] = []
        # Function-scope only (not module): avoids false positives where one
        # function's stdin json.loads inherits a sibling function's state
        # literal via shared module scope.
        functions = [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        doc_ids = docstring_nodes(tree)
        seen: set[int] = set()
        for func in functions:
            literals = scope_string_literals(func, doc_ids)
            hit_literal = next(
                (s for s in literals if any(lit in s for lit in cls._STATE_LITERALS)),
                None,
            )
            if hit_literal is None:
                continue
            for node in ast.walk(func):
                if not is_json_loads_call(node):
                    continue
                if node.lineno in seen:
                    continue
                seen.add(node.lineno)
                violations.append(
                    f"{py.name}:{node.lineno}: json.loads(...) in {func.name}() with literal {hit_literal!r}"
                )
        return sorted(set(violations))

    def test_grep_gate_no_bare_json_loads_on_state_paths_outside_helper(self) -> None:
        lib_dir = Path(__file__).resolve().parents[1] / "lib"
        violations: list[str] = []
        for py in sorted(lib_dir.glob("*.py")):
            if py.name == "state_diagnostics.py":
                continue
            if py.name in self._ALLOWLISTED_FILES:
                continue
            violations.extend(self._scan_file(py))
        self.assertEqual(
            violations,
            [],
            "Bare json.loads on managed-state paths outside state_diagnostics.py "
            "(and the doctor.py allowlist):\n" + "\n".join(violations),
        )

    def test_grep_gate_catches_unmigrated_site_outside_doctor(self) -> None:
        """Sanity: the AST scanner DOES flag a synthetic violation
        in a non-doctor file. Uses a temp file written into the lib dir
        is overkill — instead we directly invoke _scan_file on a temp file
        with the offending pattern."""
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "fake_module.py"
            fake.write_text(
                "import json\n"
                "def f():\n"
                "    p = '.scratch/phase-state.json'\n"
                "    return json.loads(open(p).read())\n",
                encoding="utf-8",
            )
            hits = self._scan_file(fake)
            self.assertTrue(hits, "AST scanner failed to flag synthetic violation")
            self.assertTrue(any("phase-state.json" in h for h in hits), hits)

    def test_grep_gate_allows_doctor_diagnostic_pattern(self) -> None:
        """doctor.py contains intentional bare json.loads on
        phase-state.json wrapped in try/except — those must NOT be
        flagged because doctor.py is on the allowlist."""
        lib_dir = Path(__file__).resolve().parents[1] / "lib"
        doctor_py = lib_dir / "doctor.py"
        self.assertTrue(doctor_py.exists())
        # The AST scanner SHOULD find violations in doctor.py (proving
        # the scanner sees them); the test_grep_gate just excludes the
        # file via _ALLOWLISTED_FILES.
        hits = self._scan_file(doctor_py)
        # doctor.py reads phase-state.json bare in several try/except
        # blocks; assert the scanner saw at least one.
        self.assertTrue(
            any("phase-state.json" in h for h in hits),
            f"scanner missed doctor.py's bare json.loads sites: {hits}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
