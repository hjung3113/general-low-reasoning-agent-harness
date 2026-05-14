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


class HarnessToolTests(unittest.TestCase):
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
            json.dumps({"phase": "discuss", "approved": False, "automation_mode": "manual", "auto_selected": []}),
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
                    "allowed_paths": ["scripts/harness.py"],
                    "verification": ["python3 -m unittest scripts/test_harness.py"],
                    "approved_by": "test-fixture",
                    "approved_at": "2026-05-15T00:00:00Z",
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
                "verification-contract",
                "risk-review",
                "data-workflow",
                "integration-boundary",
            ):
                self.assertTrue((target / f".agents/skills/{skill_name}/SKILL.md").exists(), skill_name)
            skill = target / ".agents/skills/skill-plugin-composition/SKILL.md"
            self.assertIn("Skills are composable plugins", skill.read_text(encoding="utf-8"))
            harness.run(["check", "--target", str(target)])

    def test_init_installs_first_action_and_phase_zero_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            harness.run(["init", "--target", str(target)])

            readme = (target / "README.md").read_text(encoding="utf-8")
            state = (target / ".planning/STATE.md").read_text(encoding="utf-8")
            self.assertIn("Fresh target first action", readme)
            self.assertIn("Fresh target first action", state)
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

    def test_init_refuses_to_overwrite_existing_project_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            state = target / ".planning/STATE.md"
            state.parent.mkdir(parents=True)
            state.write_text("existing project memory", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "Refusing to overwrite"):
                harness.run(["init", "--target", str(target)])

            self.assertEqual("existing project memory", state.read_text(encoding="utf-8"))
            self.assertFalse((target / "AGENTS.md").exists())

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

    def test_check_target_reports_stale_managed_guardrails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(["init", "--target", str(target)])
            (target / "AGENTS.md").write_text("locally shortened agents file", encoding="utf-8")
            (target / "README.md").write_text("locally shortened readme", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "Required guardrail phrases missing"):
                harness.run(["check", "--target", str(target)])

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

    def test_allowed_paths_use_exact_files_and_directory_prefixes(self) -> None:
        allowed = [".roo/", "README.md"]
        blocked = [".db-context/"]

        self.assertTrue(harness.path_allowed(".roo/skills/workflow-phase-gate/SKILL.md", allowed, blocked))
        self.assertTrue(harness.path_allowed("README.md", allowed, blocked))
        self.assertFalse(harness.path_allowed("README.md.bak", allowed, blocked))
        self.assertFalse(harness.path_allowed(".db-context/latest.json", allowed, blocked))

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
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "execute approval requires"):
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
                        "approved_by": "user",
                        "approved_at": "2026-05-15T00:00:00Z",
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
            "Core only:",
            "OpenCode only:",
            "Roo and OpenCode:",
            "Workflow skills are composable plugins",
            "repository-evidence-research",
            "skill-plugin-composition",
            "verification-contract",
            "integration-boundary",
        ):
            self.assertIn(phrase, readme)

    def test_root_readme_documents_general_install_check_and_upgrade_hardening(self) -> None:
        readme = (harness.repo_root() / "README.md").read_text(encoding="utf-8")

        for phrase in (
            "`.planning/**` is canonical project memory",
            "`.scratch/phase-state.json` is only the live gate",
            "python3 scripts/harness.py init --target /path/to/project --adapters none",
            "python3 scripts/harness.py init --target /path/to/project --adapters opencode",
            "python3 scripts/harness.py check --target /path/to/project --adapter opencode",
            "Modified harness-owned files are written to `.harness/conflicts/**`",
            "Do not hard-code project categories",
        ):
            self.assertIn(phrase, readme)

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


if __name__ == "__main__":
    unittest.main()
