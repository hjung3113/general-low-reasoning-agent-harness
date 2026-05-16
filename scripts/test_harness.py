#!/usr/bin/env python3
"""Tests for harness distribution, upgrade, and contamination checks."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness
import install_harness
from lib import version

REPO_ROOT = Path(__file__).resolve().parent.parent


class HarnessToolTests(unittest.TestCase):
    SHOW_PHASE_STATUS_PREFLIGHT = (
        "Start with `python3 scripts/show_phase_status.py` when available. "
        "If it reports warnings, treat named files as minimum required reads before trusting the projection. "
        "If it is missing, fails, emits malformed output, or reports an unsupported contract version, "
        "use the legacy durable planning read order."
    )

    WORKFLOW_ENTRYPOINT_MATRIX = (
        ("opencode-discuss", ".opencode/commands/discuss.md", ()),
        ("opencode-plan", ".opencode/commands/plan.md", ()),
        ("opencode-execute", ".opencode/commands/execute.md", ()),
        ("opencode-done", ".opencode/commands/done.md", ()),
        ("roo-phase-discuss", ".roo/commands/phase-discuss.md", (".roo/rules/phase-gate.md",)),
        ("roo-phase-plan", ".roo/commands/phase-plan.md", (".roo/rules/phase-gate.md",)),
        ("roo-phase-execute", ".roo/commands/phase-execute.md", (".roo/rules/phase-gate.md",)),
        ("roo-fsd-phase", ".roo/commands/fsd-phase.md", (".roo/rules/phase-gate.md",)),
        ("roo-simple", ".roo/commands/simple.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-review", ".roo/commands/review.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-doctor", ".roo/commands/doctor.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-feature", ".roo/commands/feature.md", (".roo/rules/phase-gate.md",)),
        ("roo-bugfix", ".roo/commands/bugfix.md", (".roo/rules/phase-gate.md",)),
        ("roo-adr", ".roo/commands/adr.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-issues", ".roo/commands/issues.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-ops", ".roo/commands/ops.md", (".roo/rules/phase-gate.md",)),
        ("roo-auto", ".roo/commands/README.md", ()),
        ("roo-chain", ".roo/commands/README.md", ()),
        ("roo-rules-global", ".roo/rules/global.md", ()),
        ("roo-rules-phase-gate", ".roo/rules/phase-gate.md", ()),
        ("roo-rules-architect", ".roo/rules-architect/rules.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-rules-diagnose", ".roo/rules-diagnose/rules.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-rules-docs-issues", ".roo/rules-docs-issues/rules.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-rules-ops-observability", ".roo/rules-ops-observability/rules.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-rules-orchestrator", ".roo/rules-orchestrator/rules.md", ()),
        ("roo-rules-review", ".roo/rules-review/rules.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-rules-tdd-code", ".roo/rules-tdd-code/rules.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-skills-readme", ".roo/skills/README.md", ()),
        ("roo-skill-architecture-decision", ".roo/skills/workflow-architecture-decision/SKILL.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-skill-bug-diagnosis", ".roo/skills/workflow-bug-diagnosis/SKILL.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-skill-code-review", ".roo/skills/workflow-code-review/SKILL.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-skill-docs-to-issues", ".roo/skills/workflow-docs-to-issues/SKILL.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-skill-feature-tdd", ".roo/skills/workflow-feature-tdd/SKILL.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-skill-harness-doctor", ".roo/skills/workflow-harness-doctor/SKILL.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-skill-ops-observability", ".roo/skills/workflow-ops-observability/SKILL.md", (".roo/rules-orchestrator/rules.md",)),
        ("roo-skill-phase-gate", ".roo/skills/workflow-phase-gate/SKILL.md", (".roo/rules/phase-gate.md",)),
        ("roo-skill-planning-hydration", ".roo/skills/workflow-planning-hydration/SKILL.md", (".roo/rules/phase-gate.md",)),
        ("roo-skill-simple-task", ".roo/skills/workflow-simple-task/SKILL.md", (".roo/rules-orchestrator/rules.md",)),
    )

    def test_normalize_release_version_accepts_only_stable_semver(self) -> None:
        self.assertEqual("0.4.2", harness.normalize_release_version("v0.4.2"))
        self.assertEqual("0.4.2", harness.normalize_release_version("0.4.2"))

        with self.assertRaisesRegex(ValueError, "vMAJOR.MINOR.PATCH"):
            harness.normalize_release_version("v0.4.2-1")

    def test_resolved_version_prefers_cli_then_env_then_exact_tag_then_dev_fallback(self) -> None:
        root = Path("/tmp/harness-source")
        env = {"HARNESS_VERSION": "v2.0.0"}

        self.assertEqual("3.0.0", harness.resolve_harness_version(root, explicit="v3.0.0", env=env))

        with mock.patch.object(version, "git_output") as git_output:
            git_output.return_value = "v1.2.3"
            self.assertEqual("2.0.0", harness.resolve_harness_version(root, env=env))
            git_output.assert_not_called()

        with mock.patch.object(version, "git_output") as git_output, mock.patch.object(
            version, "is_git_worktree_dirty", return_value=False
        ):
            git_output.return_value = "v1.2.3"
            self.assertEqual("1.2.3", harness.resolve_harness_version(root, env={}))

        with mock.patch.object(version, "git_output") as git_output:
            git_output.return_value = "1.2.3"
            self.assertIsNone(harness.exact_release_tag_version(root))

        def fake_git_output(_: Path, command: list[str]) -> str:
            if command == ["git", "describe", "--tags", "--exact-match"]:
                raise subprocess.CalledProcessError(128, command)
            if command == ["git", "rev-parse", "--short=12", "HEAD"]:
                return "abc123def456"
            if command == ["git", "status", "--porcelain"]:
                return ""
            raise AssertionError(command)

        with mock.patch.object(version, "git_output", side_effect=fake_git_output):
            self.assertEqual("0.0.0-dev+abc123def456", harness.resolve_harness_version(root, env={}))

    def test_init_records_cli_resolved_release_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            result = harness.run(["--version", "v9.8.7", "init", "--target", str(target), "--adapters", "none"])

            self.assertEqual(0, result)
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("9.8.7", installed["version"])
            self.assertEqual("9.8.7", installed["files"][".gitignore"]["version"])
            self.assertIn("# >>> low-reasoning-harness:.gitignore v9.8.7", (target / ".gitignore").read_text())

    def test_release_check_requires_exact_clean_tag_matching_expected_version(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "harness").mkdir()
        (root / "harness/manifest.json").write_text(json.dumps({"version": "__release__", "files": []}), encoding="utf-8")
        (root / "README.md").write_text("Install with v1.2.3\n", encoding="utf-8")

        with mock.patch.object(version, "git_output") as git_output, mock.patch.object(
            version, "is_git_worktree_dirty", return_value=False
        ):
            git_output.return_value = "v1.2.3"
            harness.release_check(root=root, expected_version="v1.2.3")

        def origin_main_git_output(_: Path, command: list[str]) -> str:
            if command == ["git", "describe", "--tags", "--exact-match"]:
                return "v1.2.3"
            if command == ["git", "rev-parse", "HEAD"]:
                return "abc"
            if command == ["git", "rev-parse", "origin/main"]:
                return "def"
            raise AssertionError(command)

        with mock.patch.object(version, "git_output", side_effect=origin_main_git_output), mock.patch.object(
            version, "is_git_worktree_dirty", return_value=False
        ):
            with self.assertRaisesRegex(SystemExit, "origin/main"):
                harness.release_check(root=root, expected_version="v1.2.3", require_origin_main=True)

        with mock.patch.object(version, "git_output") as git_output:
            git_output.side_effect = subprocess.CalledProcessError(128, ["git", "describe"])
            with self.assertRaisesRegex(SystemExit, "exact vMAJOR.MINOR.PATCH tag"):
                harness.release_check(root=root, expected_version="v1.2.3")

        with mock.patch.object(version, "git_output", return_value="v1.2.3"), mock.patch.object(
            version, "is_git_worktree_dirty", return_value=True
        ):
            with self.assertRaisesRegex(SystemExit, "dirty worktree"):
                harness.release_check(root=root, expected_version="v1.2.3")

    def test_release_check_rejects_readme_version_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "harness").mkdir()
            (root / "harness/manifest.json").write_text(json.dumps({"version": "__release__", "files": []}), encoding="utf-8")
            (root / "README.md").write_text("Install with v0.4.9\nUpgrade with v0.4.9\n", encoding="utf-8")

            with mock.patch.object(version, "git_output", return_value="v0.5.0"), mock.patch.object(
                version, "is_git_worktree_dirty", return_value=False
            ):
                with self.assertRaisesRegex(SystemExit, "README release version mismatch"):
                    harness.release_check(root=root, expected_version="v0.5.0")

    def test_load_manifest_data_rejects_stale_hardcoded_source_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "harness").mkdir()
            (root / "harness/manifest.json").write_text(json.dumps({"version": "0.4.1", "files": []}), encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "Manifest source version"):
                harness.load_manifest_data(root, version="1.2.3")

    def test_upgrade_from_installed_target_uses_recorded_source_tree(self) -> None:
        source = harness.repo_root()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["--version", "v9.8.7", "init", "--target", str(target), "--adapters", "none"])
            stale_manifest = target / "harness/manifest.json"
            stale_manifest.parent.mkdir(parents=True)
            stale_manifest.write_text(json.dumps({"version": "0.1.0", "files": []}), encoding="utf-8")
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["source"] = str(source)
            installed_path.write_text(json.dumps(installed), encoding="utf-8")

            with mock.patch.object(harness, "repo_root", return_value=target):
                result = harness.run(["--version", "v9.8.8", "upgrade", "--target", str(target), "--dry-run"])

            self.assertEqual(0, result)

    def test_installed_target_harness_upgrade_command_remains_compatible(self) -> None:
        source = harness.repo_root()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["--version", "v1.0.0", "init", "--target", str(target), "--adapters", "none"])
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["source"] = str(source)
            installed_path.write_text(json.dumps(installed), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(target / "scripts/harness.py"),
                    "--version",
                    "v1.0.1",
                    "upgrade",
                    "--target",
                    str(target),
                    "--dry-run",
                ],
                cwd=target,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("upgrade dry-run", result.stdout)
            self.assertIn("version=1.0.1", result.stdout)
            self.assertIn("no mutation performed", result.stdout)

    def test_init_dry_run_reports_selected_scope_and_no_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            result = subprocess.run(
                [
                    sys.executable,
                    str(harness.repo_root() / "scripts/harness.py"),
                    "init",
                    "--target",
                    str(target),
                    "--adapters",
                    "opencode",
                    "--packs",
                    "workflow-core,workflow-tdd",
                    "--dry-run",
                ],
                cwd=harness.repo_root(),
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("init dry-run", result.stdout)
            self.assertIn("target=", result.stdout)
            self.assertIn("adapters=opencode", result.stdout)
            self.assertIn("packs=workflow-core,workflow-tdd", result.stdout)
            self.assertIn("no mutation performed", result.stdout)
            self.assertFalse(target.exists())

    def test_upgrade_harness_source_option_delegates_with_version_and_records_provenance(self) -> None:
        source = harness.repo_root()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["--version", "v1.0.0", "init", "--target", str(target), "--adapters", "none"])

            dry_run = subprocess.run(
                [
                    sys.executable,
                    str(target / "scripts/upgrade_harness.py"),
                    "--source",
                    str(source),
                    "--version",
                    "v1.2.3",
                    "--dry-run",
                ],
                cwd=target,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, dry_run.returncode, dry_run.stderr)
            self.assertIn("selected version=v1.2.3", dry_run.stdout)
            self.assertIn("delegating", dry_run.stdout)
            self.assertIn("no mutation performed", dry_run.stdout)

            result = subprocess.run(
                [
                    sys.executable,
                    str(target / "scripts/upgrade_harness.py"),
                    "--source",
                    str(source),
                    "--version",
                    "v1.2.3",
                ],
                cwd=target,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("1.2.3", installed["version"])
            self.assertEqual(str(source), installed["source"])
            self.assertEqual(
                {"kind": "path", "ref": str(source), "version": "1.2.3"},
                installed["source_provenance"],
            )

    def test_upgrade_harness_defaults_target_to_script_repo_not_cwd(self) -> None:
        source = harness.repo_root()
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            other_cwd = Path(tmpdir) / "other"
            other_cwd.mkdir()
            harness.run(["--version", "v1.0.0", "init", "--target", str(target), "--adapters", "none"])

            result = subprocess.run(
                [
                    sys.executable,
                    str(target / "scripts/upgrade_harness.py"),
                    "--source",
                    str(source),
                    "--version",
                    "v1.2.3",
                    "--dry-run",
                ],
                cwd=other_cwd,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(f"--target {target.resolve()}", result.stdout)
            self.assertNotIn(f"--target {other_cwd.resolve()}", result.stdout)

    def test_upgrade_harness_version_dry_run_reports_download_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["--version", "v1.0.0", "init", "--target", str(target), "--adapters", "none"])

            result = subprocess.run(
                [
                    sys.executable,
                    str(target / "scripts/upgrade_harness.py"),
                    "--version",
                    "v1.2.3",
                    "--repo",
                    "https://example.invalid/harness.git",
                    "--dry-run",
                ],
                cwd=target,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("would download source=https://example.invalid/harness.git@v1.2.3", result.stdout)
            self.assertIn("no mutation performed", result.stdout)
            self.assertFalse((target / ".harness/sources").exists())

    def test_init_records_detected_git_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            with mock.patch.object(
                version,
                "git_source_provenance",
                return_value={
                    "kind": "git",
                    "repo": "git@github.company.com:team/harness.git",
                    "ref": "v1.0.0",
                    "commit": "abc123",
                },
            ):
                harness.run(["--version", "v1.0.0", "init", "--target", str(target), "--adapters", "none"])

            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                {
                    "kind": "git",
                    "repo": "git@github.company.com:team/harness.git",
                    "ref": "v1.0.0",
                    "commit": "abc123",
                    "version": "1.0.0",
                },
                installed["source_provenance"],
            )

    def test_upgrade_harness_defaults_repo_to_installed_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["--version", "v1.0.0", "init", "--target", str(target), "--adapters", "none"])
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["source_provenance"] = {
                "kind": "git",
                "repo": "git@github.company.com:team/harness.git",
                "ref": "v1.0.0",
                "version": "1.0.0",
            }
            installed_path.write_text(json.dumps(installed), encoding="utf-8")

            defaulted = subprocess.run(
                [
                    sys.executable,
                    str(target / "scripts/upgrade_harness.py"),
                    "--version",
                    "v1.2.3",
                    "--dry-run",
                ],
                cwd=target,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, defaulted.returncode, defaulted.stderr)
            self.assertIn("would download source=git@github.company.com:team/harness.git@v1.2.3", defaulted.stdout)

            explicit = subprocess.run(
                [
                    sys.executable,
                    str(target / "scripts/upgrade_harness.py"),
                    "--version",
                    "v1.2.3",
                    "--repo",
                    "ssh://override.example/harness.git",
                    "--dry-run",
                ],
                cwd=target,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, explicit.returncode, explicit.stderr)
            self.assertIn("would download source=ssh://override.example/harness.git@v1.2.3", explicit.stdout)

    def test_upgrade_harness_rejects_cache_with_mismatched_repo_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["--version", "v1.0.0", "init", "--target", str(target), "--adapters", "none"])
            cache = target / ".harness/sources" / "v1.2.3-bad"
            cache.mkdir(parents=True)
            (cache / "harness").mkdir()
            (cache / "harness/manifest.json").write_text(
                json.dumps({"version": "__release__", "files": []}),
                encoding="utf-8",
            )
            (cache / ".harness-source.json").write_text(
                json.dumps({"repo": "repo-a", "ref": "v1.2.3"}),
                encoding="utf-8",
            )
            sys.path.insert(0, str(harness.repo_root() / "scripts"))
            try:
                import upgrade_harness

                with mock.patch.object(upgrade_harness, "repo_cache_key", return_value="v1.2.3-bad"):
                    with self.assertRaisesRegex(SystemExit, "metadata does not match"):
                        upgrade_harness.run(
                            [
                                "--target",
                                str(target),
                                "--version",
                                "v1.2.3",
                                "--repo",
                                "repo-b",
                            ]
                        )
            finally:
                sys.path = [path for path in sys.path if path != str(harness.repo_root() / "scripts")]

    def test_install_harness_wrapper_matches_init_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            result = subprocess.run(
                [
                    sys.executable,
                    str(harness.repo_root() / "scripts/install_harness.py"),
                    "--version",
                    "v2.0.0",
                    "--target",
                    str(target),
                    "--adapters",
                    "none",
                    "--packs",
                    "workflow-core,workflow-tdd",
                ],
                cwd=harness.repo_root(),
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("2.0.0", installed["version"])
            self.assertEqual([], installed["adapters"])
            self.assertEqual(["workflow-core", "workflow-tdd"], installed["packs"])

    def test_install_harness_pack_selection_uses_shown_numbers_only(self) -> None:
        self.assertEqual(
            ["workflow-security-review", "tech-mssql"],
            install_harness.parse_pack_selection("1,tech-mssql", ["workflow-security-review", "tech-mssql"]),
        )
        self.assertEqual([], install_harness.parse_pack_selection("none", ["workflow-security-review"]))
        self.assertEqual("both", install_harness.normalize_adapter_choice("roo,opencode"))

    def test_install_harness_interactive_requires_existing_absolute_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            target.mkdir()
            missing = Path(tmpdir) / "missing"
            result = subprocess.run(
                [
                    sys.executable,
                    str(harness.repo_root() / "scripts/install_harness.py"),
                    "--interactive",
                ],
                input=f"relative-target\n{missing}\n{target}\n1\n2\nnone\nnone\nyes\n",
                cwd=harness.repo_root(),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("Target path must be absolute. Try again.", result.stdout)
            self.assertIn("Target path does not exist. Create it first, then try again.", result.stdout)
            self.assertIn(f"--target {target} --dry-run", result.stdout)
            self.assertIn("target=" + str(target.resolve()), result.stdout)

    def test_install_harness_interactive_merges_profile_packs_with_extra_packs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            target.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    str(harness.repo_root() / "scripts/install_harness.py"),
                    "--interactive",
                    "--adapters",
                    "roo,opencode",
                    "--packs",
                    "workflow-security-review",
                ],
                input=f"{target}\n\n4\n\n\nno\n",
                cwd=harness.repo_root(),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(["opencode", "roo"], installed["adapters"])
            self.assertEqual(
                [
                    "tech-react",
                    "tech-tailwind",
                    "tech-typescript",
                    "workflow-core",
                    "workflow-security-review",
                    "workflow-web-development",
                ],
                installed["packs"],
            )

    def test_uninstall_harness_removes_selected_adapter_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "both"])

            result = subprocess.run(
                [
                    sys.executable,
                    str(harness.repo_root() / "scripts/uninstall_harness.py"),
                    "--target",
                    str(target),
                    "--select",
                    "1",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)
            self.assertFalse((target / ".roo").exists())
            self.assertFalse((target / ".roomodes").exists())
            self.assertFalse((target / ".rooignore").exists())
            self.assertTrue((target / ".opencode").exists())
            self.assertTrue((target / ".planning").exists())
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(["opencode"], installed["adapters"])
            self.assertNotIn(".roo/README.md", installed["files"])
            self.assertIn(".opencode/commands/discuss.md", installed["files"])

    def test_uninstall_harness_removes_core_marker_blocks_without_adapters_or_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "both"])
            agents = target / "AGENTS.md"
            agents.write_text("project notes\n\n" + agents.read_text(encoding="utf-8"), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(harness.repo_root() / "scripts/uninstall_harness.py"),
                    "--target",
                    str(target),
                    "--select",
                    "4",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)
            self.assertTrue((target / ".roo").exists())
            self.assertTrue((target / ".opencode").exists())
            self.assertTrue((target / ".planning").exists())
            self.assertEqual("project notes\n\n", agents.read_text(encoding="utf-8"))
            self.assertNotIn("low-reasoning-harness:AGENTS.md", agents.read_text(encoding="utf-8"))
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("AGENTS.md", installed["files"])
            self.assertIn(".roo/README.md", installed["files"])

    def test_uninstall_harness_docs_selection_warns_and_removes_planning_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "both"])

            result = subprocess.run(
                [
                    sys.executable,
                    str(harness.repo_root() / "scripts/uninstall_harness.py"),
                    "--target",
                    str(target),
                    "--select",
                    "5",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)
            self.assertIn("WARNING: removing planning/docs is not recommended", result.stdout)
            self.assertFalse((target / ".planning").exists())
            self.assertFalse((target / "docs/phase-gate-harness.md").exists())
            self.assertTrue((target / ".roo").exists())
            self.assertTrue((target / ".opencode").exists())
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn(".planning/STATE.md", installed["files"])
            self.assertIn(".roo/README.md", installed["files"])

    def test_uninstall_harness_all_scopes_preserves_install_state_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "both"])

            result = subprocess.run(
                [
                    sys.executable,
                    str(harness.repo_root() / "scripts/uninstall_harness.py"),
                    "--target",
                    str(target),
                    "--select",
                    "1,2,3,4,5",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)
            self.assertFalse((target / ".roo").exists())
            self.assertFalse((target / ".opencode").exists())
            self.assertFalse((target / ".planning").exists())
            installed_path = target / ".harness/installed-manifest.json"
            self.assertTrue(installed_path.exists())
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            self.assertEqual(["README.md"], sorted(installed["files"]))

    def test_uninstall_harness_all_scopes_can_remove_install_state_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "both"])

            result = subprocess.run(
                [
                    sys.executable,
                    str(harness.repo_root() / "scripts/uninstall_harness.py"),
                    "--target",
                    str(target),
                    "--select",
                    "1,2,3,4,5",
                    "--remove-install-state",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)
            self.assertIn("WARNING: removing .harness/installed-manifest.json", result.stdout)
            self.assertFalse((target / ".harness/installed-manifest.json").exists())

    def test_uninstall_harness_interactive_all_scopes_asks_before_install_state_removal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "both"])

            result = subprocess.run(
                [
                    sys.executable,
                    str(harness.repo_root() / "scripts/uninstall_harness.py"),
                    "--interactive",
                ],
                input=f"{target}\n1,2,3,4,5\nno\nno\n",
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)
            self.assertIn("Also remove .harness/installed-manifest.json?", result.stdout)
            self.assertTrue((target / ".harness/installed-manifest.json").exists())

    def test_uninstall_harness_install_state_removal_requires_all_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "both"])

            result = subprocess.run(
                [
                    sys.executable,
                    str(harness.repo_root() / "scripts/uninstall_harness.py"),
                    "--target",
                    str(target),
                    "--select",
                    "1",
                    "--remove-install-state",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("--remove-install-state requires selecting all uninstall scopes", result.stderr)

    def test_harness_uninstall_command_delegates_to_uninstall_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "both"])

            result = harness.run(["uninstall", "--target", str(target), "--select", "2"])

            self.assertEqual(0, result)
            self.assertTrue((target / ".roo").exists())
            self.assertFalse((target / ".opencode").exists())
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(["roo"], installed["adapters"])

    def test_doctor_reports_structured_roadmap_state_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_sync_fixture(root, state_total=4)

            findings = harness.collect_doctor_findings(root)

            sync_findings = [finding for finding in findings if finding.code == "roadmap_state_sync"]
            self.assertTrue(sync_findings)
            self.assertEqual("P1", sync_findings[0].severity)
            self.assertIn("cause", sync_findings[0].to_dict())
            self.assertIn("impact", sync_findings[0].to_dict())
            self.assertIn("fix", sync_findings[0].to_dict())
            self.assertFalse(sync_findings[0].connects_to_db)

    def test_doctor_reports_shared_phase_status_warning_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_sync_fixture(root, phase_state_current_checkpoint="CP-04-99")

            findings = harness.collect_doctor_findings(root)

            self.assertTrue(
                any(finding.code == "phase_status_state_checkpoint_drift" for finding in findings),
                [finding.to_dict() for finding in findings],
            )

    def test_doctor_reports_projection_required_reads_as_projection_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_sync_fixture(root)

            import lib.doctor as _doctor_mod
            with mock.patch.object(_doctor_mod, "load_projection") as load_projection:
                load_projection.return_value = mock.Mock(required_reads=[], warnings=[])
                findings = harness.collect_doctor_findings(root)

            required_read_findings = [
                finding for finding in findings if finding.code == "phase_status_required_reads_empty"
            ]
            self.assertTrue(required_read_findings, [finding.to_dict() for finding in findings])
            self.assertIn("do not add required_reads to phase-state", required_read_findings[0].fix)

    def test_done_phase_is_unapproved_non_execute_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_sync_fixture(root)
            state_path = root / ".scratch/phase-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["phase"] = "done"
            state["approved"] = False
            state_path.write_text(json.dumps(state), encoding="utf-8")

            harness.check_phase_state_semantics(state_path)

            state["approved"] = True
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "done phase requires approved=false"):
                harness.check_phase_state_semantics(state_path)

    def test_doctor_json_output_is_deterministic_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_sync_fixture(root)

            with mock.patch.object(harness, "subprocess") as subprocess_mock:
                rendered = harness.render_doctor_report(harness.collect_doctor_findings(root), output_format="json")

            payload = json.loads(rendered)
            self.assertEqual(["findings"], sorted(payload))
            self.assertTrue(any(item["code"] == "diff_before_mutation" for item in payload["findings"]))
            subprocess_mock.assert_not_called()

    def test_doctor_rejects_unknown_output_format(self) -> None:
        with self.assertRaisesRegex(SystemExit, "doctor format"):
            harness.render_doctor_report([], output_format="xml")

    def test_doctor_reports_selected_pack_without_installed_files_without_stack_inference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_sync_fixture(root)
            (root / ".harness").mkdir()
            (root / ".harness/installed-manifest.json").write_text(
                json.dumps(
                    {
                        "version": harness.HARNESS_VERSION,
                        "adapters": [],
                        "profiles": ["generic"],
                        "packs": ["workflow-core"],
                        "files": {
                            "AGENTS.md": {"policy": "managed", "owner": "core"},
                            ".planning/STATE.md": {"policy": "managed", "owner": "core"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            findings = harness.installed_scope_doctor_findings(root)

            self.assertEqual(
                ["installed_scope_without_files", "installed_scope_without_files"],
                [finding.code for finding in findings],
            )
            self.assertTrue(all("infer stack support" in finding.fix for finding in findings))

    def write_sync_fixture(
        self,
        root: Path,
        *,
        state_total: int = 5,
        state_completed: int = 3,
        state_percent: int = 60,
        state_checkpoint: str = "CP-04-02",
        phase_state_checkpoint_path: str = ".planning/phases/04-template-consumer-onboarding/04-CHECKPOINTS.md",
        phase_state_current_checkpoint: str = "CP-04-02",
    ) -> None:
        (root / "harness/skeleton/clean").mkdir(parents=True)
        (root / "harness").mkdir(exist_ok=True)
        (root / "harness/manifest.json").write_text(
            json.dumps({"version": harness.HARNESS_VERSION, "files": []}), encoding="utf-8"
        )
        (root / ".roomodes").write_text(json.dumps({"customModes": []}), encoding="utf-8")
        (root / ".scratch").mkdir()
        (root / ".scratch/phase-state.schema.json").write_text("{}", encoding="utf-8")
        (root / ".scratch/phase-state.example.json").write_text(
            json.dumps(
                {
                    "phase": "discuss",
                    "approved": False,
                    "automation_mode": "manual",
                    "auto_selected": [],
                    "updated_at": "2026-05-15T00:00:00Z",
                    "updated_by": "test-fixture",
                }
            ),
            encoding="utf-8",
        )
        (root / ".scratch/phase-state.json").write_text(
            json.dumps(
                {
                    "phase": "execute",
                    "approved": True,
                    "plan_id": "harness-sync-doctor-04-01",
                    "automation_mode": "manual",
                    "auto_selected": [],
                    "state_path": ".planning/STATE.md",
                    "plan_path": ".planning/phases/04-template-consumer-onboarding/04-01-PLAN.md",
                    "checkpoint_path": phase_state_checkpoint_path,
                    "current_checkpoint": phase_state_current_checkpoint,
                    "next_action": "Run the approved verification.",
                    "allowed_paths": ["scripts/harness.py"],
                    "verification": ["python3 -m unittest scripts/test_harness.py"],
                    "approved_by": "test-fixture",
                    "approved_at": "2026-05-15T00:00:00Z",
                    "updated_at": "2026-05-15T00:00:00Z",
                    "updated_by": "test-fixture",
                }
            ),
            encoding="utf-8",
        )
        phase_dir = root / ".planning/phases/04-template-consumer-onboarding"
        phase_dir.mkdir(parents=True)
        (phase_dir / "04-01-PLAN.md").write_text("# Phase 4 Plan\n", encoding="utf-8")
        (phase_dir / "04-CHECKPOINTS.md").write_text(
            f"# Phase 4 Checkpoints\n\n## {state_checkpoint} - Review complete\n\n- **Status**: Complete.\n",
            encoding="utf-8",
        )
        (root / ".planning/ROADMAP.md").write_text(
            """# ROADMAP

