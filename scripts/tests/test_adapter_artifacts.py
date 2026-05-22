#!/usr/bin/env python3
"""Per-adapter artifact verification (Phase E Tier 1).

Asserts the file matrix each adapter writes is exact and non-overlapping
beyond the documented baseline. Surfaced by Phase E review: drift between
adapter installers and the smoke matrix was previously caught only by
human eyeballing the diff. This pins it.

Baseline = `--adapters none` (skills under `.agents/`, planning skeleton,
`.harness/installed-manifest.json`). Adapter-specific files are the
*additional* artifacts contributed when the adapter is enabled.

Adapter spec (pinned 2026-05-17):
- roo:      .roomodes, .roo/README.md, .roo/commands/, .roo/rules/,
            .roo/rules-*/, .roo/skills/
- opencode: .opencode/commands/ only
- both:     union of roo + opencode (no extra files beyond the union)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "scripts" / "harness.py"


def _install(adapter: str, target: Path) -> None:
    env = dict(os.environ)
    env["HARNESS_USER"] = "t@e"
    subprocess.run(
        [sys.executable, str(HARNESS), "init", "--target", str(target),
         "--adapters", adapter],
        check=True, capture_output=True, env=env,
    )


def _files(root: Path) -> set[str]:
    return {
        str(p.relative_to(root))
        for p in root.rglob("*") if p.is_file()
    }


class AdapterArtifactMatrixTests(unittest.TestCase):
    """One install per adapter; compare against `none` baseline."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="adapter-artifact-test."))
        cls.dirs: dict[str, Path] = {}
        cls.files: dict[str, set[str]] = {}
        for adapter in ("none", "roo", "opencode", "both"):
            d = cls.tmp / adapter
            _install(adapter, d)
            cls.dirs[adapter] = d
            cls.files[adapter] = _files(d)
        cls.baseline = cls.files["none"]
        cls.roo_extra = cls.files["roo"] - cls.baseline
        cls.opencode_extra = cls.files["opencode"] - cls.baseline
        cls.both_extra = cls.files["both"] - cls.baseline

    def test_none_baseline_has_no_adapter_dirs(self) -> None:
        for f in self.baseline:
            self.assertFalse(
                f.startswith(".roo/") or f.startswith(".opencode/") or f == ".roomodes",
                f"baseline (adapters=none) leaked adapter artifact: {f}",
            )

    def test_roo_writes_roomodes(self) -> None:
        self.assertIn(".roomodes", self.roo_extra)

    def test_roo_writes_commands_dir(self) -> None:
        cmds = {f for f in self.roo_extra if f.startswith(".roo/commands/")}
        self.assertGreaterEqual(
            len(cmds), 5, f"expected ≥5 roo command files, got {sorted(cmds)}"
        )

    def test_roo_writes_mode_rules(self) -> None:
        mode_rules = {f for f in self.roo_extra if f.startswith(".roo/rules-")}
        self.assertGreaterEqual(
            len(mode_rules), 3,
            f"expected ≥3 .roo/rules-<mode>/ files, got {sorted(mode_rules)}",
        )

    def test_roo_writes_global_rules(self) -> None:
        self.assertIn(".roo/rules/global.md", self.roo_extra)
        self.assertIn(".roo/rules/phase-gate.md", self.roo_extra)

    def test_opencode_writes_commands_only(self) -> None:
        non_command = {
            f for f in self.opencode_extra if not f.startswith(".opencode/commands/")
        }
        self.assertEqual(
            non_command, set(),
            f"opencode adapter should only write under .opencode/commands/, "
            f"saw extra: {sorted(non_command)}",
        )
        cmds = {f for f in self.opencode_extra if f.startswith(".opencode/commands/")}
        self.assertGreaterEqual(
            len(cmds), 3, f"expected ≥3 opencode command files, got {sorted(cmds)}"
        )

    def test_opencode_does_not_write_roo_artifacts(self) -> None:
        leak = {
            f for f in self.opencode_extra
            if f.startswith(".roo/") or f == ".roomodes"
        }
        self.assertEqual(leak, set(), f"opencode leaked roo artifacts: {sorted(leak)}")

    def test_roo_does_not_write_opencode_artifacts(self) -> None:
        leak = {f for f in self.roo_extra if f.startswith(".opencode/")}
        self.assertEqual(leak, set(), f"roo leaked opencode artifacts: {sorted(leak)}")

    def test_both_equals_union_of_roo_and_opencode(self) -> None:
        union = self.roo_extra | self.opencode_extra
        self.assertEqual(
            self.both_extra, union,
            f"adapters=both should equal union(roo,opencode). "
            f"missing: {union - self.both_extra}, "
            f"extra: {self.both_extra - union}",
        )

    def test_phase_command_files_reference_harness_cli(self) -> None:
        # The slash-command files (Roo + OpenCode) MUST instruct the agent
        # to invoke 'harness phase ...' verbs. Drift here means a model
        # following the command will not exercise the harness state machine.
        # Carve-out: `.roo/commands/fsd-run-phase.md` delegates to CLI wrapper;
        # the verb is embedded in the harness CLI invocation, not inline.
        # Tracked as a doc-clarity carry item for 02c.
        ROUTER_CARVE_OUTS = {".roo/commands/fsd-run-phase.md"}
        phase_cmd_files = []
        for adapter in ("roo", "opencode"):
            root = self.dirs[adapter]
            for f in self.files[adapter]:
                if f in ROUTER_CARVE_OUTS:
                    continue
                if "/commands/" in f and ("phase" in f.lower() or any(
                    p in f.lower() for p in ("plan.md", "discuss.md", "execute.md", "done.md")
                )):
                    phase_cmd_files.append(root / f)
        self.assertGreaterEqual(len(phase_cmd_files), 4,
                                "expected ≥4 phase-related command files across adapters")
        missing = []
        for path in phase_cmd_files:
            text = path.read_text(encoding="utf-8")
            if "harness phase" not in text:
                missing.append(str(path))
        self.assertEqual(missing, [],
                         f"phase command files missing 'harness phase' verb reference: {missing}")


if __name__ == "__main__":
    unittest.main()
