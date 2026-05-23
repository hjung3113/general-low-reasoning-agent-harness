#!/usr/bin/env python3
"""Tests for harness recon CLI and recon.py module (M10 / issue #34)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS = REPO_ROOT / "scripts" / "harness.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.recon import (  # noqa: E402
    ALL_FILES,
    AUTO_FILES,
    AGENT_FILES,
    build_codebase_docs,
    build_dir_tree,
    compute_files_diff,
    detect_integrations,
    detect_tech_stack,
    has_integrations,
    load_skeleton_templates,
    parse_frontmatter,
    render_anchor_section,
    split_anchors,
)


def _make_fixture(**files: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="harness-recon-m10-"))
    for rel, content in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp


class TestTechStackBuckets(unittest.TestCase):
    def test_python_pyproject(self) -> None:
        root = _make_fixture(**{"pyproject.toml": "[project]\nname='x'"})
        stack = detect_tech_stack(root)
        self.assertIn("Python", stack["languages"])
        self.assertIn("Python", stack["runtime"])
        self.assertIn("pyproject.toml", stack["package_managers"])

    def test_node_package_json(self) -> None:
        root = _make_fixture(**{"package.json": '{"name":"x"}'})
        stack = detect_tech_stack(root)
        self.assertIn("JavaScript/TypeScript", stack["languages"])
        self.assertIn("Node.js", stack["runtime"])

    def test_node_test_runners(self) -> None:
        root = _make_fixture(**{"package.json": '{"name":"x","scripts":{"test":"vitest"}}'})
        stack = detect_tech_stack(root)
        self.assertIn("vitest", stack["test_runners"])

    def test_pyproject_ruff_detection(self) -> None:
        root = _make_fixture(**{"pyproject.toml": "[tool.ruff]\nline-length = 100"})
        stack = detect_tech_stack(root)
        self.assertIn("ruff", stack["lint"])

    def test_github_actions_ci(self) -> None:
        root = _make_fixture(**{".github/workflows/ci.yml": "on: push"})
        stack = detect_tech_stack(root)
        self.assertIn("GitHub Actions", stack["ci"])


class TestIntegrations(unittest.TestCase):
    def test_docker_compose_detected(self) -> None:
        root = _make_fixture(**{"docker-compose.yml": "version: '3'"})
        ints = detect_integrations(root)
        self.assertIn("docker-compose", ints["local_dependencies"])
        self.assertTrue(has_integrations(ints))

    def test_pg_dependency_detected(self) -> None:
        root = _make_fixture(**{"package.json": '{"name":"x","dependencies":{"pg":"^8"}}'})
        ints = detect_integrations(root)
        self.assertIn("PostgreSQL (pg)", ints["datastores"])

    def test_empty_when_no_signals(self) -> None:
        root = _make_fixture(**{"README.md": "hi"})
        ints = detect_integrations(root)
        self.assertFalse(has_integrations(ints))


class TestFrontmatterAndAnchors(unittest.TestCase):
    def test_parse_frontmatter_strips_to_body(self) -> None:
        text = "---\nschema_version: 1\nartifact_type: codebase.stack\n---\n# Title\n\n## [codebase.stack.runtime] Runtime\nPython 3.12"
        fm, body = parse_frontmatter(text)
        self.assertEqual(fm["schema_version"], "1")
        self.assertEqual(fm["artifact_type"], "codebase.stack")
        self.assertIn("# Title", body)

    def test_split_anchors_extracts_id_and_title(self) -> None:
        body = "# X\n\n## [codebase.stack.runtime] Runtime\nPython\n\n## [codebase.stack.languages] Languages\nPython"
        sections = split_anchors(body)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0][0], "codebase.stack.runtime")
        self.assertEqual(sections[0][1], "Runtime")
        self.assertIn("Python", sections[0][2])

    def test_render_anchor_section_roundtrips(self) -> None:
        s = render_anchor_section("codebase.stack.test", "Test runners", "- pytest")
        sections = split_anchors(s)
        self.assertEqual(sections[0][0], "codebase.stack.test")


class TestBuildCodebaseDocs(unittest.TestCase):
    def setUp(self) -> None:
        # Load real skeleton templates for integration realism
        self.templates = load_skeleton_templates(REPO_ROOT)
        self.assertIn("STACK.md", self.templates, "skeleton templates must load")

    def test_writes_core_files(self) -> None:
        root = _make_fixture(**{"pyproject.toml": "[project]"})
        files = build_codebase_docs(root=root, templates=self.templates, today="2026-05-23")
        for fname in ("STACK.md", "STRUCTURE.md", "TESTING.md"):
            self.assertIn(fname, files)
        # Agent-owned files only appear when templates available (they are)
        for fname in ("SUMMARY.md", "CONVENTIONS.md", "CONCERNS.md", "ARCHITECTURE.md"):
            self.assertIn(fname, files)

    def test_skips_integrations_when_no_signals(self) -> None:
        root = _make_fixture(**{"pyproject.toml": "[project]"})
        files = build_codebase_docs(root=root, templates=self.templates, today="2026-05-23")
        self.assertNotIn("INTEGRATIONS.md", files)

    def test_writes_integrations_when_docker_present(self) -> None:
        root = _make_fixture(**{
            "pyproject.toml": "[project]",
            "docker-compose.yml": "version: '3'",
        })
        files = build_codebase_docs(root=root, templates=self.templates, today="2026-05-23")
        self.assertIn("INTEGRATIONS.md", files)
        self.assertIn("docker-compose", files["INTEGRATIONS.md"])

    def test_frontmatter_stamped(self) -> None:
        root = _make_fixture(**{"pyproject.toml": "[project]"})
        files = build_codebase_docs(
            root=root, templates=self.templates,
            generated_by="harness-recon@0.10.0", today="2026-05-23",
        )
        fm, _ = parse_frontmatter(files["STACK.md"])
        self.assertEqual(fm["updated_at"], "2026-05-23")
        self.assertEqual(fm["generated_by"], "harness-recon@0.10.0")
        self.assertEqual(fm["status"], "current")

    def test_anchor_headers_preserved_in_output(self) -> None:
        root = _make_fixture(**{"pyproject.toml": "[project]"})
        files = build_codebase_docs(root=root, templates=self.templates, today="2026-05-23")
        self.assertIn("## [codebase.stack.runtime]", files["STACK.md"])
        self.assertIn("## [codebase.stack.languages]", files["STACK.md"])
        self.assertIn("## [codebase.structure.tree]", files["STRUCTURE.md"])
        self.assertIn("## [codebase.testing.commands]", files["TESTING.md"])

    def test_agent_file_body_preserved(self) -> None:
        """Re-running recon must not clobber agent-edited CONVENTIONS body."""
        root = _make_fixture(**{"pyproject.toml": "[project]"})
        first = build_codebase_docs(root=root, templates=self.templates, today="2026-05-23")
        # Simulate agent editing CONVENTIONS
        conv = first["CONVENTIONS.md"]
        edited = conv.replace(
            "## [codebase.conventions.naming]",
            "## [codebase.conventions.naming] Naming Custom\nCustom rule: snake_case everywhere.\n\n## [codebase.conventions.naming.placeholder]",
            1,
        )
        # Add real content via existing dict
        second = build_codebase_docs(
            root=root,
            templates=self.templates,
            existing={"CONVENTIONS.md": edited},
            today="2026-05-24",
        )
        self.assertIn("Custom rule: snake_case", second["CONVENTIONS.md"])
        fm, _ = parse_frontmatter(second["CONVENTIONS.md"])
        self.assertEqual(fm["updated_at"], "2026-05-24")

    def test_auto_file_overwrites_stack(self) -> None:
        """STACK auto sections overwrite even if old content present."""
        root = _make_fixture(**{"pyproject.toml": "[project]"})
        first = build_codebase_docs(root=root, templates=self.templates, today="2026-05-23")
        # Switch fixture to node
        (root / "pyproject.toml").unlink()
        (root / "package.json").write_text('{"name":"x"}', encoding="utf-8")
        second = build_codebase_docs(
            root=root,
            templates=self.templates,
            existing=first,
            today="2026-05-24",
        )
        self.assertIn("Node.js", second["STACK.md"])
        self.assertNotIn("- Python", second["STACK.md"])

    def test_scope_limits_structure_tree(self) -> None:
        root = _make_fixture(**{
            "src/core/__init__.py": "",
            "tests/unit/__init__.py": "",
            "pyproject.toml": "[project]",
        })
        files = build_codebase_docs(
            root=root, scope=["src"], templates=self.templates, today="2026-05-23",
        )
        self.assertIn("src/", files["STRUCTURE.md"])
        # tests dir should NOT appear in tree when scope limits it
        self.assertNotIn("tests/", files["STRUCTURE.md"])


class TestComputeFilesDiff(unittest.TestCase):
    def test_diff_per_file(self) -> None:
        old = {"STACK.md": "a\n"}
        new = {"STACK.md": "b\n"}
        d = compute_files_diff(old=old, new=new)
        self.assertIn(".planning/codebase/STACK.md", d)
        self.assertIn("-a", d)
        self.assertIn("+b", d)

    def test_no_diff_when_identical(self) -> None:
        d = compute_files_diff(old={"X.md": "same"}, new={"X.md": "same"})
        self.assertEqual(d, "")


class TestReconCLI(unittest.TestCase):
    def _run_harness(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HARNESS), *args],
            cwd=cwd or Path.cwd(),
            capture_output=True,
            text=True,
        )

    def test_creates_core_files(self) -> None:
        root = _make_fixture(**{"pyproject.toml": "[project]"})
        result = self._run_harness("recon", "--target", str(root))
        self.assertEqual(result.returncode, 0, result.stderr)
        cb = root / ".planning" / "codebase"
        for fname in ("STACK.md", "STRUCTURE.md", "TESTING.md", "CONVENTIONS.md", "SUMMARY.md", "CONCERNS.md", "ARCHITECTURE.md"):
            self.assertTrue((cb / fname).exists(), f"{fname} should be created")

    def test_dry_run_writes_nothing(self) -> None:
        root = _make_fixture(**{"package.json": '{"name":"x"}'})
        result = self._run_harness("recon", "--target", str(root), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        cb = root / ".planning" / "codebase"
        self.assertFalse(cb.exists(), "dry-run must not create files")

    def test_stack_md_has_anchors(self) -> None:
        root = _make_fixture(**{"pyproject.toml": "[project]"})
        self._run_harness("recon", "--target", str(root))
        text = (root / ".planning" / "codebase" / "STACK.md").read_text(encoding="utf-8")
        self.assertIn("## [codebase.stack.runtime]", text)
        self.assertIn("## [codebase.stack.languages]", text)

    def test_help_text(self) -> None:
        result = self._run_harness("recon", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--dry-run", result.stdout)
        self.assertIn("--scope", result.stdout)


if __name__ == "__main__":
    unittest.main()