## Phases

- [x] **Phase 1: Document-Centered Phase Continuity** - Complete.
- [x] **Phase 2: DB Context Snapshot** - Complete.
- [x] **Phase 3: Mechanical Gate Enforcement** - Complete.
- [ ] **Phase 4: Template Consumer Onboarding** - In progress.
- [ ] **Phase 5: Example ETL Slice** - Not started.

## Progress

| Phase | Plans Complete | Status | Completed |
| --- | ---: | --- | --- |
| 1. Document-Centered Phase Continuity | 1/1 | Implemented | 2026-05-11 |
| 2. DB Context Snapshot | 1/1 | Implemented | 2026-05-13 |
| 3. Mechanical Gate Enforcement | 1/1 | Implemented | 2026-05-14 |
| 4. Template Consumer Onboarding | 0/1 | In progress | - |
| 5. Example ETL Slice | 0/? | Not started | - |
""",
            encoding="utf-8",
        )
        (root / ".planning/STATE.md").write_text(
            f"""---
progress:
  total_phases: {state_total}
  completed_phases: {state_completed}
  percent: {state_percent}
---

# STATE

## Current Position

- **Phase**: 4 - Harness Sync, DB Compatibility, and Doctor **EXECUTE APPROVED**.
- **Progress**: Phase 4: 0/1 plan complete; {state_completed}/{state_total} phases complete overall.

