#!/usr/bin/env python3
"""Tests for harness recon CLI command and recon.py module (M9-3 / issue #31)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS = REPO_ROOT / "scripts" / "harness.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.recon import (  # noqa: E402
    detect_tech_stack,
    render_tech_stack_section,
    build_dir_tree,
    render_dir_tree_section,
    find_existing_docs,
    render_docs_section,
    build_recon_doc,
    compute_unified_diff,
)


def _make_fixture(**files: str) -> Path:
    """Create a temp dir with the given file tree (relative path → content)."""
    tmp = Path(tempfile.mkdtemp(prefix="harness-recon-"))
    for rel, content in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp


class TestDetectTechStack(unittest.TestCase):
    """Unit tests for detect_tech_stack()."""

    def test_python_pyproject(self) -> None:
        root = _make_fixture(**{"pyproject.toml": "[project]\nname='x'"})
        stack = detect_tech_stack(root)
        self.assertIn("Python", stack["languages"])

    def test_python_requirements(self) -> None:
        root = _make_fixture(**{"requirements.txt": "pytest\n"})
        stack = detect_tech_stack(root)
        self.assertIn("Python", stack["languages"])

    def test_node_package_json(self) -> None:
        root = _make_fixture(**{"package.json": '{"name":"x"}'})
        stack = detect_tech_stack(root)
        self.assertIn("Node", stack["languages"])

    def test_rust_cargo(self) -> None:
        root = _make_fixture(**{"Cargo.toml": '[package]\nname="x"'})
        stack = detect_tech_stack(root)
        self.assertIn("Rust", stack["languages"])

    def test_go_mod(self) -> None:
        root = _make_fixture(**{"go.mod": "module example.com/x\n"})
        stack = detect_tech_stack(root)
        self.assertIn("Go", stack["languages"])

    def test_no_stack(self) -> None:
        root = _make_fixture(**{"README.md": "hello"})
        stack = detect_tech_stack(root)
        self.assertEqual(stack["languages"], [])

    def test_pytest_runner(self) -> None:
        root = _make_fixture(**{"pyproject.toml": "[project]", "tests/__init__.py": ""})
        stack = detect_tech_stack(root)
        self.assertIn("pytest", stack["test_runners"])

    def test_github_actions_ci(self) -> None:
        root = _make_fixture(**{".github/workflows/ci.yml": "on: push"})
        stack = detect_tech_stack(root)
        self.assertIn("GitHub Actions", stack["ci"])

    def test_multiple_languages(self) -> None:
        root = _make_fixture(**{
            "pyproject.toml": "[project]",
            "package.json": '{"name":"y"}',
        })
        stack = detect_tech_stack(root)
        self.assertIn("Python", stack["languages"])
        self.assertIn("Node", stack["languages"])


class TestBuildDirTree(unittest.TestCase):
    """Unit tests for build_dir_tree()."""

    def test_basic_tree(self) -> None:
        root = _make_fixture(**{
            "src/__init__.py": "",
            "docs/README.md": "",
            "tests/test_foo.py": "",
        })
        tree = build_dir_tree(root)
        rel_dirs = [str(d.relative_to(root)) for d, _ in tree]
        self.assertIn("src", rel_dirs)
        self.assertIn("docs", rel_dirs)
        self.assertIn("tests", rel_dirs)

    def test_excludes_git(self) -> None:
        root = _make_fixture(**{".git/HEAD": "ref: refs/heads/main"})
        tree = build_dir_tree(root)
        rel_dirs = [str(d.relative_to(root)) for d, _ in tree]
        self.assertNotIn(".git", rel_dirs)

    def test_excludes_node_modules(self) -> None:
        root = _make_fixture(**{"node_modules/pkg/index.js": ""})
        tree = build_dir_tree(root)
        rel_dirs = [str(d.relative_to(root)) for d, _ in tree]
        self.assertNotIn("node_modules", rel_dirs)

    def test_scope_limits_to_subdir(self) -> None:
        root = _make_fixture(**{
            "src/core/__init__.py": "",
            "tests/unit/__init__.py": "",
        })
        tree = build_dir_tree(root, scope=["src"])
        rel_dirs = [str(d.relative_to(root)) for d, _ in tree]
        self.assertIn("src", rel_dirs)
        # tests should not appear since scope is limited to src
        self.assertNotIn("tests", rel_dirs)

    def test_depth_2_subdir_included(self) -> None:
        root = _make_fixture(**{
            "src/models/__init__.py": "",
            "src/views/__init__.py": "",
        })
        tree = build_dir_tree(root)
        rel_dirs = [str(d.relative_to(root)) for d, _ in tree]
        self.assertIn("src/models", rel_dirs)
        self.assertIn("src/views", rel_dirs)


class TestFindExistingDocs(unittest.TestCase):
    """Unit tests for find_existing_docs()."""

    def test_finds_readme(self) -> None:
        root = _make_fixture(**{"README.md": "# Project"})
        docs = find_existing_docs(root)
        self.assertIn(Path("README.md"), docs)

    def test_finds_docs_dir(self) -> None:
        root = _make_fixture(**{
            "docs/overview.md": "# Overview",
            "docs/adr/0001-foo.md": "# ADR",
        })
        docs = find_existing_docs(root)
        paths = [str(d) for d in docs]
        self.assertTrue(any("overview.md" in p for p in paths))
        self.assertTrue(any("0001-foo.md" in p for p in paths))

    def test_no_docs(self) -> None:
        root = _make_fixture(**{"src/__init__.py": ""})
        docs = find_existing_docs(root)
        self.assertEqual(docs, [])


class TestBuildReconDoc(unittest.TestCase):
    """Integration tests for build_recon_doc()."""

    TEMPLATE = (
        "# Codebase Recon\n\n"
        "## 1. One-liner — what is this project?\n"
        "<!-- User or agent: 2-3 sentences -->\n\n"
        "## 2. Tech stack\n"
        "<!-- Auto-detected -->\n\n"
        "## 3. Top-level structure (depth 2)\n"
        "<!-- Tree -->\n\n"
        "## 4. Existing docs found\n"
        "<!-- Paths -->\n\n"
        "## 5. Open questions\n"
        "<!-- Agent-flagged unknowns -->\n"
    )

    def test_python_in_section_2(self) -> None:
        root = _make_fixture(**{"pyproject.toml": "[project]"})
        doc = build_recon_doc(root, template_text=self.TEMPLATE, today="2026-01-01")
        self.assertIn("Python", doc)

    def test_node_in_section_2(self) -> None:
        root = _make_fixture(**{"package.json": '{"name":"x"}'})
        doc = build_recon_doc(root, template_text=self.TEMPLATE, today="2026-01-01")
        self.assertIn("Node", doc)

    def test_auto_detected_comment_present(self) -> None:
        root = _make_fixture(**{"pyproject.toml": "[project]"})
        doc = build_recon_doc(root, template_text=self.TEMPLATE, today="2026-01-01")
        self.assertIn("auto-detected on 2026-01-01", doc)

    def test_sections_1_and_5_placeholders_when_empty(self) -> None:
        root = _make_fixture(**{"pyproject.toml": "[project]"})
        doc = build_recon_doc(root, template_text=self.TEMPLATE, today="2026-01-01")
        self.assertIn("## 1.", doc)
        self.assertIn("## 5.", doc)
        # Placeholder comment inserted for empty user sections
        self.assertIn("<!--", doc)

    def test_idempotent_user_content_preserved(self) -> None:
        """Second run preserves user edits in sections 1 and 5."""
        root = _make_fixture(**{"pyproject.toml": "[project]"})
        first = build_recon_doc(root, template_text=self.TEMPLATE, today="2026-01-01")

        # Simulate user editing sections 1 and 5
        user_edit = first.replace(
            "<!-- User or agent: 2-3 sentences -->",
            "This project does X, Y, and Z.",
        ).replace(
            "<!-- Agent-flagged unknowns for user to answer -->",
            "- Why is X done this way?",
        )

        second = build_recon_doc(
            root,
            existing_text=user_edit,
            template_text=self.TEMPLATE,
            today="2026-01-02",
        )
        self.assertIn("This project does X, Y, and Z.", second)
        self.assertIn("- Why is X done this way?", second)

    def test_auto_sections_updated_on_rerun(self) -> None:
        """Second run updates sections 2-4 even when sections 1/5 have user content."""
        root = _make_fixture(**{"pyproject.toml": "[project]"})
        first = build_recon_doc(root, template_text=self.TEMPLATE, today="2026-01-01")

        # Add package.json to the fixture between runs
        (root / "package.json").write_text('{"name":"x"}', encoding="utf-8")

        second = build_recon_doc(
            root,
            existing_text=first,
            template_text=self.TEMPLATE,
            today="2026-01-02",
        )
        self.assertIn("Node", second)
        self.assertIn("2026-01-02", second)

    def test_scope_limits_tree(self) -> None:
        root = _make_fixture(**{
            "src/core/__init__.py": "",
            "tests/unit/__init__.py": "",
        })
        doc = build_recon_doc(
            root, scope=["src"], template_text=self.TEMPLATE, today="2026-01-01"
        )
        self.assertIn("src", doc)
        # tests dir should not appear since scope is limited
        self.assertNotIn("`tests/`", doc)


class TestComputeUnifiedDiff(unittest.TestCase):
    def test_diff_shows_change(self) -> None:
        diff = compute_unified_diff("old line\n", "new line\n")
        self.assertIn("-old line", diff)
        self.assertIn("+new line", diff)

    def test_no_diff_for_identical(self) -> None:
        diff = compute_unified_diff("same\n", "same\n")
        self.assertEqual(diff, "")


class TestReconCLI(unittest.TestCase):
    """End-to-end CLI tests for `harness recon`."""

    def _run_harness(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HARNESS), *args],
            cwd=cwd or Path.cwd(),
            capture_output=True,
            text=True,
        )

    def _make_target(self, **files: str) -> Path:
        return _make_fixture(**files)

    def test_creates_file_when_absent(self) -> None:
        root = self._make_target(**{"pyproject.toml": "[project]"})
        result = self._run_harness("recon", "--target", str(root))
        self.assertEqual(result.returncode, 0, result.stderr)
        recon = root / ".planning" / "codebase-recon.md"
        self.assertTrue(recon.exists(), "codebase-recon.md should be created")
        content = recon.read_text(encoding="utf-8")
        self.assertIn("Python", content)

    def test_dry_run_does_not_write(self) -> None:
        root = self._make_target(**{"package.json": '{"name":"x"}'})
        result = self._run_harness("recon", "--target", str(root), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        # Dry run should print a diff (or no-change message), not write the file
        recon = root / ".planning" / "codebase-recon.md"
        self.assertFalse(recon.exists(), "dry-run must not create the file")

    def test_dry_run_prints_diff(self) -> None:
        root = self._make_target(**{"package.json": '{"name":"x"}'})
        result = self._run_harness("recon", "--target", str(root), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        # stdout should contain something (diff or no-change marker)
        self.assertTrue(result.stdout.strip(), "dry-run should produce output")

    def test_node_detected(self) -> None:
        root = self._make_target(**{"package.json": '{"name":"x"}'})
        result = self._run_harness("recon", "--target", str(root))
        self.assertEqual(result.returncode, 0, result.stderr)
        content = (root / ".planning" / "codebase-recon.md").read_text(encoding="utf-8")
        self.assertIn("Node", content)

    def test_second_run_preserves_user_edits(self) -> None:
        root = self._make_target(**{"pyproject.toml": "[project]"})
        # First run
        self._run_harness("recon", "--target", str(root))
        recon = root / ".planning" / "codebase-recon.md"
        # Simulate user editing section 1
        old_content = recon.read_text(encoding="utf-8")
        new_content = old_content.replace(
            "<!-- User or agent: 2-3 sentences -->",
            "This project is a low-reasoning agent harness.",
        )
        recon.write_text(new_content, encoding="utf-8")
        # Second run
        self._run_harness("recon", "--target", str(root))
        after = recon.read_text(encoding="utf-8")
        self.assertIn("This project is a low-reasoning agent harness.", after)

    def test_scope_flag_limits_tree(self) -> None:
        root = self._make_target(**{
            "src/core/__init__.py": "",
            "tests/unit/__init__.py": "",
        })
        result = self._run_harness(
            "recon", "--target", str(root), "--scope", "src"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        content = (root / ".planning" / "codebase-recon.md").read_text(encoding="utf-8")
        self.assertIn("src", content)
        self.assertNotIn("`tests/`", content)

    def test_help_text(self) -> None:
        result = self._run_harness("recon", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("codebase-recon.md", result.stdout)
        self.assertIn("--dry-run", result.stdout)
        self.assertIn("--target", result.stdout)
        self.assertIn("--scope", result.stdout)


if __name__ == "__main__":
    unittest.main()
