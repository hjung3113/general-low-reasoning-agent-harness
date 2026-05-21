"""T7 — Fixture builder determinism + fail-fast on non-zero init.

Test cases:
1. Pinned .sha256 matches current tarball bytes on disk
2. Forced harness init non-zero → FixtureBuildError raised (not swallowed)
3. Two builds in separate temp dirs → sha256 equal (determinism property)
   (Skipped in CI unless HARNESS_RUN_FIXTURE_REBUILD=1; full rebuild takes ~30s)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tarfile
import io
import gzip
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
_TESTS_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _TESTS_DIR / "fixtures"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from build_v094_fixture import (  # noqa: E402
    FixtureBuildError,
    build_deterministic_tarball,
    _normalize_v094_install_state,
    sha256_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_pinned_sha256(sha256_path: Path) -> str:
    """Parse '<hex>  <filename>' format."""
    return sha256_path.read_text(encoding="utf-8").split()[0]


# ---------------------------------------------------------------------------
# Test 1: Pinned .sha256 matches current tarball on disk
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["v094-clean.tar.gz", "v094-with-workaround.tar.gz"])
def test_pinned_sha256_matches_tarball(name: str) -> None:
    """T7-1: pinned .sha256 == sha256(tarball bytes) for each fixture."""
    tarball = _FIXTURES_DIR / name
    sha256_file_path = _FIXTURES_DIR / f"{name}.sha256"

    if not tarball.exists():
        pytest.skip(f"Fixture tarball missing: {tarball}; run scripts/build_v094_fixture.py")
    if not sha256_file_path.exists():
        pytest.skip(f"Pinned sha256 missing: {sha256_file_path}")

    actual = _sha256_bytes(tarball.read_bytes())
    pinned = _read_pinned_sha256(sha256_file_path)

    assert actual == pinned, (
        f"{name}: tarball sha256 {actual[:16]}... does not match pinned {pinned[:16]}...\n"
        f"Re-run: python3 scripts/build_v094_fixture.py"
    )


# ---------------------------------------------------------------------------
# Test 2: Forced harness init non-zero → FixtureBuildError raised
# ---------------------------------------------------------------------------


def test_non_zero_init_raises_fixture_build_error(tmp_path: Path) -> None:
    """T7-2: run_v094_init with a bad harness.py raises FixtureBuildError, not silent continue."""
    import subprocess

    # Import here so we can patch subprocess.run
    import build_v094_fixture as _bfx

    bad_harness = tmp_path / "harness.py"
    bad_harness.write_text("import sys; sys.exit(99)\n", encoding="utf-8")
    target_dir = tmp_path / "target"

    with pytest.raises(FixtureBuildError) as exc_info:
        _bfx.run_v094_init(bad_harness, target_dir)

    assert "99" in str(exc_info.value), f"Error should mention exit code 99: {exc_info.value}"


# ---------------------------------------------------------------------------
# Test 3: build_deterministic_tarball is deterministic (two calls same output)
# ---------------------------------------------------------------------------


def test_build_deterministic_tarball_same_output(tmp_path: Path) -> None:
    """T7-3: two calls to build_deterministic_tarball on same source → identical bytes."""
    # Create a small source tree
    src = tmp_path / "source"
    (src / "scripts" / "lib").mkdir(parents=True)
    (src / "scripts" / "harness.py").write_text("# harness\n", encoding="utf-8")
    (src / "scripts" / "lib" / "state.py").write_text("# state\n", encoding="utf-8")
    (src / ".harness").mkdir()
    (src / ".harness" / "installed-manifest.json").write_text(
        json.dumps({"version": "0.9.4", "schema_version": 2, "files": {}}),
        encoding="utf-8",
    )

    out1 = tmp_path / "out1.tar.gz"
    out2 = tmp_path / "out2.tar.gz"

    digest1 = build_deterministic_tarball(src, out1)
    digest2 = build_deterministic_tarball(src, out2)

    assert digest1 == digest2, (
        f"build_deterministic_tarball not deterministic:\n  run1={digest1}\n  run2={digest2}"
    )
    assert out1.read_bytes() == out2.read_bytes(), "Tarball bytes differ between two identical runs"


# ---------------------------------------------------------------------------
# Test 4: _normalize_v094_install_state strips non-deterministic fields
# ---------------------------------------------------------------------------


def test_normalize_strips_nondeterministic_fields(tmp_path: Path) -> None:
    """T7-4: _normalize_v094_install_state removes source, git hash, and normalizes installed_at."""
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    manifest = harness_dir / "installed-manifest.json"
    manifest.write_text(
        json.dumps({
            "version": "0.9.4",
            "schema_version": 2,
            "source": "/home/user/dev/harness",
            "git_user_email_at_install_sha256": "abc123",
            "files": {
                "scripts/harness.py": {
                    "sha256": "deadbeef",
                    "installed_at": "2026-05-01T00:00:00Z",
                }
            },
        }),
        encoding="utf-8",
    )

    _normalize_v094_install_state(tmp_path)

    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["git_user_email_at_install_sha256"] is None
    assert data["source"] == "__fixture__"
    assert data["files"]["scripts/harness.py"]["installed_at"] == "2026-05-21T00:00:00Z"