## Active Checkpoint

- **Checkpoint**: {state_checkpoint} - design adversarial review complete.
- **Checkpoint file**: `.planning/phases/04-template-consumer-onboarding/04-CHECKPOINTS.md`.
""",
            encoding="utf-8",
        )

    def test_roadmap_state_sync_accepts_matching_progress_and_pointers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_sync_fixture(root)

            self.assertEqual([], harness.find_roadmap_state_sync_findings(root))
            harness.check(root=root)

    def test_roadmap_state_sync_reports_state_progress_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_sync_fixture(root, state_total=4, state_completed=2, state_percent=50)

            findings = harness.find_roadmap_state_sync_findings(root)

            self.assertTrue(any("progress.total_phases" in finding for finding in findings))
            self.assertTrue(any("progress.completed_phases" in finding for finding in findings))
            self.assertTrue(any("progress.percent" in finding for finding in findings))

    def test_check_rejects_phase_state_checkpoint_pointer_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_sync_fixture(
                root,
                phase_state_checkpoint_path=".planning/phases/04-template-consumer-onboarding/WRONG.md",
                phase_state_current_checkpoint="CP-04-99",
            )
            (root / ".planning/phases/04-template-consumer-onboarding/WRONG.md").write_text(
                "# Wrong checkpoint file\n\n## CP-04-99 - Wrong\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(SystemExit, "Roadmap/state sync invariant"):
                harness.check(root=root)

    def test_init_installs_clean_project_state_without_live_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            result = harness.run(["init", "--target", str(target)])

            self.assertEqual(0, result)
            state = (target / ".planning/STATE.md").read_text(encoding="utf-8")
            phase_state = json.loads((target / ".scratch/phase-state.json").read_text(encoding="utf-8"))
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))

            self.assertNotIn("DB context snapshot", state)
            self.assertNotIn("PR #", state)
            self.assertEqual("discuss", phase_state["phase"])
            self.assertFalse(phase_state["approved"])
            self.assertEqual(harness.HARNESS_VERSION, installed["version"])
            self.assertTrue((target / ".roo/skills/workflow-phase-gate/SKILL.md").exists())
            self.assertTrue((target / "scripts/project_dashboard.py").exists())
            self.assertTrue((target / "scripts/test_project_dashboard.py").exists())
            agents = (target / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("Karpathy-Inspired Coding Guidelines", agents)
            for phrase in (
                "Think Before Coding",
                "Simplicity First",
                "Surgical Changes",
                "Goal-Driven Execution",
            ):
                self.assertIn(phrase, agents)
            self.assertIn("project_dashboard.py", (target / "README.md").read_text(encoding="utf-8"))

    def test_init_core_only_does_not_install_client_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            harness.run(["init", "--target", str(target), "--adapters", "none"])

            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual([], installed["adapters"])
            self.assertFalse((target / ".roo").exists())
            self.assertFalse((target / ".roomodes").exists())
            self.assertFalse((target / ".opencode").exists())
            harness.run(["check", "--target", str(target)])

    def test_init_opencode_only_installs_opencode_without_roo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            harness.run(["init", "--target", str(target), "--adapters", "opencode"])

            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(["opencode"], installed["adapters"])
            self.assertTrue((target / ".opencode/commands/plan.md").exists())
            self.assertFalse((target / ".roo").exists())
            self.assertFalse((target / ".roomodes").exists())
            harness.run(["check", "--target", str(target), "--adapter", "opencode"])

    def test_init_both_adapter_alias_installs_roo_and_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            harness.run(["init", "--target", str(target), "--adapters", "both"])

            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(["opencode", "roo"], installed["adapters"])
            self.assertTrue((target / ".roo/commands/phase-plan.md").exists())
            self.assertTrue((target / ".opencode/commands/plan.md").exists())
            harness.run(["check", "--target", str(target), "--adapter", "opencode"])

    def test_workflow_core_pack_installs_composable_project_local_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            harness.run(
                [
                    "init",
                    "--target",
                    str(target),
                    "--adapters",
                    "none",
                    "--packs",
                    "workflow-core",
                ]
            )

            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(["workflow-core"], installed["packs"])
            for skill_name in (
                "repository-evidence-research",
                "skill-plugin-composition",
                "ecosystem-skill-research",
                "verification-contract",
                "risk-review",
                "multi-agent-review",
                "release-readiness-audit",
                "data-workflow",
                "integration-boundary",
            ):
                self.assertTrue((target / f".agents/skills/{skill_name}/SKILL.md").exists(), skill_name)
            skill = target / ".agents/skills/skill-plugin-composition/SKILL.md"
            self.assertIn("Skills are composable plugins", skill.read_text(encoding="utf-8"))
            harness.run(["check", "--target", str(target)])

    def test_requested_tech_and_workflow_packs_install_as_composable_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            packs = ",".join(
                [
                    "tech-python",
                    "tech-react",
                    "tech-typescript",
                    "tech-tailwind",
                    "tech-csharp",
                    "tech-mssql",
                    "tech-postgresql",
                    "workflow-data-analysis",
                    "workflow-data-processing",
                    "workflow-etl",
                    "workflow-db-context",
                    "workflow-web-development",
                    "workflow-tdd",
                    "workflow-debugging",
                    "workflow-code-review",
                    "workflow-skill-authoring",
                    "workflow-security-review",
                ]
            )

            harness.run(["init", "--target", str(target), "--adapters", "none", "--packs", packs])

            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(packs.split(",")), installed["packs"])
            for skill_name in packs.split(","):
                self.assertTrue((target / f".agents/skills/{skill_name}/SKILL.md").exists(), skill_name)
            self.assertFalse((target / ".roo").exists())
            harness.run(["check", "--target", str(target)])

    def test_init_rejects_unknown_adapter_profile_or_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            for args, message in (
                (["--adapters", "unknown-adapter"], "adapter: unknown-adapter"),
                (["--profiles", "unknown-profile"], "profile: unknown-profile"),
                (["--packs", "unknown-pack"], "pack: unknown-pack"),
            ):
                with self.subTest(args=args):
                    with self.assertRaisesRegex(SystemExit, message):
                        harness.run(["init", "--target", str(target), *args])
                    self.assertFalse(target.exists())

    def test_check_target_rejects_installed_state_with_unknown_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["packs"] = ["unknown-pack"]
            installed_path.write_text(json.dumps(installed), encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "pack: unknown-pack"):
                harness.run(["check", "--target", str(target)])

    def test_target_local_check_rejects_unknown_installed_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["adapters"] = ["unknown-adapter"]
            installed["packs"] = ["unknown-pack"]
            installed_path.write_text(json.dumps(installed), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "scripts/harness.py", "check"],
                cwd=target,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(0, completed.returncode)
            self.assertIn("Unknown installed harness scope", completed.stderr)

    def test_csharp_mssql_etl_pack_composition_recreates_specialized_guardrails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            harness.run(
                [
                    "init",
                    "--target",
                    str(target),
                    "--adapters",
                    "roo,opencode",
                    "--profiles",
                    "generic,dotnet-etl",
                    "--packs",
                    "workflow-core,tech-csharp,tech-mssql,workflow-etl,workflow-db-context",
                ]
            )

            for skill_name in (
                "tech-csharp",
                "tech-mssql",
                "workflow-etl",
                "workflow-db-context",
                "verification-contract",
                "risk-review",
            ):
                self.assertTrue((target / f".agents/skills/{skill_name}/SKILL.md").exists(), skill_name)
            profile = (target / "docs/profiles/dotnet-etl.md").read_text(encoding="utf-8")
            self.assertIn("dotnet-etl", profile)
            etl = (target / ".agents/skills/workflow-etl/SKILL.md").read_text(encoding="utf-8")
            self.assertIn("tech-csharp", etl)
            self.assertIn("tech-mssql", etl)
            self.assertIn("workflow-db-context", etl)
            db_context = (target / ".agents/skills/workflow-db-context/SKILL.md").read_text(encoding="utf-8")
            self.assertIn("needs-db-context", db_context)
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("dotnet-etl", installed["profiles"])
            self.assertEqual("workflow", installed["pack_metadata"]["workflow-db-context"]["category"])
            self.assertIn("sql server verification", installed["pack_metadata"]["tech-mssql"]["capabilities"])
            self.assertTrue((target / ".roo/skills/workflow-phase-gate/SKILL.md").exists())
            self.assertTrue((target / ".opencode/commands/execute.md").exists())
            harness.run(["check", "--target", str(target), "--adapter", "opencode"])

    def test_quality_workflow_packs_install_low_reasoning_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            packs = ",".join(
                [
                    "workflow-core",
                    "workflow-tdd",
                    "workflow-debugging",
                    "workflow-code-review",
                    "workflow-skill-authoring",
                    "workflow-security-review",
                ]
            )

            harness.run(["init", "--target", str(target), "--adapters", "none", "--packs", packs])

            expected_snippets = {
                "workflow-tdd": "Do not implement first",
                "workflow-debugging": "Do not guess the cause",
                "workflow-code-review": "Findings first",
                "workflow-skill-authoring": "A useful skill must say when to use it",
                "workflow-security-review": "Identify trust boundaries before editing",
            }
            for skill_name, snippet in expected_snippets.items():
                skill = (target / f".agents/skills/{skill_name}/SKILL.md").read_text(encoding="utf-8")
                self.assertIn("## Output Contract", skill)
                self.assertIn(snippet, skill)

            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(packs.split(",")), installed["packs"])
            self.assertIn("red green refactor", installed["pack_metadata"]["workflow-tdd"]["capabilities"])
            harness.run(["check", "--target", str(target)])

    def test_default_roo_adapter_does_not_leak_specialized_stack_guardrails(self) -> None:
        forbidden = (
            ".NET 10",
            "MSSQL",
            "SQL Server",
            "ETL",
            "SqlBulkCopy",
            "MERGE",
            "EF Core",
            "xUnit",
            "testcontainers",
            "FluentAssertions",
            "NSubstitute",
            "Dapper",
            "SQLite",
            "InMemory",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "roo", "--packs", "workflow-core"])

            offenders = []
            scan_roots = [
                target / "AGENTS.md",
                target / "README.md",
                target / ".roomodes",
                target / "scripts/harness.py",
                *sorted((target / ".roo").rglob("*.md")),
                *sorted((target / ".planning").rglob("*.md")),
                *sorted((target / ".agents").rglob("*.md")),
            ]
            for path in scan_roots:
                if not path.exists():
                    continue
                text = path.read_text(encoding="utf-8")
                for phrase in forbidden:
                    if phrase in text:
                        offenders.append(f"{path.relative_to(target)}: {phrase}")

            self.assertEqual([], offenders)

    def test_init_installs_first_action_and_phase_zero_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            harness.run(["init", "--target", str(target)])

            readme = (target / "README.md").read_text(encoding="utf-8")
            state = (target / ".planning/STATE.md").read_text(encoding="utf-8")
            self.assertIn("Fresh target first action", readme)
            self.assertIn("python3 scripts/harness.py state show", state)
            for earlier, later in (
                ("`AGENTS.md`", "`.planning/STATE.md`"),
                ("`.planning/STATE.md`", "`.planning/ROADMAP.md`"),
                ("`.planning/ROADMAP.md`", "`.planning/codebase/**`"),
                ("`.planning/codebase/**`", "active phase checkpoint"),
                ("active phase docs", "`.scratch/phase-state.json`"),
            ):
                self.assertLess(readme.index(earlier), readme.index(later))
            for filename in (
                "00-CONTEXT.md",
                "00-01-PLAN.md",
                "00-REVIEW.md",
                "00-VERIFICATION.md",
                "00-01-SUMMARY.md",
            ):
                text = (target / ".planning/phases/00-planning-hydration" / filename).read_text(encoding="utf-8")
                self.assertIn("not hydrated yet", text)

    def test_init_installs_target_safe_smoke_test_suite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = harness.repo_root()
            target = Path(tmpdir) / "target"

            harness.run(["init", "--target", str(target)])

            self.assertEqual(
                (root / "scripts/target_smoke_test.py").read_text(encoding="utf-8"),
                (target / "scripts/test_harness.py").read_text(encoding="utf-8"),
            )
            completed = subprocess.run(
                [sys.executable, "scripts/test_harness.py"],
                cwd=target,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_init_preserves_existing_project_owned_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            state = target / ".planning/STATE.md"
            state.parent.mkdir(parents=True)
            state.write_text("existing project memory", encoding="utf-8")

            result = harness.run(["init", "--target", str(target)])

            self.assertEqual(0, result)
            self.assertEqual("existing project memory", state.read_text(encoding="utf-8"))
            self.assertTrue((target / "AGENTS.md").exists())

    def test_init_appends_gitignore_block_to_existing_project_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            target.mkdir()
            gitignore = target / ".gitignore"
            gitignore.write_text("node_modules/\n", encoding="utf-8")

            result = harness.run(["init", "--target", str(target), "--adapters", "none"])

            self.assertEqual(0, result)
            text = gitignore.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("node_modules/\n"))
            self.assertEqual(1, text.count("# >>> low-reasoning-harness:.gitignore v"))
            self.assertIn(".scratch/reports/", text)
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            info = installed["files"][".gitignore"]
            self.assertEqual("managed-append", info["policy"])
            self.assertEqual(harness.HARNESS_VERSION, info["version"])
            self.assertIn("source_sha256", info)
            self.assertIn("applied_sha256", info)

    def test_init_still_refuses_existing_non_append_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            command = target / ".roo/commands/simple.md"
            command.parent.mkdir(parents=True)
            command.write_text("project command", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "Refusing to overwrite"):
                harness.run(["init", "--target", str(target)])

            self.assertEqual("project command", command.read_text(encoding="utf-8"))

    def test_init_preserves_existing_project_readme(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            readme = target / "README.md"
            readme.parent.mkdir(parents=True)
            readme.write_text("# Existing Project\n", encoding="utf-8")

            result = harness.run(["init", "--target", str(target), "--adapters", "none"])

            self.assertEqual(0, result)
            self.assertEqual("# Existing Project\n", readme.read_text(encoding="utf-8"))
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("project-owned", installed["files"]["README.md"]["policy"])

    def test_init_dry_run_has_no_filesystem_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            result = harness.run(["init", "--target", str(target), "--dry-run"])

            self.assertEqual(0, result)
            self.assertFalse(target.exists())

    def test_manifest_destination_paths_cannot_escape_target(self) -> None:
        entry = harness.ManifestEntry(
            path=PurePosixPath("../outside.md"),
            source=PurePosixPath("README.md"),
            policy="harness-owned",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(SystemExit, "escapes target"):
                harness.destination_path(Path(tmpdir), entry)

    def test_write_copy_refuses_destination_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source.txt"
            outside = root / "outside.txt"
            link = root / "target.txt"
            source.write_text("new", encoding="utf-8")
            outside.write_text("old", encoding="utf-8")
            link.symlink_to(outside)

            with self.assertRaisesRegex(SystemExit, "symlink"):
                harness.write_copy(source, link)

            self.assertEqual("old", outside.read_text(encoding="utf-8"))

    def test_write_copy_refuses_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source.txt"
            outside_dir = root / "outside"
            link_dir = root / "target/link"
            source.write_text("new", encoding="utf-8")
            outside_dir.mkdir()
            link_dir.parent.mkdir(parents=True)
            link_dir.symlink_to(outside_dir, target_is_directory=True)

            with self.assertRaisesRegex(SystemExit, "symlink"):
                harness.write_copy(source, link_dir / "nested/file.txt")

            self.assertFalse((outside_dir / "nested/file.txt").exists())

    def test_upgrade_preserves_project_owned_state_and_reports_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target)])
            state = target / ".planning/STATE.md"
            state.write_text("real project state", encoding="utf-8")
            command = target / ".roo/commands/simple.md"
            command.write_text("local command edit", encoding="utf-8")

            result = harness.run(["upgrade", "--target", str(target)])

            self.assertEqual(1, result)
            self.assertEqual("real project state", state.read_text(encoding="utf-8"))
            self.assertEqual("local command edit", command.read_text(encoding="utf-8"))
            self.assertTrue((target / ".harness/conflicts/.roo/commands/simple.md.new").exists())

    def test_upgrade_migrates_unmodified_legacy_managed_gitignore_to_marker_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            gitignore = target / ".gitignore"
            legacy = (harness.repo_root() / "harness/skeleton/clean/.gitignore").read_text(encoding="utf-8")
            gitignore.write_text(legacy, encoding="utf-8")
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["files"][".gitignore"] = {"policy": "managed", "sha256": harness.file_hash(gitignore)}
            installed_path.write_text(json.dumps(installed), encoding="utf-8")

            result = harness.run(["upgrade", "--target", str(target), "--adapters", "none"])

            self.assertEqual(0, result)
            text = gitignore.read_text(encoding="utf-8")
            self.assertEqual(1, text.count(".scratch/reports/"))
            self.assertEqual(1, text.count("# >>> low-reasoning-harness:.gitignore v"))
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            self.assertEqual("managed-append", installed["files"][".gitignore"]["policy"])

    def test_upgrade_migrates_unmodified_legacy_managed_agents_to_marker_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            agents = target / "AGENTS.md"
            legacy = (harness.repo_root() / "harness/skeleton/clean/AGENTS.md").read_text(encoding="utf-8")
            agents.write_text(legacy, encoding="utf-8")
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["files"]["AGENTS.md"] = {"policy": "managed", "sha256": harness.file_hash(agents)}
            installed_path.write_text(json.dumps(installed), encoding="utf-8")

            result = harness.run(["upgrade", "--target", str(target), "--adapters", "none"])

            self.assertEqual(0, result)
            text = agents.read_text(encoding="utf-8")
            self.assertEqual(1, text.count("# >>> low-reasoning-harness:AGENTS.md v"))
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            self.assertEqual("managed-append", installed["files"]["AGENTS.md"]["policy"])

    def test_upgrade_conflicts_modified_legacy_managed_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            agents = target / "AGENTS.md"
            agents.write_text("legacy agents\n", encoding="utf-8")
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["files"]["AGENTS.md"] = {"policy": "managed", "sha256": harness.file_hash(agents)}
            installed_path.write_text(json.dumps(installed), encoding="utf-8")
            agents.write_text("legacy agents\nproject notes\n", encoding="utf-8")

            result = harness.run(["upgrade", "--target", str(target), "--adapters", "none"])

            self.assertEqual(1, result)
            self.assertEqual("legacy agents\nproject notes\n", agents.read_text(encoding="utf-8"))
            self.assertTrue((target / ".harness/conflicts/AGENTS.md.new").exists())

    def test_upgrade_preserves_project_readme_and_normalizes_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            readme = target / "README.md"
            readme.write_text("# Project README\n\nReal project docs.\n", encoding="utf-8")

            result = harness.run(["upgrade", "--target", str(target), "--force", "--adapters", "none"])

            self.assertEqual(0, result)
            self.assertEqual("# Project README\n\nReal project docs.\n", readme.read_text(encoding="utf-8"))
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("project-owned", installed["files"]["README.md"]["policy"])

    def test_upgrade_conflicts_modified_legacy_managed_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            gitignore = target / ".gitignore"
            gitignore.write_text("legacy\n", encoding="utf-8")
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["files"][".gitignore"] = {"policy": "managed", "sha256": harness.file_hash(gitignore)}
            installed_path.write_text(json.dumps(installed), encoding="utf-8")
            gitignore.write_text("legacy\nlocal edit\n", encoding="utf-8")

            result = harness.run(["upgrade", "--target", str(target), "--adapters", "none"])

            self.assertEqual(1, result)
            self.assertEqual("legacy\nlocal edit\n", gitignore.read_text(encoding="utf-8"))
            self.assertTrue((target / ".harness/conflicts/.gitignore.new").exists())

    def test_upgrade_conflicts_local_edits_inside_gitignore_marker_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            gitignore = target / ".gitignore"
            original = gitignore.read_text(encoding="utf-8")
            gitignore.write_text(
                original.replace(".scratch/reports/", ".scratch/reports/\nlocal-inside-block/"),
                encoding="utf-8",
            )

            result = harness.run(["upgrade", "--target", str(target), "--adapters", "none"])

            self.assertEqual(1, result)
            self.assertIn("local-inside-block/", gitignore.read_text(encoding="utf-8"))
            self.assertTrue((target / ".harness/conflicts/.gitignore.new").exists())

    def test_same_version_upgrade_adds_new_pack_without_rewriting_existing_append_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none", "--packs", "workflow-core"])
            gitignore = target / ".gitignore"
            before = gitignore.read_text(encoding="utf-8")

            result = harness.run(
                [
                    "upgrade",
                    "--target",
                    str(target),
                    "--adapters",
                    "none",
                    "--packs",
                    "workflow-core,workflow-tdd",
                ]
            )

            self.assertEqual(0, result)
            self.assertEqual(before, gitignore.read_text(encoding="utf-8"))
            self.assertTrue((target / ".agents/skills/workflow-tdd/SKILL.md").exists())

    def test_init_records_scope_and_upgrade_reuses_it_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(
                [
                    "init",
                    "--target",
                    str(target),
                    "--adapters",
                    "opencode",
                    "--profiles",
                    "generic,dotnet-etl",
                    "--packs",
                    "workflow-core,workflow-tdd,tech-python",
                ]
            )

            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(["opencode"], installed["init_options"]["adapters"])
            self.assertEqual(["dotnet-etl", "generic"], installed["init_options"]["profiles"])
            self.assertEqual(["tech-python", "workflow-core", "workflow-tdd"], installed["init_options"]["packs"])

            result = harness.run(["upgrade", "--target", str(target)])

            self.assertEqual(0, result)
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(["opencode"], installed["adapters"])
            self.assertEqual(["dotnet-etl", "generic"], installed["profiles"])
            self.assertEqual(["tech-python", "workflow-core", "workflow-tdd"], installed["packs"])
            self.assertEqual(installed["init_options"]["packs"], installed["packs"])
            self.assertTrue((target / ".opencode/commands/plan.md").exists())
            self.assertFalse((target / ".roo").exists())
            self.assertTrue((target / ".agents/skills/workflow-tdd/SKILL.md").exists())
            self.assertTrue((target / ".agents/skills/tech-python/SKILL.md").exists())

    def test_upgrade_without_install_state_refuses_existing_manifest_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            command = target / ".roo/commands/simple.md"
            command.parent.mkdir(parents=True)
            command.write_text("unknown local file", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "not initialized"):
                harness.run(["upgrade", "--target", str(target)])

            self.assertEqual("unknown local file", command.read_text(encoding="utf-8"))
            self.assertFalse((target / ".harness/conflicts/.roo/commands/simple.md.new").exists())

    def test_upgrade_without_install_state_does_not_bootstrap_empty_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            target.mkdir()

            with self.assertRaisesRegex(SystemExit, "not initialized"):
                harness.run(["upgrade", "--target", str(target)])

            self.assertFalse((target / "AGENTS.md").exists())

    def test_upgrade_adopt_existing_creates_install_state_for_manual_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            (target / ".harness/installed-manifest.json").unlink()

            result = harness.run(["upgrade", "--target", str(target), "--adopt-existing", "--adapters", "none"])

            self.assertEqual(0, result)
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(harness.HARNESS_VERSION, installed["version"])
            self.assertEqual([], installed["adapters"])
            self.assertIn("AGENTS.md", installed["files"])
            self.assertIn(".gitignore", installed["files"])

    def test_upgrade_adopt_existing_records_project_agents_marker_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            (target / ".harness/installed-manifest.json").unlink()
            agents = target / "AGENTS.md"
            agents.write_text(agents.read_text(encoding="utf-8") + "\n## Project Notes\nmanual agents\n", encoding="utf-8")

            result = harness.run(["upgrade", "--target", str(target), "--adopt-existing", "--adapters", "none"])

            self.assertEqual(0, result)
            self.assertIn("manual agents", agents.read_text(encoding="utf-8"))
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("managed-append", installed["files"]["AGENTS.md"]["policy"])

    def test_upgrade_adopt_existing_force_preserves_project_agents_and_project_owned(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            (target / ".harness/installed-manifest.json").unlink()
            agents = target / "AGENTS.md"
            agents.write_text(agents.read_text(encoding="utf-8") + "\n## Project Notes\nmanual agents\n", encoding="utf-8")
            state = target / ".planning/STATE.md"
            state.write_text("real project state\n", encoding="utf-8")

            result = harness.run(
                ["upgrade", "--target", str(target), "--adopt-existing", "--force", "--adapters", "none"]
            )

            self.assertEqual(0, result)
            self.assertIn("manual agents", agents.read_text(encoding="utf-8"))
            self.assertFalse((target / ".harness/conflicts/AGENTS.md.adopted").exists())
            self.assertEqual("real project state\n", state.read_text(encoding="utf-8"))
            self.assertTrue((target / ".harness/installed-manifest.json").exists())

    def test_upgrade_adopt_existing_appends_gitignore_marker_and_preserves_project_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            (target / ".harness/installed-manifest.json").unlink()
            gitignore = target / ".gitignore"
            gitignore.write_text("node_modules/\n", encoding="utf-8")

            result = harness.run(["upgrade", "--target", str(target), "--adopt-existing", "--adapters", "none"])

            self.assertEqual(0, result)
            text = gitignore.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("node_modules/\n"))
            self.assertEqual(1, text.count("# >>> low-reasoning-harness:.gitignore v"))
            self.assertTrue((target / ".harness/installed-manifest.json").exists())

    def test_upgrade_adopt_existing_conflicts_local_gitignore_marker_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            (target / ".harness/installed-manifest.json").unlink()
            gitignore = target / ".gitignore"
            edited = gitignore.read_text(encoding="utf-8").replace(".env\n", ".env\nmanual-inside-block/\n")
            gitignore.write_text(edited, encoding="utf-8")

            result = harness.run(
                ["upgrade", "--target", str(target), "--adopt-existing", "--force", "--adapters", "none"]
            )

            self.assertEqual(1, result)
            self.assertEqual(edited, gitignore.read_text(encoding="utf-8"))
            self.assertTrue((target / ".harness/conflicts/.gitignore.new").exists())
            self.assertFalse((target / ".harness/installed-manifest.json").exists())

    def test_upgrade_adopt_existing_preflight_failure_leaves_earlier_files_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            (target / ".harness/installed-manifest.json").unlink()
            agents = target / "AGENTS.md"
            agents.write_text("manual agents\n", encoding="utf-8")
            gitignore = target / ".gitignore"
            malformed = gitignore.read_text(encoding="utf-8").replace("# <<< low-reasoning-harness:.gitignore\n", "")
            gitignore.write_text(malformed, encoding="utf-8")

            result = harness.run(
                ["upgrade", "--target", str(target), "--adopt-existing", "--force", "--adapters", "none"]
            )

            self.assertEqual(1, result)
            self.assertEqual("manual agents\n", agents.read_text(encoding="utf-8"))
            self.assertEqual(malformed, gitignore.read_text(encoding="utf-8"))
            self.assertFalse((target / ".harness/installed-manifest.json").exists())

    def test_upgrade_adopt_existing_dry_run_has_no_state_or_conflict_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            (target / ".harness/installed-manifest.json").unlink()
            agents = target / "AGENTS.md"
            agents.write_text("manual agents\n", encoding="utf-8")

            result = harness.run(
                ["upgrade", "--target", str(target), "--adopt-existing", "--adapters", "none", "--dry-run"]
            )

            self.assertEqual(0, result)
            self.assertEqual("manual agents\n", agents.read_text(encoding="utf-8"))
            self.assertFalse((target / ".harness/installed-manifest.json").exists())
            self.assertFalse((target / ".harness/conflicts/AGENTS.md.new").exists())

    def test_upgrade_adopt_existing_rejects_target_missing_core_project_owned_planning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            (target / ".harness/installed-manifest.json").unlink()
            (target / ".planning/STATE.md").unlink()

            with self.assertRaisesRegex(SystemExit, "Cannot adopt target missing required project-owned files"):
                harness.run(["upgrade", "--target", str(target), "--adopt-existing", "--adapters", "none"])

            self.assertFalse((target / ".harness/installed-manifest.json").exists())

    def test_upgrade_adopt_existing_does_not_bootstrap_empty_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            target.mkdir()

            with self.assertRaisesRegex(SystemExit, "Cannot adopt target missing required project-owned files"):
                harness.run(["upgrade", "--target", str(target), "--adopt-existing", "--adapters", "none"])

            self.assertFalse((target / ".harness/installed-manifest.json").exists())

    def test_upgrade_adopt_existing_rejects_planning_only_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_target = Path(tmpdir) / "source"
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(source_target), "--adapters", "none"])
            for relative in (
                ".planning/STATE.md",
                ".planning/ROADMAP.md",
                ".scratch/phase-state.json",
            ):
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text((source_target / relative).read_text(encoding="utf-8"), encoding="utf-8")
            for source in (source_target / ".planning/codebase").glob("*"):
                destination = target / ".planning/codebase" / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "Cannot adopt target without existing selected harness files"):
                harness.run(["upgrade", "--target", str(target), "--adopt-existing", "--adapters", "none"])

            self.assertFalse((target / ".harness/installed-manifest.json").exists())

    def test_upgrade_adopt_existing_rejects_plain_project_agents_as_harness_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_target = Path(tmpdir) / "source"
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(source_target), "--adapters", "none"])
            for relative in (
                ".planning/STATE.md",
                ".planning/ROADMAP.md",
                ".scratch/phase-state.json",
                "AGENTS.md",
            ):
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(
                    "plain project agents\n" if relative == "AGENTS.md" else (source_target / relative).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            for source in (source_target / ".planning/codebase").glob("*"):
                destination = target / ".planning/codebase" / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "Cannot adopt target without existing selected harness files"):
                harness.run(["upgrade", "--target", str(target), "--adopt-existing", "--adapters", "none"])

            self.assertFalse((target / ".harness/installed-manifest.json").exists())

    def test_installed_target_can_run_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target)])

            completed = subprocess.run(
                [sys.executable, "scripts/harness.py", "check"],
                cwd=target,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual("", completed.stderr)
            self.assertEqual(0, completed.returncode)

    def test_installed_target_check_ignores_stale_target_local_source_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target)])
            (target / "harness").mkdir()
            (target / "harness/manifest.json").write_text(
                json.dumps({"version": "0.3.2", "files": []}),
                encoding="utf-8",
            )

            harness.check(root=target)

    def test_installed_target_doctor_does_not_report_generic_sync_p1(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target)])

            findings = harness.collect_doctor_findings(target)

            self.assertFalse(
                any(finding.severity == "P1" and finding.code == "roadmap_state_sync" for finding in findings),
                [finding.to_dict() for finding in findings],
            )

    def test_check_target_compares_current_source_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target)])
            missing_path = ".roo/commands/phase-plan.md"
            (target / missing_path).unlink()
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["files"].pop(missing_path)
            installed_path.write_text(json.dumps(installed), encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "Current harness files missing"):
                harness.run(["check", "--target", str(target)])

    def test_check_target_reports_retired_installed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target)])
            retired = target / ".roo/commands/retired.md"
            retired.write_text("retired command", encoding="utf-8")
            self.add_installed_file(target, ".roo/commands/retired.md", retired)

            with self.assertRaisesRegex(SystemExit, "Retired harness files"):
                harness.run(["check", "--target", str(target)])

    def test_check_target_allows_project_readme_without_harness_phrases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target)])
            (target / "README.md").write_text("# Project README\n", encoding="utf-8")

            result = harness.run(["check", "--target", str(target)])

            self.assertEqual(0, result)

    def test_check_target_allows_deleted_project_readme(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target)])
            (target / "README.md").unlink()

            result = harness.run(["check", "--target", str(target)])

            self.assertEqual(0, result)

    def test_check_target_reports_missing_agents_managed_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target)])
            (target / "AGENTS.md").write_text("Karpathy-Inspired Coding Guidelines\n", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "managed-append marker is missing"):
                harness.run(["check", "--target", str(target)])

    def test_check_target_reports_legacy_agents_policy_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target)])
            agents = target / "AGENTS.md"
            legacy = (harness.repo_root() / "harness/skeleton/clean/AGENTS.md").read_text(encoding="utf-8")
            agents.write_text(legacy, encoding="utf-8")
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["files"]["AGENTS.md"] = {"policy": "managed", "sha256": harness.file_hash(agents)}
            installed_path.write_text(json.dumps(installed), encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "Installed policy mismatch"):
                harness.run(["check", "--target", str(target)])

    def test_check_target_rejects_gitignore_marker_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            gitignore = target / ".gitignore"
            gitignore.write_text(
                gitignore.read_text(encoding="utf-8").replace(".env\n", ".env\nmanual-inside-block/\n"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "managed-append"):
                harness.run(["check", "--target", str(target)])

    def test_upgrade_normalizes_legacy_project_owned_state_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            state_path = target / ".planning/STATE.md"
            installed["files"][".planning/STATE.md"] = {
                "policy": "project-owned",
                "sha256": harness.file_hash(state_path),
            }
            installed_path.write_text(json.dumps(installed), encoding="utf-8")

            result = harness.run(["upgrade", "--target", str(target), "--adapters", "none"])

            self.assertEqual(0, result)
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            info = installed["files"][".planning/STATE.md"]
            self.assertEqual("project-owned", info["policy"])
            self.assertEqual(harness.HARNESS_VERSION, info["version"])
            self.assertIn("source_sha256", info)
            self.assertIn("owner", info)

    def test_append_marker_version_only_change_does_not_rewrite_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(harness, "HARNESS_VERSION", "9.9.9"):
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            gitignore = target / ".gitignore"
            original = gitignore.read_text(encoding="utf-8")
            downgraded = original.replace("v9.9.9", "v0.4.1")
            gitignore.write_text(downgraded, encoding="utf-8")
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["files"][".gitignore"]["applied_sha256"] = harness.sha256_text(downgraded)
            installed_path.write_text(json.dumps(installed), encoding="utf-8")

            result = harness.run(["upgrade", "--target", str(target), "--adapters", "none"])

            self.assertEqual(0, result)
            self.assertEqual(downgraded, gitignore.read_text(encoding="utf-8"))

    def test_upgrade_dry_run_marker_conflict_has_no_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            gitignore = target / ".gitignore"
            installed_path = target / ".harness/installed-manifest.json"
            original_gitignore = gitignore.read_text(encoding="utf-8")
            original_state = installed_path.read_text(encoding="utf-8")
            gitignore.write_text(original_gitignore.replace(".env\n", ".env\nmanual-inside-block/\n"), encoding="utf-8")
            drifted_gitignore = gitignore.read_text(encoding="utf-8")

            result = harness.run(["upgrade", "--target", str(target), "--adapters", "none", "--dry-run"])

            self.assertEqual(1, result)
            self.assertEqual(drifted_gitignore, gitignore.read_text(encoding="utf-8"))
            self.assertEqual(original_state, installed_path.read_text(encoding="utf-8"))
            self.assertFalse((target / ".harness/conflicts/.gitignore.new").exists())

    def test_upgrade_malformed_gitignore_marker_conflicts_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            gitignore = target / ".gitignore"
            malformed = gitignore.read_text(encoding="utf-8").replace(
                "# <<< low-reasoning-harness:.gitignore\n",
                "",
            )
            gitignore.write_text(malformed, encoding="utf-8")

            result = harness.run(["upgrade", "--target", str(target), "--adapters", "none"])

            self.assertEqual(1, result)
            self.assertEqual(malformed, gitignore.read_text(encoding="utf-8"))
            self.assertTrue((target / ".harness/conflicts/.gitignore.new").exists())

    def test_upgrade_removes_unmodified_retired_harness_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target)])
            retired = target / ".roo/commands/retired.md"
            retired.write_text("retired command", encoding="utf-8")
            self.add_installed_file(target, ".roo/commands/retired.md", retired)

            result = harness.run(["upgrade", "--target", str(target)])

            self.assertEqual(0, result)
            self.assertFalse(retired.exists())
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn(".roo/commands/retired.md", installed["files"])

    def test_upgrade_removes_empty_adapter_directories_after_scope_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "roo"])

            result = harness.run(["upgrade", "--target", str(target), "--adapters", "opencode"])

            self.assertEqual(0, result)
            self.assertFalse((target / ".roo").exists())
            self.assertFalse((target / ".roomodes").exists())
            self.assertTrue((target / ".opencode/commands/plan.md").exists())
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(["opencode"], installed["init_options"]["adapters"])

    def test_upgrade_reports_modified_retired_harness_file_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target)])
            retired = target / ".roo/commands/retired.md"
            retired.write_text("installed retired command", encoding="utf-8")
            self.add_installed_file(target, ".roo/commands/retired.md", retired)
            retired.write_text("locally edited retired command", encoding="utf-8")

            result = harness.run(["upgrade", "--target", str(target)])

            self.assertEqual(1, result)
            self.assertEqual("locally edited retired command", retired.read_text(encoding="utf-8"))
            self.assertTrue((target / ".harness/conflicts/.roo/commands/retired.md.retired").exists())

    def test_upgrade_removes_unmodified_retired_managed_append_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target), "--adapters", "none"])
            retired = target / "old.append"
            block = "# >>> low-reasoning-harness:old.append v0.4.1\nold/\n# <<< low-reasoning-harness:old.append\n"
            retired.write_text("project-line\n\n" + block, encoding="utf-8")
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["files"]["old.append"] = {
                "policy": "managed-append",
                "sha256": harness.file_hash(retired),
                "applied_sha256": harness.sha256_text(block),
            }
            installed_path.write_text(json.dumps(installed), encoding="utf-8")

            result = harness.run(["upgrade", "--target", str(target), "--adapters", "none"])

            self.assertEqual(0, result)
            self.assertEqual("project-line\n\n", retired.read_text(encoding="utf-8"))
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            self.assertNotIn("old.append", installed["files"])

    def test_check_rejects_contaminated_clean_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = {"version": harness.HARNESS_VERSION, "files": []}
            (root / "harness/skeleton/clean/.planning").mkdir(parents=True)
            (root / "harness").mkdir(exist_ok=True)
            (root / "harness/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "harness/skeleton/clean/.planning/STATE.md").write_text(
                "Current focus: DB context snapshot PR #12", encoding="utf-8"
            )

            with self.assertRaisesRegex(SystemExit, "contamination"):
                harness.check(root=root)

    def test_workflow_entrypoint_matrix_shares_show_phase_status_preflight(self) -> None:
        root = harness.repo_root()
        failures = []

        for name, relative, delegates in self.WORKFLOW_ENTRYPOINT_MATRIX:
            path = root / relative
            text = path.read_text(encoding="utf-8")
            has_preflight = self.SHOW_PHASE_STATUS_PREFLIGHT in text
            delegated = []
            for delegate in delegates:
                delegate_text = (root / delegate).read_text(encoding="utf-8")
                if delegate in text and self.SHOW_PHASE_STATUS_PREFLIGHT in delegate_text:
                    delegated.append(delegate)
            if not has_preflight and not delegated:
                failures.append(f"{name}: {relative}")

        self.assertEqual([], failures)

        active_surfaces = [
            *self._markdown_files(root / ".opencode/commands"),
            *self._markdown_files(root / ".roo"),
            root / "AGENTS.md",
            root / "README.md",
            root / "docs/protocol-spec.md",
            root / "docs/phase-gate-harness.md",
            root / "harness/skeleton/clean/AGENTS.md",
            root / "harness/skeleton/clean/README.md",
        ]
        contradictory = []
        contradictory_phrases = (
            "Fresh sessions must read",
            "Fresh sessions must start with `.planning/STATE.md`",
            "read all planning docs first",
            "read all planning first",
        )
        for path in active_surfaces:
            relative = path.relative_to(root).as_posix()
            if relative.startswith(".planning/phases/") or relative.startswith("docs/superpowers/"):
                continue
            text = path.read_text(encoding="utf-8")
            for phrase in contradictory_phrases:
                if phrase in text:
                    contradictory.append(f"{relative}: {phrase}")

        self.assertEqual([], contradictory)

    def test_manifest_marks_phase_status_scripts_harness_owned(self) -> None:
        root = harness.repo_root()
        manifest = json.loads((root / "harness/manifest.json").read_text(encoding="utf-8"))
        entries = {entry["path"]: entry for entry in manifest["files"]}

        expected_sources = {
            "scripts/show_phase_status.py": "scripts/show_phase_status.py",
            "scripts/upgrade_harness.py": "scripts/upgrade_harness.py",
            "scripts/uninstall_harness.py": "scripts/uninstall_harness.py",
            "scripts/check_harness.py": "scripts/check_harness.py",
            "scripts/doctor_harness.py": "scripts/doctor_harness.py",
            "scripts/lib/__init__.py": "scripts/lib/__init__.py",
            "scripts/lib/planning_status.py": "scripts/lib/planning_status.py",
            "scripts/lib/workflow_static_checks.py": "scripts/lib/workflow_static_checks.py",
        }
        for path, source in expected_sources.items():
            self.assertIn(path, entries)
            self.assertEqual(source, entries[path]["source"])
            self.assertEqual("harness-owned", entries[path]["policy"])

    def _markdown_files(self, root: Path) -> list[Path]:
        if not root.exists():
            return []
        return sorted(path for path in root.rglob("*.md") if path.is_file())

    def test_allowed_paths_use_exact_files_and_directory_prefixes(self) -> None:
        allowed = [".roo/", "README.md"]
        blocked = [".db-context/"]

        self.assertTrue(harness.path_allowed(".roo/skills/workflow-phase-gate/SKILL.md", allowed, blocked))
        self.assertTrue(harness.path_allowed("README.md", allowed, blocked))
        self.assertFalse(harness.path_allowed("README.md.bak", allowed, blocked))
        self.assertFalse(harness.path_allowed(".db-context/latest.json", allowed, blocked))

    def test_check_worktree_paths_accepts_allowed_staged_unstaged_and_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_phase_state_for_worktree(root, allowed_paths=[".scratch/phase-state.json", "allowed/"])
            subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (root / "allowed").mkdir()
            (root / "allowed/staged.txt").write_text("staged", encoding="utf-8")
            subprocess.run(["git", "add", "allowed/staged.txt"], cwd=root, check=True)
            (root / "allowed/unstaged.txt").write_text("unstaged", encoding="utf-8")
            subprocess.run(["git", "add", "allowed/unstaged.txt"], cwd=root, check=True)
            (root / "allowed/unstaged.txt").write_text("changed", encoding="utf-8")
            (root / "allowed/untracked.txt").write_text("untracked", encoding="utf-8")

            harness.check_worktree_paths(root)

    def test_check_worktree_paths_rejects_denied_untracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_phase_state_for_worktree(root, allowed_paths=[".scratch/phase-state.json", "allowed/"])
            subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (root / "outside.txt").write_text("outside", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "Worktree paths outside allowed_paths: outside.txt"):
                harness.check_worktree_paths(root)

    def write_phase_state_for_worktree(self, root: Path, *, allowed_paths: list[str]) -> None:
        (root / ".scratch").mkdir(parents=True)
        (root / ".scratch/phase-state.json").write_text(
            json.dumps(
                {
                    "phase": "execute",
                    "approved": True,
                    "automation_mode": "manual",
                    "auto_selected": [],
                    "plan_id": "worktree-test-plan",
                    "allowed_paths": allowed_paths,
                    "verification": ["python3 scripts/harness.py check"],
                    "state_path": ".planning/STATE.md",
                    "plan_path": ".planning/phases/01/PLAN.md",
                    "checkpoint_path": ".planning/phases/01/CHECKPOINTS.md",
                    "current_checkpoint": "CP-01",
                    "next_action": "Run check --worktree.",
                    "approved_by": "test",
                    "approved_at": "2026-05-15T00:00:00Z",
                    "updated_at": "2026-05-15T00:00:00Z",
                    "updated_by": "test",
                }
            ),
            encoding="utf-8",
        )

    def test_phase_state_semantics_require_auditable_auto_selected_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            path.write_text(
                json.dumps(
                    {
                        "phase": "discuss",
                        "approved": False,
                        "automation_mode": "auto",
                        "auto_selected": ["too vague"],
                        "updated_at": "2026-05-14T00:00:00Z",
                        "updated_by": "test",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "auto_selected\\[0\\] must be an object"):
                harness.check_phase_state_semantics(path)

    def test_phase_state_execute_requires_approval_scope_and_provenance_for_manual_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            path.write_text(
                json.dumps(
                    {
                        "phase": "execute",
                        "approved": True,
                        "automation_mode": "manual",
                        "auto_selected": [],
                        "plan_id": "manual-plan",
                        "updated_at": "2026-05-15T00:00:00Z",
                        "updated_by": "test",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "execute approval requires"):
                harness.check_phase_state_semantics(path)

    def test_phase_state_rejects_bad_timestamp_and_missing_plan_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            path.write_text(
                json.dumps(
                    {
                        "phase": "plan",
                        "approved": False,
                        "automation_mode": "manual",
                        "auto_selected": [],
                        "updated_at": "not-a-date",
                        "updated_by": "test",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "updated_at must be an ISO-8601 UTC timestamp"):
                harness.check_phase_state_semantics(path)

            path.write_text(
                json.dumps(
                    {
                        "phase": "plan",
                        "approved": False,
                        "automation_mode": "manual",
                        "auto_selected": [],
                        "updated_at": "2026-05-15T00:00:00Z",
                        "updated_by": "test",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "plan phase requires"):
                harness.check_phase_state_semantics(path)

    def test_phase_state_rejects_bogus_execute_verification_and_approval_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            path.write_text(
                json.dumps(
                    {
                        "phase": "execute",
                        "approved": True,
                        "automation_mode": "manual",
                        "auto_selected": [],
                        "plan_id": "manual-plan",
                        "allowed_paths": ["scripts/harness.py"],
                        "verification": ["definitely-not-a-command --nope"],
                        "state_path": ".planning/STATE.md",
                        "plan_path": ".planning/phases/01/PLAN.md",
                        "checkpoint_path": ".planning/phases/01/CHECKPOINTS.md",
                        "current_checkpoint": "CP-01",
                        "next_action": "Run verification.",
                        "approved_by": "user",
                        "approved_at": "not-a-date",
                        "updated_at": "2026-05-15T00:00:00Z",
                        "updated_by": "test",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "approved_at must be an ISO-8601 UTC timestamp"):
                harness.check_phase_state_semantics(path)

    def test_phase_state_rejects_placeholder_verification_without_required_reads_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            path.write_text(
                json.dumps(
                    {
                        "phase": "execute",
                        "approved": True,
                        "automation_mode": "manual",
                        "auto_selected": [],
                        "plan_id": "manual-plan",
                        "allowed_paths": ["scripts/harness.py"],
                        "verification": ["TODO: add concrete verification"],
                        "state_path": ".planning/STATE.md",
                        "plan_path": ".planning/phases/01/PLAN.md",
                        "checkpoint_path": ".planning/phases/01/CHECKPOINTS.md",
                        "current_checkpoint": "CP-01",
                        "next_action": "Run verification.",
                        "approved_by": "user",
                        "approved_at": "2026-05-15T00:00:00Z",
                        "updated_at": "2026-05-15T00:00:00Z",
                        "updated_by": "test",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "placeholder verification entry"):
                harness.check_phase_state_semantics(path)

            state = json.loads(path.read_text(encoding="utf-8"))
            state["verification"] = ["Review phase verification file"]
            path.write_text(json.dumps(state), encoding="utf-8")
            harness.check_phase_state_semantics(path)

            state = json.loads(path.read_text(encoding="utf-8"))
            state["verification"] = ["definitely-not-a-command --nope"]
            path.write_text(json.dumps(state), encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "verification\\[0\\] must start with an allowed command"):
                harness.check_phase_state_semantics(path)

            state["verification"] = ["TODO add concrete verification"]
            path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "verification\\[0\\] must start with an allowed command"):
                harness.check_phase_state_semantics(path)

    def test_phase_state_allows_domain_words_that_look_like_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            base_state = {
                "phase": "execute",
                "approved": True,
                "automation_mode": "manual",
                "auto_selected": [],
                "plan_id": "manual-plan",
                "allowed_paths": ["scripts/harness.py"],
                "state_path": ".planning/STATE.md",
                "plan_path": ".planning/phases/01/PLAN.md",
                "checkpoint_path": ".planning/phases/01/CHECKPOINTS.md",
                "current_checkpoint": "CP-01",
                "next_action": "Run verification.",
                "approved_by": "user",
                "approved_at": "2026-05-15T00:00:00Z",
                "updated_at": "2026-05-15T00:00:00Z",
                "updated_by": "test",
            }
            for verification in (
                "Inspect todo-list component behavior",
                "Review manual test plan results in docs/verification.md",
                "Review placeholder replacement in docs",
            ):
                state = dict(base_state)
                state["verification"] = [verification]
                path.write_text(json.dumps(state), encoding="utf-8")
                harness.check_phase_state_semantics(path)

    def test_phase_state_execute_accepts_manual_mode_with_scope_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            path.write_text(
                json.dumps(
                    {
                        "phase": "execute",
                        "approved": True,
                        "automation_mode": "manual",
                        "auto_selected": [],
                        "plan_id": "manual-plan",
                        "allowed_paths": ["scripts/harness.py"],
                        "verification": ["python3 -m unittest scripts/test_harness.py"],
                        "state_path": ".planning/STATE.md",
                        "plan_path": ".planning/phases/04-template-consumer-onboarding/04-01-PLAN.md",
                        "checkpoint_path": ".planning/phases/04-template-consumer-onboarding/04-CHECKPOINTS.md",
                        "current_checkpoint": "CP-04-02",
                        "next_action": "Run verification.",
                        "approved_by": "user",
                        "approved_at": "2026-05-15T00:00:00Z",
                        "updated_at": "2026-05-15T00:00:00Z",
                        "updated_by": "test",
                    }
                ),
                encoding="utf-8",
            )

            harness.check_phase_state_semantics(path)

    def test_hydration_and_simple_workflows_document_low_reasoning_limits(self) -> None:
        root = harness.repo_root()
        commands = (root / ".roo/commands/README.md").read_text(encoding="utf-8")
        hydration = (root / ".roo/skills/workflow-planning-hydration/SKILL.md").read_text(encoding="utf-8")
        simple = (root / ".roo/skills/workflow-simple-task/SKILL.md").read_text(encoding="utf-8")

        for phrase in ("/phase-discuss planning-hydration", "/simple", "/review", "/doctor"):
            self.assertIn(phrase, commands)
        for phrase in (
            "Pass 0",
            "PROJECT.md",
            "STATE.md",
            "ROADMAP.md",
            ".planning/codebase/STRUCTURE.md",
            "00-CHECKPOINTS.md",
            "stop for review",
        ):
            self.assertIn(phrase, hydration)
        for phrase in (
            "one or two known files",
            "no application code edits",
            "without subtask tooling",
        ):
            self.assertIn(phrase, simple)

    def test_phase_commands_are_present_and_manifest_owned(self) -> None:
        root = harness.repo_root()
        manifest_entries = {entry.path.as_posix(): entry for entry in harness.load_manifest(root)}
        required_commands = {
            ".roo/commands/fsd-phase.md",
            ".roo/commands/phase-discuss.md",
            ".roo/commands/phase-plan.md",
            ".roo/commands/phase-execute.md",
        }

        missing_files = [path for path in sorted(required_commands) if not (root / path).exists()]
        missing_manifest = [path for path in sorted(required_commands) if path not in manifest_entries]
        wrong_policy = [
            path
            for path in sorted(required_commands)
            if path in manifest_entries and manifest_entries[path].policy != "harness-owned"
        ]

        self.assertEqual([], missing_files)
        self.assertEqual([], missing_manifest)
        self.assertEqual([], wrong_policy)

    def test_all_command_files_except_readme_are_manifest_owned(self) -> None:
        root = harness.repo_root()
        manifest_entries = {entry.path.as_posix(): entry for entry in harness.load_manifest(root)}
        command_paths = {
            path.relative_to(root).as_posix()
            for path in (root / ".roo/commands").glob("*.md")
            if path.name != "README.md"
        }

        missing_manifest = sorted(command_paths - set(manifest_entries))
        wrong_policy = sorted(
            path for path in command_paths if path in manifest_entries and manifest_entries[path].policy != "harness-owned"
        )
        wrong_source = sorted(
            path
            for path in command_paths
            if path in manifest_entries and manifest_entries[path].source.as_posix() != path
        )

        self.assertEqual([], missing_manifest)
        self.assertEqual([], wrong_policy)
        self.assertEqual([], wrong_source)

    def test_phase_commands_have_explicit_subtask_first_routing(self) -> None:
        root = harness.repo_root()
        rules = (root / ".roo/rules-orchestrator/rules.md").read_text(encoding="utf-8")
        routing_rows = self.parse_routing_table(rules)
        expected_rows = {
            "/phase-discuss": ("`workflow-phase-gate`", "`architect`"),
            "/phase-plan": ("`workflow-phase-gate`", "`architect`"),
            "/phase-execute": ("`workflow-phase-gate`", "`orchestrator` then owning mode"),
            "/fsd-phase": ("`workflow-phase-gate`", "`orchestrator` then owning modes"),
        }

        for command, (workflow, owner) in expected_rows.items():
            self.assertIn(command, routing_rows)
            self.assertEqual(workflow, routing_rows[command]["workflow"])
            self.assertEqual(owner, routing_rows[command]["owner"])
        self.assertLess(routing_rows["/phase-execute"]["index"], routing_rows["harness request"]["index"])
        self.assertLess(routing_rows["/fsd-phase"]["index"], routing_rows["harness request"]["index"])
        self.assertIn("Phase command rows do not override Subtask-First Execution", rules)
        for phrase in ("`phase=execute`", "`approved=true`", "`plan_id`", "`allowed_paths`", "`verification`"):
            self.assertIn(phrase, rules)
        self.assertIn("If `new_task` is unavailable, output the handoff packet and stop", rules)

    def parse_routing_table(self, rules: str) -> dict[str, dict[str, object]]:
        rows: dict[str, dict[str, object]] = {}
        for index, line in enumerate(rules.splitlines()):
            if not line.startswith("| "):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) != 4 or cells[0] in {"User entry", "---"}:
                continue
            rows[cells[0].strip("`")] = {
                "index": index,
                "scope": cells[1],
                "workflow": cells[2],
                "owner": cells[3],
            }
        return rows

    def test_phase_command_files_keep_thin_workflow_contract(self) -> None:
        root = harness.repo_root()
        expected_modes = {
            "fsd-phase.md": "orchestrator",
            "phase-discuss.md": "architect",
            "phase-plan.md": "architect",
            "phase-execute.md": "orchestrator",
        }
        required_phrases = {
            "fsd-phase.md": [
                "Use the `workflow-phase-gate` skill for $ARGUMENTS.",
                "not an inline implementation command",
                "If `new_task` is unavailable, output the handoff packet and stop.",
            ],
            "phase-discuss.md": [
                "Use the `workflow-phase-gate` skill for $ARGUMENTS.",
                "Do not edit implementation files.",
            ],
            "phase-plan.md": [
                "Use the `workflow-phase-gate` skill for $ARGUMENTS.",
                "Do not implement behavior changes.",
                "Do not edit implementation files.",
            ],
            "phase-execute.md": [
                "Use the `workflow-phase-gate` skill for $ARGUMENTS.",
                "Do not implement inline from orchestrator.",
                "If `new_task` is unavailable, output the handoff packet and stop.",
            ],
        }

        for filename, mode in expected_modes.items():
            text = (root / ".roo/commands" / filename).read_text(encoding="utf-8")
            self.assertRegex(text, rf"(?m)^mode:\s*{mode}\s*$")
            self.assertRegex(text, r"(?m)^argument-hint:\s*.+$")
            for phrase in required_phrases[filename]:
                self.assertIn(phrase, text)

    def test_root_readme_documents_phase_commands(self) -> None:
        readme = (harness.repo_root() / "README.md").read_text(encoding="utf-8")

        for phrase in (
            "discuss -> plan -> execute -> done",
            "지원 환경과 명령 표기",
            "사용 시나리오 빠른 선택",
            "클라이언트별 커맨드 모델",
            "core-only 하네스",
            "OpenCode 전용 하네스",
            "Roo + OpenCode 동시 지원",
            "skill pack은 플러그인입니다",
            "source repository에는 `.agents/skills/**`가 없어도 정상입니다",
            "OpenCode adapter는 의도적으로 phase primitive만 제공합니다",
            "repository-evidence-research",
            "skill-plugin-composition",
            "verification-contract",
            "integration-boundary",
            "tech-csharp",
            "tech-mssql",
            "workflow-etl",
            "tech-react",
            "tech-typescript",
            "tech-tailwind",
        ):
            self.assertIn(phrase, readme)

    def test_root_readme_documents_user_use_cases_prompts_and_platform_variants(self) -> None:
        readme = (harness.repo_root() / "README.md").read_text(encoding="utf-8")

        for phrase in (
            "Windows PowerShell",
            "py -3 scripts/harness.py check",
            "`scripts/codex-cloud-setup.sh`는 Linux/macOS shell용입니다",
            "새 프로젝트에 기본 가드레일만 넣기",
            "OpenCode만 쓰기",
            "버그 진단",
            "보안/권한/secret 변경",
            "하네스 업그레이드",
            "`/phase-discuss`",
            "`.opencode/commands/execute.md`",
            "OpenCode에서 버그 수정",
            "Windows 사용자에게 적용",
            "active phase docs는 다음 순서로 해석합니다",
            "workflow-debugging,workflow-tdd",
        ):
            self.assertIn(phrase, readme)

    def test_opencode_commands_document_core_adapter_contract(self) -> None:
        root = harness.repo_root()
        required = {
            "discuss.md": [
                "Use this command for `phase=discuss` work only.",
                "Preflight checklist:",
                "Resolve active phase docs in this order:",
                "Output checklist:",
                "Read `.scratch/phase-state.json` last.",
                "application-code edits",
            ],
            "plan.md": [
                "Use this command for `phase=plan` work only.",
                "Preflight checklist:",
                "Plan output checklist:",
                "allowed path candidates",
                "verification candidates",
                "Request execute approval instead of self-approving.",
            ],
            "execute.md": [
                "Use this command only after the live gate is already approved.",
                "Preflight checklist:",
                "Execution output checklist:",
                "non-empty `allowed_paths`",
                "non-empty `verification`",
                "Run `python3 scripts/harness.py check --worktree` before committing.",
            ],
            "done.md": [
                "Use this command to close a completed phase.",
                "Preflight checklist:",
                "Done output checklist:",
                "post-completion audit only",
                "Confirm verification evidence exists.",
                "Run `python3 scripts/harness.py check --worktree` before marking done.",
            ],
        }

        for filename, phrases in required.items():
            text = (root / ".opencode/commands" / filename).read_text(encoding="utf-8")
            for phrase in phrases:
                self.assertIn(phrase, text, filename)

    def test_readme_documents_unified_profiles_and_db_flag(self) -> None:
        readme = (harness.repo_root() / "README.md").read_text(encoding="utf-8")

        for phrase in (
            "`.planning/**`은 canonical memory입니다",
            "`.scratch/phase-state.json`은 현재 작업을 열거나 막는 live gate일 뿐입니다",
            "python3 scripts/harness.py init --target /path/to/project --adapters none",
            "python3 scripts/harness.py init --target /path/to/project --adapters opencode",
            "python3 scripts/harness.py init --target /path/to/project --adapters both",
            "python3 scripts/harness.py check --target /path/to/project --adapter opencode",
            "python3 scripts/harness.py check --worktree",
            "python3 scripts/release_smoke_test.py",
            "push 전에 서브에이전트 적대적 리뷰를 해줘",
            "`dotnet-etl`",
            "`react-web`",
            "`--db`",
            "`--db mssql` 또는 `--db postgresql`",
            "workflow-tdd",
            "workflow-debugging",
            "workflow-code-review",
            "workflow-skill-authoring",
            "workflow-security-review",
        ):
            self.assertIn(phrase, readme)

    def test_core_docs_are_client_neutral_and_document_done_audit_mode(self) -> None:
        root = harness.repo_root()
        phase_gate = (root / "docs/phase-gate-harness.md").read_text(encoding="utf-8")
        protocol = (root / "docs/protocol-spec.md").read_text(encoding="utf-8")

        for phrase in (
            "Roo and OpenCode are adapters over the same state machine",
            "What Adapters Can Enforce",
            "What Adapters Cannot Enforce Alone",
            "`check --worktree` also accepts `phase=done` for post-completion audit work",
        ):
            self.assertIn(phrase, phase_gate)
        for phrase in (
            "Resolve active phase docs deterministically",
            "OpenCode intentionally ships phase primitives",
            "Workflow specialization comes from installed `.agents/skills/**` packs",
        ):
            self.assertIn(phrase, protocol)

    def test_init_installs_phase_commands_from_manifest_sources(self) -> None:
        root = harness.repo_root()
        command_paths = [
            ".roo/commands/fsd-phase.md",
            ".roo/commands/phase-discuss.md",
            ".roo/commands/phase-plan.md",
            ".roo/commands/phase-execute.md",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target)])

            for path in command_paths:
                self.assertEqual(
                    (root / path).read_text(encoding="utf-8"),
                    (target / path).read_text(encoding="utf-8"),
                )

    def add_installed_file(self, target: Path, relative_path: str, path: Path) -> None:
        installed_path = target / ".harness/installed-manifest.json"
        installed = json.loads(installed_path.read_text(encoding="utf-8"))
        installed["files"][relative_path] = {
            "policy": "harness-owned",
            "sha256": harness.file_hash(path),
        }
        installed_path.write_text(json.dumps(installed), encoding="utf-8")


class ManifestProfileEntriesTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((REPO_ROOT / "harness/manifest.json").read_text(encoding="utf-8"))
        self.entries = self.manifest["files"]

    def _entry(self, path):
        for e in self.entries:
            if e["path"] == path:
                return e
        self.fail(f"manifest entry missing: {path}")

    def test_legacy_dotnet_etl_mssql_profile_doc_removed(self):
        paths = {e["path"] for e in self.entries}
        self.assertNotIn("docs/profiles/dotnet-etl-mssql.md", paths)

    def test_new_profile_docs_present(self):
        for path in (
            "docs/profiles/dotnet-etl.md",
            "docs/profiles/python-etl.md",
            "docs/profiles/react-web.md",
        ):
            e = self._entry(path)
            self.assertEqual(
                e["owner"], f"profile:{path.split('/')[-1].removesuffix('.md')}"
            )

    def test_dotnet_etl_etl_tdd_installs_into_roo_and_opencode(self):
        roo = self._entry(".roo/rules-tdd-code/dotnet-etl-etl-tdd.md")
        self.assertEqual(roo["profile"], "dotnet-etl")
        self.assertEqual(roo["adapter"], "roo")
        self.assertEqual(roo["owner"], "profile:dotnet-etl")
        oc = self._entry(".opencode/profile-rules/dotnet-etl-etl-tdd.md")
        self.assertEqual(oc["adapter"], "opencode")
        self.assertEqual(oc["profile"], "dotnet-etl")

    def test_react_web_ui_engineer_extras_targets_ui_engineer_rules_dir(self):
        roo = self._entry(".roo/rules-ui-engineer/react-web-ui-engineer-extras.md")
        self.assertEqual(roo["profile"], "react-web")
        self.assertEqual(roo["adapter"], "roo")


class ProfileResolutionTests(unittest.TestCase):
    def test_known_profiles(self):
        from scripts import harness as h
        self.assertEqual(h.KNOWN_PROFILES, {"generic", "dotnet-etl", "python-etl", "react-web"})

    def test_legacy_alias_maps(self):
        from scripts import harness as h
        self.assertEqual(h.LEGACY_PROFILE_ALIASES["dotnet-etl-mssql"], "dotnet-etl")

    def test_default_packs_for_dotnet_etl(self):
        from scripts import harness as h
        packs = h.default_packs_for_profile("dotnet-etl")
        self.assertEqual(set(packs), {"workflow-core", "workflow-etl", "tech-csharp"})

    def test_default_packs_for_python_etl(self):
        from scripts import harness as h
        packs = h.default_packs_for_profile("python-etl")
        self.assertEqual(set(packs), {"workflow-core", "workflow-etl", "tech-python"})

    def test_default_packs_for_react_web(self):
        from scripts import harness as h
        packs = h.default_packs_for_profile("react-web")
        self.assertEqual(
            set(packs),
            {"workflow-core", "workflow-web-development", "tech-react", "tech-typescript", "tech-tailwind"},
        )

    def test_db_packs_mssql(self):
        from scripts import harness as h
        self.assertEqual(set(h.db_packs("mssql")), {"tech-mssql", "workflow-db-context"})

    def test_db_packs_postgresql(self):
        from scripts import harness as h
        self.assertEqual(set(h.db_packs("postgresql")), {"tech-postgresql", "workflow-db-context"})

    def test_db_packs_none_returns_empty(self):
        from scripts import harness as h
        self.assertEqual(h.db_packs("none"), [])

    def test_db_packs_unknown_raises(self):
        from scripts import harness as h
        with self.assertRaises(ValueError):
            h.db_packs("mysql")

    def test_normalize_profiles_handles_legacy_alias(self):
        from scripts import harness as h
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            result = h.normalize_profiles(["dotnet-etl-mssql", "generic"])
        self.assertEqual(result, ["dotnet-etl", "generic"])
        self.assertIn("deprecated", buf.getvalue())

    def test_normalize_profiles_rejects_unknown(self):
        from scripts import harness as h
        with self.assertRaises(SystemExit):
            h.normalize_profiles(["bogus"])

    def test_normalize_profiles_passes_known_through(self):
        from scripts import harness as h
        self.assertEqual(h.normalize_profiles(["react-web", "generic"]), ["react-web", "generic"])


class DbFlagTests(unittest.TestCase):
    def test_init_with_db_mssql_adds_db_packs(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                    "init",
                    "--target", str(target),
                    "--adapters", "roo",
                    "--profiles", "dotnet-etl",
                    "--db", "mssql",
                ],
                check=True,
            )
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("tech-mssql", installed["packs"])
            self.assertIn("workflow-db-context", installed["packs"])

    def test_init_with_db_postgresql_adds_db_packs(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                    "init",
                    "--target", str(target),
                    "--adapters", "roo",
                    "--profiles", "python-etl",
                    "--db", "postgresql",
                ],
                check=True,
            )
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("tech-postgresql", installed["packs"])
            self.assertIn("workflow-db-context", installed["packs"])

    def test_init_db_none_does_not_add_db_packs(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                    "init",
                    "--target", str(target),
                    "--adapters", "roo",
                    "--profiles", "dotnet-etl",
                    "--db", "none",
                ],
                check=True,
            )
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("tech-mssql", installed["packs"])
            self.assertNotIn("tech-postgresql", installed["packs"])

    def test_init_db_with_generic_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            result = subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                    "init",
                    "--target", str(target),
                    "--adapters", "roo",
                    "--profiles", "generic",
                    "--db", "mssql",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("ignored", (result.stderr + result.stdout).lower())
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("tech-mssql", installed["packs"])

    def test_init_without_db_omits_db_packs(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                    "init",
                    "--target", str(target),
                    "--adapters", "roo",
                    "--profiles", "dotnet-etl",
                ],
                check=True,
            )
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("tech-mssql", installed["packs"])
            self.assertNotIn("tech-postgresql", installed["packs"])


class RoomodesWriterTests(unittest.TestCase):
    def test_read_baseline_returns_eight_base_modes(self):
        from scripts.lib import roomodes_writer
        baseline = roomodes_writer.read(REPO_ROOT / ".roomodes")
        self.assertEqual(
            [m["slug"] for m in baseline.base_modes],
            [
                "orchestrator",
                "architect",
                "tdd-code",
                "diagnose",
                "review",
                "docs-issues",
                "ops-observability",
                "harness-maintainer",
            ],
        )
        self.assertEqual(baseline.profile_modes, [])

    def test_set_profile_modes_round_trip(self):
        from scripts.lib import roomodes_writer
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / ".roomodes"
            target.write_text((REPO_ROOT / ".roomodes").read_text(encoding="utf-8"), encoding="utf-8")
            ui_engineer = {"slug": "ui-engineer", "name": "UI Engineer"}
            roomodes_writer.set_profile_modes(target, [ui_engineer])
            again = roomodes_writer.read(target)
            self.assertEqual(len(again.base_modes), 8)
            self.assertEqual([m["slug"] for m in again.profile_modes], ["ui-engineer"])
            roomodes_writer.set_profile_modes(target, [])
            again2 = roomodes_writer.read(target)
            self.assertEqual(again2.profile_modes, [])
            self.assertEqual(len(again2.base_modes), 8)

    def test_unmanaged_modes_preserved(self):
        from scripts.lib import roomodes_writer
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / ".roomodes"
            target.write_text(json.dumps({"customModes": [
                {"slug": "orchestrator"},
                {"slug": "tdd-code"},
                {"slug": "my-custom-mode", "name": "Project-owned"},
            ]}), encoding="utf-8")
            c = roomodes_writer.read(target)
            self.assertEqual([m["slug"] for m in c.unmanaged_modes], ["my-custom-mode"])
            roomodes_writer.set_profile_modes(target, [{"slug": "ui-engineer"}])
            c2 = roomodes_writer.read(target)
            self.assertEqual([m["slug"] for m in c2.unmanaged_modes], ["my-custom-mode"])


class RoomodesProfileSyncTests(unittest.TestCase):
    def test_react_web_install_adds_ui_engineer(self):
        from scripts.lib import roomodes_writer
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "init", "--target", str(target),
                 "--adapters", "roo", "--profiles", "react-web"],
                check=True,
            )
            roomodes = json.loads((target / ".roomodes").read_text(encoding="utf-8"))
            slugs = [m["slug"] for m in roomodes["customModes"]]
            self.assertIn("ui-engineer", slugs)
            self.assertEqual(slugs[:8], list(roomodes_writer.BASE_MODE_SLUGS))

    def test_dotnet_etl_install_does_not_add_ui_engineer(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "init", "--target", str(target),
                 "--adapters", "roo", "--profiles", "dotnet-etl"],
                check=True,
            )
            roomodes = json.loads((target / ".roomodes").read_text(encoding="utf-8"))
            slugs = [m["slug"] for m in roomodes["customModes"]]
            self.assertNotIn("ui-engineer", slugs)

    def test_opencode_only_install_does_not_create_roomodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "init", "--target", str(target),
                 "--adapters", "opencode", "--profiles", "react-web"],
                check=True,
            )
            self.assertFalse((target / ".roomodes").exists())

    def test_upgrade_removes_ui_engineer_when_react_web_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run([sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                            "init", "--target", str(target),
                            "--adapters", "roo", "--profiles", "react-web"], check=True)
            # confirm ui-engineer present
            slugs_before = [m["slug"] for m in json.loads((target / ".roomodes").read_text())["customModes"]]
            self.assertIn("ui-engineer", slugs_before)
            # upgrade to generic
            subprocess.run([sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                            "upgrade", "--target", str(target),
                            "--profiles", "generic"], check=True)
            slugs_after = [m["slug"] for m in json.loads((target / ".roomodes").read_text())["customModes"]]
            self.assertNotIn("ui-engineer", slugs_after)


class OpencodeCommandsProfileRulesTests(unittest.TestCase):
    def test_each_command_references_profile_rules_dir(self):
        for name in ("discuss.md", "plan.md", "execute.md", "done.md"):
            text = (REPO_ROOT / ".opencode/commands" / name).read_text(encoding="utf-8")
            self.assertIn(".opencode/profile-rules/", text, msg=name)
            self.assertIn("alphabetical", text.lower(), msg=name)


class InstallerInteractiveTests(unittest.TestCase):
    def test_profile_options_are_unified(self):
        from scripts import install_harness
        slugs = [opt[0] for opt in install_harness.PROFILE_OPTIONS]
        self.assertEqual(set(slugs), {"generic", "dotnet-etl", "python-etl", "react-web"})

    def test_db_options_include_none(self):
        from scripts import install_harness
        slugs = [opt[0] for opt in install_harness.DB_OPTIONS]
        self.assertEqual(set(slugs), {"mssql", "postgresql", "none"})

    def test_prompt_db_returns_none_for_generic_without_prompting(self):
        from scripts import install_harness
        with mock.patch("builtins.input", side_effect=AssertionError("should not prompt")):
            self.assertEqual(install_harness.prompt_db("generic"), "none")

    def test_legacy_preset_names_removed(self):
        from scripts import install_harness
        self.assertFalse(hasattr(install_harness, "PROFILE_PRESETS"))
        self.assertFalse(hasattr(install_harness, "resolve_profile_preset"))

    def test_run_interactive_dry_run_resolves_dotnet_etl_with_mssql(self):
        from scripts import install_harness
        with tempfile.TemporaryDirectory() as tmp:
            # tmp path, adapter choice "1" (roo), profile choice "2" (dotnet-etl),
            # db choice "1" (mssql), then "" for additional packs.
            answers = iter([tmp, "1", "2", "1", ""])
            with mock.patch("builtins.input", side_effect=lambda *a, **k: next(answers)):
                plan = install_harness.run_interactive_dry_run()
            self.assertEqual(plan["profile"], "dotnet-etl")
            self.assertEqual(plan["db"], "mssql")
            self.assertIn("tech-mssql", plan["packs"])
            self.assertIn("workflow-db-context", plan["packs"])


class UpgradeMigrationTests(unittest.TestCase):
    def test_upgrade_migrates_dotnet_etl_mssql_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            # Bootstrap a working install first so the upgrade has files to
            # operate on; then forcibly rewrite the manifest to look like
            # a pre-migration v0.6.0 install.
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "init", "--target", str(target),
                 "--adapters", "roo", "--profiles", "dotnet-etl"],
                check=True,
            )
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["init_options"]["profiles"] = ["dotnet-etl-mssql"]
            installed["profiles"] = ["dotnet-etl-mssql"]
            # Strip the auto-added db packs so we can verify migration adds them.
            installed["packs"] = ["workflow-core", "workflow-etl", "tech-csharp"]
            installed["init_options"]["packs"] = ["workflow-core", "workflow-etl", "tech-csharp"]
            installed_path.write_text(json.dumps(installed), encoding="utf-8")
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "upgrade", "--target", str(target)],
                check=True,
            )
            migrated = json.loads(installed_path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["init_options"]["profiles"], ["dotnet-etl"])
            self.assertEqual(migrated["profiles"], ["dotnet-etl"])
            self.assertIn("tech-mssql", migrated["packs"])
            self.assertIn("workflow-db-context", migrated["packs"])

    def test_upgrade_dry_run_reports_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "init", "--target", str(target),
                 "--adapters", "roo", "--profiles", "dotnet-etl"],
                check=True,
            )
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["init_options"]["profiles"] = ["dotnet-etl-mssql"]
            installed["profiles"] = ["dotnet-etl-mssql"]
            installed_path.write_text(json.dumps(installed), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "upgrade", "--target", str(target), "--dry-run"],
                check=True,
                capture_output=True,
                text=True,
            )
            combined = result.stdout + result.stderr
            self.assertIn("dotnet-etl-mssql", combined)
            self.assertIn("dotnet-etl", combined)

    def test_upgrade_preserves_non_legacy_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "init", "--target", str(target),
                 "--adapters", "roo", "--profiles", "react-web"],
                check=True,
            )
            installed_path = target / ".harness/installed-manifest.json"
            before = json.loads(installed_path.read_text(encoding="utf-8"))
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "upgrade", "--target", str(target)],
                check=True,
            )
            after = json.loads(installed_path.read_text(encoding="utf-8"))
            self.assertEqual(after["init_options"]["profiles"], before["init_options"]["profiles"])
            self.assertEqual(set(after["packs"]), set(before["packs"]))


class CheckProfileSyncTests(unittest.TestCase):
    def test_check_fails_when_ui_engineer_present_without_react_web(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "init", "--target", str(target),
                 "--adapters", "roo", "--profiles", "react-web"], check=True)
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["init_options"]["profiles"] = ["generic"]
            installed["profiles"] = ["generic"]
            installed_path.write_text(json.dumps(installed), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "check", "--target", str(target)],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ui-engineer", result.stdout + result.stderr)

    def test_check_passes_for_clean_react_web_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "init", "--target", str(target),
                 "--adapters", "roo", "--profiles", "react-web"], check=True)
            result = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "check", "--target", str(target)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)


class DoctorOpencodeProfileRulesTests(unittest.TestCase):
    def test_doctor_warns_when_profile_rules_line_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "init", "--target", str(target),
                 "--adapters", "opencode", "--profiles", "dotnet-etl"], check=True)
            execute = target / ".opencode/commands/execute.md"
            text = execute.read_text(encoding="utf-8")
            mangled = "\n".join(
                line for line in text.splitlines()
                if ".opencode/profile-rules/" not in line
            ) + "\n"
            execute.write_text(mangled, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "doctor", "--target", str(target)],
                capture_output=True, text=True)
            self.assertIn("profile-rules", result.stdout + result.stderr)


class StateSubcommandTests(unittest.TestCase):
    def test_state_show_runs(self):
        from pathlib import Path
        import tempfile, json as _json
        root = Path(tempfile.mkdtemp())
        (root / ".planning").mkdir()
        (root / ".scratch").mkdir()
        (root / ".planning/ROADMAP.md").write_text(
            "# R\n\n## Phases\n\n- [ ] **Phase 0: A**\n", encoding="utf-8"
        )
        (root / ".planning/STATE.md").write_text(
            "---\nprogress:\n  total_phases: 1\n  completed_phases: 0\n  percent: 0\n---\n\n"
            "# S\n\n## Current Position\n\n- **Phase**: 0\n",
            encoding="utf-8",
        )
        (root / ".scratch/phase-state.json").write_text(
            _json.dumps({"phase": "discuss", "state_path": ".planning/STATE.md"}),
            encoding="utf-8",
        )

        import harness
        rc = harness.run(["state", "show", "--root", str(root)])
        self.assertEqual(rc, 0)

    def test_state_repair_runs(self):
        from pathlib import Path
        import tempfile, json as _json
        root = Path(tempfile.mkdtemp())
        (root / ".planning").mkdir()
        (root / ".scratch").mkdir()
        (root / ".planning/ROADMAP.md").write_text(
            "# R\n\n## Phases\n\n- [ ] **Phase 0: A**\n", encoding="utf-8"
        )
        (root / ".planning/STATE.md").write_text(
            "---\nprogress:\n  total_phases: 1\n  completed_phases: 0\n  percent: 0\n---\n\n"
            "# S\n\n## Current Position\n\n- **Phase**: 0\n",
            encoding="utf-8",
        )
        (root / ".scratch/phase-state.json").write_text(
            _json.dumps({"phase": "discuss"}), encoding="utf-8"
        )
        import harness
        rc = harness.run(["state", "repair", "--root", str(root)])
        self.assertEqual(rc, 0)
        roadmap = (root / ".planning/ROADMAP.md").read_text(encoding="utf-8")
        self.assertIn("HARNESS:BEGIN managed:roadmap-phases", roadmap)


class SkeletonManagedBlockTests(unittest.TestCase):
    def test_skeleton_roadmap_has_managed_block(self):
        from pathlib import Path
        text = Path("harness/skeleton/clean/.planning/ROADMAP.md").read_text(encoding="utf-8")
        self.assertIn("<!-- HARNESS:BEGIN managed:roadmap-phases v1 -->", text)
        self.assertIn("<!-- HARNESS:END managed:roadmap-phases -->", text)

    def test_skeleton_state_has_managed_block(self):
        from pathlib import Path
        text = Path("harness/skeleton/clean/.planning/STATE.md").read_text(encoding="utf-8")
        self.assertIn("<!-- HARNESS:BEGIN managed:state-current v1 -->", text)
        self.assertIn("<!-- HARNESS:END managed:state-current -->", text)


class ManagedBlockCheckWarningTests(unittest.TestCase):
    def test_check_warns_when_roadmap_missing_managed_block(self):
        import tempfile, io, contextlib
        from pathlib import Path
        import json as _json
        root = Path(tempfile.mkdtemp())
        (root / ".planning").mkdir()
        (root / ".scratch").mkdir()
        (root / ".planning/ROADMAP.md").write_text(
            "# R\n\n## Phases\n\n- [ ] **Phase 0: A**\n", encoding="utf-8"
        )
        (root / ".planning/STATE.md").write_text(
            "---\nprogress:\n  total_phases: 1\n  completed_phases: 0\n  percent: 0\n---\n\n"
            "# S\n\n## Current Position\n\n- **Phase**: 0\n",
            encoding="utf-8",
        )
        (root / ".scratch/phase-state.json").write_text(
            _json.dumps({"phase": "discuss"}), encoding="utf-8"
        )
        from lib.check import managed_block_warnings
        warnings = managed_block_warnings(root)
        codes = {w.code for w in warnings}
        self.assertIn("missing_managed_block", codes)


class LiveFixtureMigrationTests(unittest.TestCase):
    """T0-1 Block D — live ``.scratch/phase-state.json`` was migrated."""

    def test_live_fixture_was_migrated_by_this_slice(self) -> None:
        live = REPO_ROOT / ".scratch" / "phase-state.json"
        # Skip in installed-target contexts where the live fixture is a
        # source-repo concept (heuristic: harness/manifest.json absent).
        if not (REPO_ROOT / "harness" / "manifest.json").exists():
            self.skipTest("not a source-repo checkout (harness/manifest.json absent)")
        state = json.loads(live.read_text(encoding="utf-8"))
        self.assertEqual(state.get("state_schema_version"), 2)
        self.assertEqual(state.get("phase"), "done")


class ChangelogStructureTests(unittest.TestCase):
    """T0-1 (02b-02) — CHANGELOG ### Breaking subsection (Block 0).

    Per plan .planning/phases/02b-hardening/plans/02b-02-T0-1-PLAN.md and
    CONTRACT-PIN §7 (ledger L1, L2, L12 owned by 02b-02 and land in Block 0).
    """

    def _read_changelog(self) -> str:
        return (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    def _breaking_body(self, text: str) -> str:
        # Scan lines from the literal heading '## Unreleased (develop)' to the
        # next '## ' boundary; within that scan, capture the body of the
        # '### Breaking' subsection until the next '### ' or '## ' boundary.
        lines = text.splitlines()
        in_unreleased = False
        in_breaking = False
        body: list[str] = []
        for line in lines:
            if line.startswith("## "):
                if line.strip() == "## Unreleased (develop)":
                    in_unreleased = True
                    in_breaking = False
                    continue
                if in_unreleased:
                    break  # left the Unreleased section
            if not in_unreleased:
                continue
            if line.startswith("### "):
                if line.strip() == "### Breaking":
                    in_breaking = True
                    continue
                else:
                    in_breaking = False
                    continue
            if in_breaking:
                body.append(line)
        return "\n".join(body)

    def test_changelog_unreleased_section_has_breaking_subsection(self) -> None:
        text = self._read_changelog()
        self.assertIn("## Unreleased (develop)", text)
        body = self._breaking_body(text)
        # Body present (string-non-empty) — the seed file is allowed but the
        # T0-1 Block 0 commit MUST populate the body with ledger rows. Any
        # non-comment content is required.
        non_comment = [
            ln for ln in body.splitlines()
            if ln.strip() and not ln.strip().startswith("<!--")
        ]
        self.assertTrue(
            non_comment,
            "### Breaking subsection under ## Unreleased (develop) is empty or only contains HTML comments",
        )

    def test_changelog_breaking_subsection_mentions_done_contract_and_state_schema_version(self) -> None:
        text = self._read_changelog()
        body = self._breaking_body(text)
        self.assertIn("phase=done", body)
        self.assertIn("state_schema_version", body)
        # Ledger L12 — migrator --resume verb mention required.
        self.assertIn("--resume", body)


if __name__ == "__main__":
    unittest.main()
