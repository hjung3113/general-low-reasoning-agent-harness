#!/usr/bin/env python3
"""Tests for release orchestration helpers."""

from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release


class ReleaseScriptTests(unittest.TestCase):
    def test_next_patch_version_uses_highest_stable_tag(self) -> None:
        tags = ["v0.4.2", "v0.4.10", "v0.5.0-rc1", "not-a-version"]

        self.assertEqual("v0.4.11", release.next_release_version(tags, bump="patch"))

    def test_next_minor_and_major_reset_lower_components(self) -> None:
        tags = ["v0.4.2"]

        self.assertEqual("v0.5.0", release.next_release_version(tags, bump="minor"))
        self.assertEqual("v1.0.0", release.next_release_version(tags, bump="major"))

    def test_validate_release_version_rejects_suffix_tags(self) -> None:
        self.assertEqual("v1.2.3", release.validate_release_version("v1.2.3"))

        with self.assertRaisesRegex(ValueError, "vMAJOR.MINOR.PATCH"):
            release.validate_release_version("v1.2.3-1")

    def test_dry_run_release_uses_calculated_next_version_and_expected_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            release.subprocess.run(["git", "init"], cwd=root, check=True, stdout=release.subprocess.DEVNULL)
            runner = release.CommandRunner(root=root, dry_run=True)

            with mock.patch.object(release, "read_existing_tags", return_value=["v0.4.2"]):
                selected = release.run_release(version=None, bump="patch", runner=runner, assume_yes=True)

            self.assertEqual("v0.4.3", selected)
            commands = [" ".join(command) for command in runner.commands]
        self.assertEqual(
            [
                "git fetch --tags origin",
                "git switch develop",
                "git pull --ff-only origin develop",
                "git switch main",
                "git pull --ff-only origin main",
                "git merge --no-ff develop -m merge: release v0.4.3",
                "python3 -m unittest scripts/test_harness.py scripts/test_release.py",
                "python3 scripts/harness.py check",
                "python3 scripts/release_smoke_test.py",
                "git push origin main",
                "git tag -a v0.4.3 -m v0.4.3",
                "python3 scripts/release_smoke_test.py --release --expected-version v0.4.3",
                "git push origin v0.4.3",
            ],
            commands[:13],
        )
        self.assertIn("gh release create v0.4.3 --verify-tag --title v0.4.3 --notes v0.4.3", commands)


if __name__ == "__main__":
    unittest.main()
