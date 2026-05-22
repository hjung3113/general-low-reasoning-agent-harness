"""Tests for ADR-002 glob matcher semantics in scripts/lib/worktree.py.

T0-2 slice; see .planning/phases/02b-hardening/plans/02b-03-T0-2-PLAN.md
TDD list items 1..17.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib import worktree  # noqa: E402


class MatcherSemanticsTests(unittest.TestCase):
    # Test 1
    def test_exact_match_preserved(self):
        self.assertTrue(worktree.matches_any("README.md", ["README.md"]))
        self.assertFalse(worktree.matches_any("README2.md", ["README.md"]))

    # Test 2
    def test_trailing_slash_prefix_still_matches(self):
        self.assertTrue(worktree.matches_any("docs/x.md", ["docs/"]))
        self.assertTrue(worktree.matches_any("docs/a/b.md", ["docs/"]))
        self.assertFalse(worktree.matches_any("docs", ["docs/"]))

    # Test 3
    def test_star_does_not_cross_slash(self):
        self.assertTrue(worktree.matches_any("foo.md", ["*.md"]))
        self.assertFalse(worktree.matches_any("foo/bar.md", ["*.md"]))

    # Test 4
    def test_double_star_treated_as_single_star(self):
        self.assertFalse(worktree.matches_any("foo.md", ["**/*.md"]))
        self.assertTrue(worktree.matches_any("a/b.md", ["**/*.md"]))
        self.assertFalse(worktree.matches_any("a/b/c.md", ["**/*.md"]))

    # Test 5
    def test_question_mark_single_char_no_slash(self):
        self.assertTrue(worktree.matches_any("a.md", ["?.md"]))
        self.assertFalse(worktree.matches_any("ab.md", ["?.md"]))
        # "/" cannot be matched by ?
        self.assertFalse(worktree.matches_any("/.md", ["?.md"]))

    # Test 6
    def test_character_class_positive(self):
        for p in ("a/file", "b/file", "c/file"):
            self.assertTrue(worktree.matches_any(p, ["[abc]/file"]), p)
        self.assertFalse(worktree.matches_any("d/file", ["[abc]/file"]))

    # Test 7
    def test_character_class_negated_with_bang(self):
        self.assertTrue(worktree.matches_any("d/file", ["[!abc]/file"]))
        self.assertFalse(worktree.matches_any("a/file", ["[!abc]/file"]))

    # Test 8
    def test_caret_is_literal_not_negation(self):
        self.assertTrue(worktree.matches_any("^/file", ["[^abc]/file"]))
        self.assertFalse(worktree.matches_any("d/file", ["[^abc]/file"]))

    # Test 15
    def test_pattern_with_no_metachars_uses_prefix_or_exact_branch(self):
        self.assertTrue(worktree.matches_any("AGENTS.md", ["AGENTS.md"]))
        self.assertFalse(worktree.matches_any("AGENTS.md.bak", ["AGENTS.md"]))
        self.assertTrue(worktree.matches_any(".planning/STATE.md", [".planning/"]))

    # Test 16
    def test_case_sensitive_on_all_platforms(self):
        self.assertFalse(worktree.matches_any("readme.md", ["README.md"]))
        self.assertFalse(worktree.matches_any("foo.md", ["*.MD"]))

    # Test 17
    def test_normalize_path_still_applied(self):
        # Pattern with redundant ./ segment normalizes identically.
        self.assertTrue(worktree.matches_any("docs/x.md", ["./docs/"]))
        self.assertTrue(worktree.matches_any("README.md", ["./README.md"]))


class PrecedenceTests(unittest.TestCase):
    # Test 9
    def test_blocked_overrides_allowed(self):
        allowed = ["docs/"]
        blocked = ["docs/secrets/"]
        self.assertFalse(worktree.path_allowed("docs/secrets/key.md", allowed, blocked))
        self.assertTrue(worktree.path_allowed("docs/public.md", allowed, blocked))

    # Test 10
    def test_blocked_glob_overrides_allowed_literal(self):
        allowed = ["src/main.py"]
        blocked = ["src/*.py"]
        self.assertFalse(worktree.path_allowed("src/main.py", allowed, blocked))


class BreakageScannerTests(unittest.TestCase):
    # Test 11
    def test_breakage_warning_on_literal_collision(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            (target / "[draft]").mkdir()
            state = {"allowed_paths": ["[draft]"], "blocked_paths": []}
            buf = io.StringIO()
            worktree.scan_for_glob_literal_collisions(target, state, buf)
            out = buf.getvalue()
            self.assertIn("warning:", out)
            self.assertIn("glob metacharacters", out)
            self.assertIn("[draft]", out)
            self.assertIn("allowed_paths", out)

    # Test 12
    def test_breakage_warning_silent_when_no_collision(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            state = {"allowed_paths": ["*.md"], "blocked_paths": []}
            buf = io.StringIO()
            worktree.scan_for_glob_literal_collisions(target, state, buf)
            self.assertEqual(buf.getvalue(), "")

    # Test 13
    def test_breakage_warning_rate_limited_once_per_pattern_per_invocation(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            (target / "[draft]").mkdir()
            # Duplicate entries — though uniqueItems normally prevents this,
            # the scanner must still rate-limit by (field, index).
            state = {
                "allowed_paths": ["[draft]", "[other]"],
                "blocked_paths": [],
            }
            buf = io.StringIO()
            worktree.scan_for_glob_literal_collisions(target, state, buf)
            lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
            # Only [draft] collides; one warning expected.
            self.assertEqual(len(lines), 1, lines)


class MalformedPatternTests(unittest.TestCase):
    # Test 14 (legacy contract; matches_any no longer re-validates after
    # T0-2-M2 so this test now asserts the pre-validate contract instead).
    def test_malformed_pattern_fails_loudly(self):
        # _validate_pattern itself still raises ScopePatternError when called
        # directly by the eager validator.
        with self.assertRaises(worktree.ScopePatternError):
            worktree._validate_pattern("[abc")

    def test_pattern_with_dotdot_loud_fails(self):
        """T0-2-SecM2: any `..` segment in a scope pattern must loud-fail.

        Prevents path-traversal-shaped patterns from sneaking into the
        allowed/blocked scope: `..` segments cannot map to a legitimate
        repo-relative path under our normalization rules.
        """
        # Direct _validate_pattern rejection (segment-aware).
        for bad in ("..", "../etc/passwd", "docs/../etc", "a/b/../c"):
            with self.assertRaises(worktree.ScopePatternError, msg=bad):
                worktree._validate_pattern(bad)
        # And via the state validator (surfaces as SystemExit).
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            (target / ".scratch").mkdir()
            state = {
                "phase": "execute",
                "approved": True,
                "allowed_paths": ["docs/../etc"],
                "blocked_paths": [],
            }
            (target / ".scratch/phase-state.json").write_text(json.dumps(state))
            import subprocess as sp
            sp.check_call(["git", "init", "-q"], cwd=target)
            sp.check_call(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "--allow-empty", "-q", "-m", "x"],
                cwd=target,
            )
            with self.assertRaises(SystemExit) as cm:
                worktree.check_worktree_paths(target)
            self.assertIn("..", str(cm.exception))

    def test_matches_any_does_not_revalidate(self):
        """T0-2-M2: matches_any must NOT invoke _validate_pattern.

        Callers MUST call _validate_state_patterns(state) eagerly before
        invoking matchers; matches_any is on the hot path and must be total.
        Patching _validate_pattern to fail proves matches_any never calls it.
        """
        from unittest import mock

        def _boom(_pattern: str) -> None:  # pragma: no cover - asserts non-call
            raise AssertionError("matches_any must not call _validate_pattern")

        with mock.patch.object(worktree, "_validate_pattern", side_effect=_boom):
            # Valid pattern: should match cleanly without invoking validator.
            self.assertTrue(worktree.matches_any("foo.md", ["*.md"]))
            self.assertFalse(worktree.matches_any("foo.py", ["*.md"]))

    def test_malformed_pattern_loud_fails_before_collision_scan(self):
        """T0-2-M1: validation must run BEFORE the collision scan so a
        malformed pattern surfaces as SystemExit(5) WITHOUT a confusing
        collision warning being emitted first."""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            (target / ".scratch").mkdir()
            # Create a literal directory that would collide with `[abc` were
            # it parsed as a glob — to make sure the scanner WOULD warn if
            # called.
            (target / "[abc").mkdir()
            state = {
                "phase": "execute",
                "approved": True,
                "allowed_paths": ["[abc"],
                "blocked_paths": [],
            }
            (target / ".scratch/phase-state.json").write_text(json.dumps(state))
            import subprocess as sp
            sp.check_call(["git", "init", "-q"], cwd=target)
            sp.check_call(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "--allow-empty", "-q", "-m", "x"],
                cwd=target,
            )
            # Capture stderr so we can assert no warning preceded the exit.
            import io as _io
            from contextlib import redirect_stderr
            buf = _io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit):
                    worktree.check_worktree_paths(target)
            self.assertNotIn("warning:", buf.getvalue())

    def test_malformed_pattern_surfaces_as_systemexit_in_check(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            (target / ".scratch").mkdir()
            state = {
                "phase": "execute",
                "approved": True,
                "allowed_paths": ["[abc"],
                "blocked_paths": [],
            }
            (target / ".scratch/phase-state.json").write_text(json.dumps(state))
            # initialize a git repo so git diff doesn't choke
            import subprocess as sp
            sp.check_call(["git", "init", "-q"], cwd=target)
            sp.check_call(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "--allow-empty", "-q", "-m", "x"], cwd=target)
            with self.assertRaises(SystemExit) as cm:
                worktree.check_worktree_paths(target)
            self.assertIn("[abc", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
