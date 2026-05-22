"""T0-5 preservation + paused-phase + JSON-refuse tests for state_repair.

Plan: .planning/phases/02b-hardening/plans/02b-06-T0-5-PLAN.md (Task 3 list).
Contract: CONTRACT-PIN.md §5.1 (load_state_json wrap), §6.1 (.bak filename),
§4 (exit 5 = EXIT_UNPARSEABLE_JSON).

This file is NEW per the plan; the pre-existing scripts/test_state_repair.py
stays untouched except for any required regression adjustments per Task 9.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import state_repair  # noqa: E402
from lib.state_repair import (  # noqa: E402
    RepairRefusedError,
    canonical_state_current_payload,
    repair,
)


ROADMAP_WITH_BLOCK = """# ROADMAP

## Goals

Build the harness. **Bold** text with `code spans`.

## Phases

<!-- HARNESS:BEGIN managed:roadmap-phases v1 -->
- [x] **Phase 0: A**
- [ ] **Phase 1: B**
<!-- HARNESS:END managed:roadmap-phases -->

## Notes

Free-form notes with `code` and **emphasis**.
"""

STATE_WITH_BLOCK = (
    "---\nprogress:\n  total_phases: 2\n  completed_phases: 1\n  percent: 50\n---\n\n"
    "# S\n\n"
    "<!-- HARNESS:BEGIN managed:state-current v1 -->\n"
    "## Current Position\n\n- **Phase**: 1 - B\n\n"
    "## Active Checkpoint\n\n- **Checkpoint**: CP-01-01\n"
    "<!-- HARNESS:END managed:state-current -->\n"
)


def _make_root(
    *,
    roadmap_text: str = ROADMAP_WITH_BLOCK,
    state_text: str = STATE_WITH_BLOCK,
    phase_state: dict | str | None = None,
) -> Path:
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".planning").mkdir()
    (tmp / ".scratch").mkdir()
    (tmp / ".harness").mkdir()
    (tmp / ".planning/ROADMAP.md").write_text(roadmap_text, encoding="utf-8")
    (tmp / ".planning/STATE.md").write_text(state_text, encoding="utf-8")
    if phase_state is None:
        phase_state = {"phase": "discuss"}
    if isinstance(phase_state, str):
        (tmp / ".scratch/phase-state.json").write_text(phase_state, encoding="utf-8")
    else:
        (tmp / ".scratch/phase-state.json").write_text(
            json.dumps(phase_state), encoding="utf-8"
        )
    return tmp


class PreservationTests(unittest.TestCase):
    def test_preserves_content_above_phases_block_verbatim(self) -> None:
        root = _make_root()
        before = (root / ".planning/ROADMAP.md").read_text(encoding="utf-8")
        repair(root)
        after = (root / ".planning/ROADMAP.md").read_text(encoding="utf-8")
        # The "## Goals\n\n... " section above ## Phases must be byte-identical.
        goals_before = before.split("## Phases")[0]
        goals_after = after.split("## Phases")[0]
        self.assertEqual(goals_before, goals_after)
        self.assertIn("**Bold** text with `code spans`", after)

    def test_preserves_content_below_phases_block_verbatim(self) -> None:
        root = _make_root()
        repair(root)
        after = (root / ".planning/ROADMAP.md").read_text(encoding="utf-8")
        # Everything from "## Notes" onwards must survive byte-for-byte.
        self.assertIn(
            "## Notes\n\nFree-form notes with `code` and **emphasis**.",
            after,
        )

    def test_repair_writes_bak_under_dot_harness_not_dot_planning(self) -> None:
        # Force a state-payload diff by injecting a checkpoint in phase-state.
        # The pre-existing STATE.md block has no Checkpoint file line, so
        # threading "checkpoint_path" into canonical_state_current_payload
        # will rewrite the block payload — which triggers the .bak write.
        root = _make_root(
            phase_state={
                "phase": "discuss",
                "current_checkpoint": "CP-09-99",
                "checkpoint_path": ".planning/phases/09-test/CHECKPOINTS.md",
            }
        )
        report = repair(root)
        # No legacy .bak alongside the source.
        self.assertFalse((root / ".planning/ROADMAP.md.bak").exists())
        self.assertFalse((root / ".planning/STATE.md.bak").exists())
        backups_dir = root / ".harness" / "backups"
        self.assertTrue(
            backups_dir.is_dir(),
            f"backups dir missing; repair report={report!r}",
        )
        baks = list(backups_dir.glob("*.pre-repair.*.bak"))
        self.assertGreaterEqual(
            len(baks), 1, f"expected at least one backup, got {baks}"
        )
        # Filename grammar: CONTRACT-PIN §6.1.
        for bak in baks:
            self.assertTrue(bak.name.endswith(".bak"))
            self.assertIn(".pre-repair.", bak.name)


class MalformedJsonRefusalTests(unittest.TestCase):
    def test_repair_with_malformed_phase_state_json_refuses_and_does_not_rewrite(
        self,
    ) -> None:
        root = _make_root(phase_state="{not json")
        roadmap_path = root / ".planning/ROADMAP.md"
        state_path = root / ".planning/STATE.md"
        roadmap_before = roadmap_path.read_bytes()
        state_before = state_path.read_bytes()
        with self.assertRaises(RepairRefusedError):
            repair(root)
        # Pre-existing files unchanged.
        self.assertEqual(roadmap_path.read_bytes(), roadmap_before)
        self.assertEqual(state_path.read_bytes(), state_before)
        # No backup written either (refusal precedes any write).
        backups_dir = root / ".harness" / "backups"
        if backups_dir.exists():
            self.assertEqual(list(backups_dir.glob("*.bak")), [])

    def test_refusal_diagnostic_mentions_recovery_path(self) -> None:
        root = _make_root(phase_state="{not json")
        try:
            repair(root)
        except RepairRefusedError as exc:
            self.assertIn(
                "fix the JSON or restore from .harness/backups/".lower(),
                str(exc).lower(),
            )
        else:  # pragma: no cover
            self.fail("RepairRefusedError not raised")


class PausedPhasesTests(unittest.TestCase):
    def test_paused_phases_subsection_emitted_when_phase_state_lists_them(
        self,
    ) -> None:
        root = _make_root(
            phase_state={
                "phase": "discuss",
                "paused_phases": [
                    {"slug": "02-skill-pack-expansion", "paused_since": "2026-05-12"}
                ],
            }
        )
        repair(root)
        state_text = (root / ".planning/STATE.md").read_text(encoding="utf-8")
        self.assertIn("### Paused Phases", state_text)
        self.assertIn(
            "- 02-skill-pack-expansion (paused since 2026-05-12)",
            state_text,
        )

    def test_paused_phases_round_trip_no_drift(self) -> None:
        root = _make_root(
            phase_state={
                "phase": "discuss",
                "paused_phases": [
                    {"slug": "02-skill-pack-expansion", "paused_since": "2026-05-12"}
                ],
            }
        )
        repair(root)
        first = (root / ".planning/STATE.md").read_text(encoding="utf-8")
        report = repair(root)
        second = (root / ".planning/STATE.md").read_text(encoding="utf-8")
        self.assertEqual(first, second)
        self.assertEqual(report.files_updated, [])

    def test_paused_phases_absent_when_phase_state_has_none(self) -> None:
        root = _make_root(phase_state={"phase": "discuss"})
        repair(root)
        state_text = (root / ".planning/STATE.md").read_text(encoding="utf-8")
        self.assertNotIn("### Paused Phases", state_text)


class DuplicateSlugTests(unittest.TestCase):
    def test_duplicate_managed_block_slug_raises_graceful_diagnostic(self) -> None:
        duplicate_state = (
            "---\nprogress:\n  total_phases: 1\n  completed_phases: 0\n  percent: 0\n---\n\n"
            "# S\n\n"
            "<!-- HARNESS:BEGIN managed:state-current v1 -->\n"
            "## Current Position\n\n- **Phase**: 0\n"
            "<!-- HARNESS:END managed:state-current -->\n"
            "\n"
            "<!-- HARNESS:BEGIN managed:state-current v1 -->\n"
            "## Current Position\n\n- **Phase**: 0\n"
            "<!-- HARNESS:END managed:state-current -->\n"
        )
        root = _make_root(state_text=duplicate_state)
        state_before = (root / ".planning/STATE.md").read_bytes()
        with self.assertRaises(RepairRefusedError) as ctx:
            repair(root)
        self.assertIn("duplicate managed block 'state-current'", str(ctx.exception))
        self.assertEqual((root / ".planning/STATE.md").read_bytes(), state_before)


class CliExitCodeTests(unittest.TestCase):
    def test_state_repair_exits_5_on_malformed_phase_state_json(self) -> None:
        import io

        from lib import state_cli
        from lib.exitcodes import EXIT_UNPARSEABLE_JSON

        root = _make_root(phase_state="{not json")
        buf = io.StringIO()
        rc = state_cli.run_repair(root=root, stream=buf)
        self.assertEqual(rc, EXIT_UNPARSEABLE_JSON)
        combined = buf.getvalue().lower()
        self.assertIn("fix the json or restore from .harness/backups/", combined)


class SkeletonGitignoreTests(unittest.TestCase):
    def test_skeleton_gitignore_contains_harness_backups_path(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        gitignore = repo_root / "harness" / "skeleton" / "clean" / ".gitignore"
        lines = gitignore.read_text(encoding="utf-8").splitlines()
        self.assertIn(".harness/backups/", lines)


class RapidRepairUniquenessTests(unittest.TestCase):
    """T0-5-M1: rapid back-to-back repairs MUST produce unique `.bak` names.

    Collisions would either silently overwrite a recent backup or trip the
    O_EXCL refusal and abort an otherwise valid repair. Either is a data
    hazard. With nanosecond+pid timestamping plus a 3-retry loop, N=50
    sequential calls inside one process should always succeed and yield
    50 distinct files.
    """

    def test_rapid_repeated_repairs_produce_unique_backups(self):
        root = _make_root(
            phase_state={
                "phase": "discuss",
                "current_checkpoint": "CP-09-99",
                "checkpoint_path": ".planning/phases/09-test/CHECKPOINTS.md",
            }
        )
        # The first repair rewrites STATE.md; subsequent repairs are no-ops
        # unless we keep nudging the payload. Easiest is to keep mutating
        # the phase-state checkpoint between calls so each repair has a
        # diff to flush.
        backups_dir = root / ".harness" / "backups"
        for i in range(50):
            (root / ".scratch/phase-state.json").write_text(
                json.dumps({
                    "phase": "discuss",
                    "current_checkpoint": f"CP-09-{i:02d}",
                    "checkpoint_path": f".planning/phases/09-test/CP-{i}.md",
                }),
                encoding="utf-8",
            )
            repair(root)
        baks = list(backups_dir.glob("*.pre-repair.*.bak"))
        names = [b.name for b in baks]
        self.assertEqual(
            len(set(names)), len(names),
            f"duplicate backup names: {sorted(names)}",
        )


class RetentionCapE2ETests(unittest.TestCase):
    """T0-5-M2: seeding 10 fake `.bak` siblings + a repair must leave 10.

    Validates retention from the repair() surface (not just lib.backups
    directly), confirming the default retention=10 is wired end-to-end.
    """

    def test_repair_prunes_to_retention_cap(self):
        root = _make_root(
            phase_state={
                "phase": "discuss",
                "current_checkpoint": "CP-09-99",
                "checkpoint_path": ".planning/phases/09-test/CHECKPOINTS.md",
            }
        )
        backups_dir = root / ".harness" / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        # The repair() targets STATE.md (only the state-current block changes
        # in this fixture); seed 10 `.bak` siblings for that basename so the
        # 11th (the one repair writes) triggers exactly one eviction.
        for i in range(10):
            ts = f"20260101T0000{i:02d}000000000Z"
            (backups_dir / f"STATE.md.pre-repair.{ts}.0.bak").write_bytes(
                f"seed-{i}".encode()
            )
        repair(root)
        remaining = sorted(backups_dir.glob("STATE.md.pre-repair.*.bak"))
        self.assertEqual(
            len(remaining), 10,
            f"expected 10 after prune, got {len(remaining)}: {[p.name for p in remaining]}",
        )


class BackupsDirSecurityTests(unittest.TestCase):
    """T0-5-M3: assert SM3 invariants at the slice surface (repair()).

    The lib.backups module has its own coverage; this file owns the
    end-to-end guarantee that any repair-driven backup write yields a
    mode-0o700 directory and refuses symlink-targeted .bak paths.
    """

    def test_backups_dir_mode_is_0700(self):
        root = _make_root(
            phase_state={
                "phase": "discuss",
                "current_checkpoint": "CP-09-99",
                "checkpoint_path": ".planning/phases/09-test/CHECKPOINTS.md",
            }
        )
        repair(root)
        backups_dir = root / ".harness" / "backups"
        self.assertTrue(backups_dir.is_dir())
        mode = stat.S_IMODE(backups_dir.stat().st_mode)
        self.assertEqual(mode, 0o700, f"expected 0o700, got {oct(mode)}")

    def test_repair_refuses_symlink_target(self):
        """Deterministic .bak name pointed at a symlink — repair must NOT
        follow it (O_NOFOLLOW). The decoy file MUST be untouched."""
        from unittest import mock
        from lib import backups as backups_mod

        root = _make_root(
            phase_state={
                "phase": "discuss",
                "current_checkpoint": "CP-09-99",
                "checkpoint_path": ".planning/phases/09-test/CHECKPOINTS.md",
            }
        )
        backups_dir = root / ".harness" / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        decoy = root / "decoy"
        decoy.write_bytes(b"DECOY")
        fixed_ts = "20260516T193045000000000Z"
        # Pre-plant the symlink at every name the 3-retry loop could pick.
        bak_path = backups_dir / f"STATE.md.pre-repair.{fixed_ts}.99.bak"
        os.symlink(decoy, bak_path)
        with mock.patch.object(backups_mod, "_compact_utc_nanos",
                               return_value=fixed_ts), \
             mock.patch.object(backups_mod, "_pid", return_value=99):
            with self.assertRaises((SystemExit, OSError)):
                repair(root)
        self.assertEqual(decoy.read_bytes(), b"DECOY",
                         "O_NOFOLLOW MUST prevent writing through the symlink")


class CanonicalPayloadTests(unittest.TestCase):
    def test_canonical_payload_threads_paused_phases(self) -> None:
        payload = canonical_state_current_payload(
            phase=1,
            phase_title="X",
            checkpoint=None,
            checkpoint_path=None,
            paused_phases=[
                {"slug": "02-skill-pack-expansion", "paused_since": "2026-05-12"},
            ],
        )
        self.assertIn("### Paused Phases", payload)
        self.assertIn(
            "- 02-skill-pack-expansion (paused since 2026-05-12)\n", payload
        )

    def test_canonical_payload_omits_subsection_when_empty(self) -> None:
        payload = canonical_state_current_payload(
            phase=1,
            phase_title="X",
            checkpoint=None,
            checkpoint_path=None,
            paused_phases=[],
        )
        self.assertNotIn("### Paused Phases", payload)


if __name__ == "__main__":
    unittest.main()
