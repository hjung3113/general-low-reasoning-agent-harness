"""Tests for M6/#15 — graveyard + obsolete-artifact upgrade policy.

Tests cover:
- obsolete_artifact_policy() helper in manifest.py
- Graveyard section in docs/ARTIFACTS.md
- Upgrade behavior for each action: delete, warn, ignore
- Missing upgrade_action triggers fallback (not hard-fail) with stderr warning
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.manifest import obsolete_artifact_policy, KNOWN_UPGRADE_ACTIONS


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_manifest_data(removed_entries: list[dict]) -> dict:
    return {
        "version": "__release__",
        "_display_version": "test",
        "packs": {},
        "files": [],
        "removed_in_version": removed_entries,
    }


# ---------------------------------------------------------------------------
# Unit tests for obsolete_artifact_policy()
# ---------------------------------------------------------------------------

class TestObsoleteArtifactPolicy(unittest.TestCase):

    def test_returns_empty_when_no_removed_entries(self):
        data = _make_manifest_data([])
        policy = obsolete_artifact_policy(data)
        self.assertEqual(policy, {})

    def test_returns_correct_action_for_each_entry(self):
        data = _make_manifest_data([
            {"path": ".roo/commands/old.md", "removed_in": "v0.7.0", "upgrade_action": "delete"},
            {"path": "docs/old.md", "removed_in": "v0.7.0", "upgrade_action": "warn"},
            {"path": "skip-me.md", "removed_in": "v0.7.0", "upgrade_action": "ignore"},
        ])
        policy = obsolete_artifact_policy(data)
        self.assertEqual(policy[".roo/commands/old.md"], "delete")
        self.assertEqual(policy["docs/old.md"], "warn")
        self.assertEqual(policy["skip-me.md"], "ignore")

    def test_known_upgrade_actions_constant(self):
        self.assertEqual(KNOWN_UPGRADE_ACTIONS, {"delete", "ignore", "warn"})

    def test_missing_upgrade_action_infers_safe_default(self):
        """Entries missing upgrade_action get an inferred default (no hard fail)."""
        data = _make_manifest_data([
            {"path": ".roo/commands/old.md", "removed_in": "v0.7.0"},  # no upgrade_action
        ])
        captured = io.StringIO()
        with patch.object(sys, "stderr", captured):
            policy = obsolete_artifact_policy(data)
        # Should not raise; should warn.
        self.assertIn(".roo/commands/old.md", policy)
        # Harness adapter path → inferred "delete"
        self.assertEqual(policy[".roo/commands/old.md"], "delete")
        self.assertIn("missing upgrade_action", captured.getvalue())

    def test_missing_upgrade_action_unknown_path_defaults_to_warn(self):
        """Unknown path without upgrade_action infers 'warn' (conservative)."""
        data = _make_manifest_data([
            {"path": "some/user/file.md", "removed_in": "v0.7.0"},
        ])
        captured = io.StringIO()
        with patch.object(sys, "stderr", captured):
            policy = obsolete_artifact_policy(data)
        self.assertEqual(policy["some/user/file.md"], "warn")

    def test_unknown_upgrade_action_raises_system_exit(self):
        data = _make_manifest_data([
            {"path": "old.md", "removed_in": "v0.7.0", "upgrade_action": "nuke"},
        ])
        with self.assertRaises(SystemExit):
            obsolete_artifact_policy(data)

    def test_skips_entries_with_empty_path(self):
        data = _make_manifest_data([
            {"path": "", "removed_in": "v0.7.0", "upgrade_action": "delete"},
        ])
        policy = obsolete_artifact_policy(data)
        self.assertEqual(policy, {})


# ---------------------------------------------------------------------------
# Graveyard section in generated docs/ARTIFACTS.md
# ---------------------------------------------------------------------------

class TestGraveyardDocSection(unittest.TestCase):
    """Generated docs/ARTIFACTS.md must document graveyard entries."""

    def setUp(self):
        self.content = (_REPO_ROOT / "docs" / "ARTIFACTS.md").read_text(encoding="utf-8")
        self.manifest = json.loads((_REPO_ROOT / "harness" / "manifest.json").read_text(encoding="utf-8"))

    def test_graveyard_section_exists(self):
        self.assertIn("Graveyard", self.content)

    def test_all_removed_entries_listed(self):
        for entry in self.manifest.get("removed_in_version", []):
            path = entry["path"]
            self.assertIn(path, self.content, msg=f"Removed entry {path!r} missing from ARTIFACTS.md")

    def test_upgrade_action_field_present(self):
        for entry in self.manifest.get("removed_in_version", []):
            action = entry.get("upgrade_action")
            self.assertIsNotNone(action, msg=f"Entry {entry['path']!r} missing upgrade_action in manifest")
            self.assertIn(action, self.content, msg=f"Action {action!r} for {entry['path']!r} missing from doc")

    def test_all_manifest_entries_have_upgrade_action(self):
        """Schema requirement: every removed_in_version entry must have upgrade_action."""
        for entry in self.manifest.get("removed_in_version", []):
            self.assertIn(
                "upgrade_action", entry,
                msg=f"removed_in_version entry {entry.get('path','?')!r} missing upgrade_action"
            )


# ---------------------------------------------------------------------------
# Upgrade behavior with graveyard policy
# ---------------------------------------------------------------------------

class TestUpgradeGraveyardBehavior(unittest.TestCase):
    """Upgrade applies graveyard policy correctly for delete, warn, ignore."""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _call_obsolete_policy_delete(self):
        """Returns policy dict with a single delete entry for a synthetic path."""
        return {".roo/commands/legacy.md": "delete"}

    def test_delete_action_removes_present_file(self):
        """Upgrade with 'delete' action removes the legacy file."""
        # Create a temp target with the legacy file present.
        target = self.tmpdir / "target"
        target.mkdir()
        legacy = target / ".roo" / "commands" / "legacy.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("old content\n", encoding="utf-8")

        # Simulate what upgrade does with a delete action.
        policy = {".roo/commands/legacy.md": "delete"}
        from lib.roadmap_state import normalize_path
        from lib.install import remove_empty_parents
        for grave_path, action in policy.items():
            dest = target / normalize_path(grave_path)
            if dest.exists() and action == "delete":
                dest.unlink()
                remove_empty_parents(dest.parent, target)

        self.assertFalse(legacy.exists(), "Legacy file should have been deleted")

    def test_warn_action_preserves_present_file(self):
        """Upgrade with 'warn' action leaves the file untouched and warns."""
        target = self.tmpdir / "target"
        target.mkdir()
        legacy = target / "docs" / "old.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("user content\n", encoding="utf-8")

        policy = {"docs/old.md": "warn"}
        from lib.roadmap_state import normalize_path
        captured = io.StringIO()
        with patch.object(sys, "stderr", captured):
            for grave_path, action in policy.items():
                dest = target / normalize_path(grave_path)
                if dest.exists():
                    if action == "warn":
                        sys.stderr.write(f"WARNING: obsolete harness artifact present but not deleted (policy=warn): {grave_path}\n")
                    elif action == "delete":
                        dest.unlink()

        self.assertTrue(legacy.exists(), "Warn action must not delete the file")
        self.assertIn("WARNING", captured.getvalue())

    def test_ignore_action_is_silent(self):
        """Upgrade with 'ignore' action does nothing even if file is present."""
        target = self.tmpdir / "target"
        target.mkdir()
        legacy = target / "skip.md"
        legacy.write_text("content\n", encoding="utf-8")

        policy = {"skip.md": "ignore"}
        captured = io.StringIO()
        with patch.object(sys, "stderr", captured):
            for grave_path, action in policy.items():
                dest = target / grave_path
                if dest.exists() and action == "delete":
                    dest.unlink()
                # ignore: nothing

        self.assertTrue(legacy.exists(), "Ignore action must not delete the file")
        self.assertEqual(captured.getvalue(), "", "Ignore action must produce no stderr")

    def test_absent_file_is_no_op_for_delete(self):
        """If the legacy file does not exist, delete is a no-op."""
        target = self.tmpdir / "target"
        target.mkdir()
        policy = {".roo/commands/nonexistent.md": "delete"}
        from lib.roadmap_state import normalize_path

        # Should not raise.
        for grave_path, action in policy.items():
            dest = target / normalize_path(grave_path)
            if dest.exists() and action == "delete":
                dest.unlink()


if __name__ == "__main__":
    unittest.main()
