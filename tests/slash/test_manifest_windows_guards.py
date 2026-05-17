"""S10d — Verify manifest.json declares the Windows degraded guard files (§5.2).

These entries must exist in harness/manifest.json so that `harness install`
can locate and ship them in a future Windows install adapter.

Files verified:
  - scripts/lib/autopilot_guard.ps1
  - scripts/lib/autopilot_guard_wrappers/curl.cmd
  - scripts/lib/autopilot_guard_wrappers/gh.cmd
  - scripts/lib/autopilot_guard_wrappers/git.cmd

Design ref: §5.2 S10d — Windows degraded posture shims.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "harness" / "manifest.json"

WINDOWS_GUARD_PATHS = [
    "scripts/lib/autopilot_guard.ps1",
    "scripts/lib/autopilot_guard_wrappers/curl.cmd",
    "scripts/lib/autopilot_guard_wrappers/gh.cmd",
    "scripts/lib/autopilot_guard_wrappers/git.cmd",
]


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest_files(manifest) -> list[dict]:
    return manifest["files"]


@pytest.fixture(scope="module")
def manifest_file_paths(manifest_files) -> set[str]:
    return {f["path"] for f in manifest_files}


class TestManifestWindowsGuardEntries:
    """All four Windows guard files must be declared in harness/manifest.json."""

    @pytest.mark.parametrize("guard_path", WINDOWS_GUARD_PATHS)
    def test_entry_present_in_manifest_files(self, manifest_file_paths, guard_path):
        assert guard_path in manifest_file_paths, (
            f"{guard_path!r} is missing from harness/manifest.json 'files' array. "
            "S10d requires all Windows guard files to be declared in the manifest."
        )

    @pytest.mark.parametrize("guard_path", WINDOWS_GUARD_PATHS)
    def test_entry_policy_harness_owned(self, manifest_files, guard_path):
        entry = next((f for f in manifest_files if f["path"] == guard_path), None)
        assert entry is not None, f"{guard_path!r} not found in manifest files"
        assert entry.get("policy") == "harness-owned", (
            f"{guard_path!r}: expected policy='harness-owned', got {entry.get('policy')!r}"
        )

    @pytest.mark.parametrize("guard_path", WINDOWS_GUARD_PATHS)
    def test_entry_owner_harness(self, manifest_files, guard_path):
        entry = next((f for f in manifest_files if f["path"] == guard_path), None)
        assert entry is not None, f"{guard_path!r} not found in manifest files"
        assert entry.get("owner") == "harness", (
            f"{guard_path!r}: expected owner='harness', got {entry.get('owner')!r}"
        )

    @pytest.mark.parametrize("guard_path", WINDOWS_GUARD_PATHS)
    def test_on_disk_file_present(self, guard_path):
        on_disk = REPO_ROOT / guard_path
        assert on_disk.exists(), (
            f"On-disk file {on_disk} does not exist — manifest entry would be broken."
        )

    def test_all_four_entries_present(self, manifest_file_paths):
        """All four Windows guard paths must be present (single assertion for easy CI reporting)."""
        missing = [p for p in WINDOWS_GUARD_PATHS if p not in manifest_file_paths]
        assert not missing, (
            f"Missing Windows guard manifest entries: {missing}. "
            "S10d requires all four entries in harness/manifest.json."
        )
