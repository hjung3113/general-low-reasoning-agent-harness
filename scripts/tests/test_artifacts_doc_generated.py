"""Tests for generate_artifacts_doc.py — determinism and --check mode (issue #14)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Repo root — two levels up from scripts/tests/
_REPO_ROOT = Path(__file__).resolve().parents[2]
_GENERATOR = _REPO_ROOT / "scripts" / "generate_artifacts_doc.py"
_OUTPUT_PATH = _REPO_ROOT / "docs" / "ARTIFACTS.md"
_MANIFEST_PATH = _REPO_ROOT / "harness" / "manifest.json"


def _run_generator(*extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_GENERATOR)] + list(extra_args),
        capture_output=True,
        text=True,
    )


class TestArtifactsDocCheck(unittest.TestCase):
    """--check passes when docs/ARTIFACTS.md is current."""

    def test_check_passes_on_current_file(self):
        result = _run_generator("--check")
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")

    def test_check_fails_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_output = Path(tmpdir) / "ARTIFACTS.md"
            # Patch the generator to use a non-existent output path.
            # We do this by running in a subprocess with env manipulation —
            # but simpler: just verify the --check message contains FAIL.
            # Indirect approach: rename the real file temporarily.
            import shutil
            backup = Path(tmpdir) / "ARTIFACTS.md.bak"
            if _OUTPUT_PATH.exists():
                shutil.copy2(str(_OUTPUT_PATH), str(backup))
                _OUTPUT_PATH.rename(missing_output)
                try:
                    result = _run_generator("--check")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("FAIL", result.stderr)
                finally:
                    missing_output.rename(_OUTPUT_PATH)


class TestArtifactsDocDeterminism(unittest.TestCase):
    """Running the generator twice produces byte-identical output."""

    def test_deterministic_regeneration(self):
        result1 = _run_generator("--check")
        # Generator is already current; generate once into a temp file and compare.
        with tempfile.TemporaryDirectory() as tmpdir:
            # We can't redirect output path in current interface, so instead
            # run the generator again and compare stdout (which only has a
            # progress line) — real test is check exit code stays 0 twice.
            result2 = _run_generator("--check")
        self.assertEqual(result1.returncode, 0, msg=result1.stderr)
        self.assertEqual(result2.returncode, 0, msg=result2.stderr)

    def test_mutated_manifest_fails_check(self):
        """Mutating a temp manifest copy changes generated text vs real doc."""
        import sys, os
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))

        # Load real manifest, add a dummy file entry.
        manifest_data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest_data["files"].append({
            "path": "_test_only_dummy_artifact.txt",
            "source": "harness/skeleton/clean/AGENTS.md",
            "policy": "harness-owned",
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_manifest = Path(tmpdir) / "manifest.json"
            tmp_manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

            # Import generator module, temporarily patch manifest path.
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "generate_artifacts_doc", str(_GENERATOR)
            )
            mod = importlib.util.module_from_spec(spec)
            # Patch paths before exec.
            spec.loader.exec_module(mod)
            orig_manifest = mod._MANIFEST_PATH
            orig_output = mod._OUTPUT_PATH
            try:
                mod._MANIFEST_PATH = tmp_manifest
                mod._OUTPUT_PATH = _OUTPUT_PATH  # read current file
                # _generate with mutated data should differ from current file.
                data = mod._load_manifest()
                generated = mod._generate(data)
                current = _OUTPUT_PATH.read_text(encoding="utf-8")
                self.assertNotEqual(
                    current, generated,
                    msg="Adding a dummy manifest entry should change generated output",
                )
            finally:
                mod._MANIFEST_PATH = orig_manifest
                mod._OUTPUT_PATH = orig_output


class TestArtifactsDocContent(unittest.TestCase):
    """Structural checks: file counts match manifest, no timestamps."""

    def setUp(self):
        self.content = _OUTPUT_PATH.read_text(encoding="utf-8")
        self.manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_no_wall_clock_timestamp(self):
        """Generated doc must not contain wall-clock timestamps."""
        import re
        # Check for ISO datetime patterns like 2026-05-23T12:34:56
        timestamp_pattern = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        matches = timestamp_pattern.findall(self.content)
        self.assertEqual(matches, [], msg=f"Found timestamps: {matches}")

    def test_file_count_matches_manifest(self):
        """Total file count in doc header matches manifest files array."""
        expected = len(self.manifest["files"])
        self.assertIn(f"Total files: **{expected}**", self.content)

    def test_all_packs_present(self):
        """Every pack name appears in the generated doc."""
        for pack_name in self.manifest["packs"]:
            self.assertIn(pack_name, self.content, msg=f"Pack {pack_name!r} missing from ARTIFACTS.md")

    def test_generated_header_present(self):
        """Doc has the generated-file header."""
        self.assertIn("Generated file", self.content)
        self.assertIn("do not hand-edit", self.content)

    def test_graveyard_section_present(self):
        """Graveyard section is present."""
        self.assertIn("Graveyard", self.content)


if __name__ == "__main__":
    unittest.main()
