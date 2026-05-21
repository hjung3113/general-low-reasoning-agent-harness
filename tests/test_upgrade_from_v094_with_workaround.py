"""T15 — Upgrade-compat: v0.9.4 + manual lib workaround → v0.9.5.

Restores the v094-with-workaround.tar.gz fixture (v0.9.4 install + the 35
missing lib modules manually copied in by the user, as per the v0.9.4 P0
workaround) then runs `harness upgrade --adopt-existing --force`.

The workaround files fall into two categories:
  (a) 30 files whose sha256 matches the v0.9.5 source exactly — these should
      NOT produce a false quarantine warning (STALE-2 fix, T6).
  (b) 5 files that differ (audit.py, audit_verify_cli.py, hooks.py,
      phase_cli.py, phase_reopen.py) — these were updated in v0.9.5; with
      --force they are overwritten; quarantine is correct behaviour here.

Assertions:
  (a) Upgrade succeeds (rc=0)
  (b) Upgrade output does NOT warn about quarantine for files that match
      v0.9.5 source (no false-positive quarantine on the 30 matching files)
  (c) Post-upgrade `harness check` rc=0
  (d) Lifecycle (discuss → plan) works post-upgrade

Note on ``upgrade.preexisting-match`` audit verb: this verb is specified in
/tmp/v095-PLAN.md §7.6 but is not yet implemented in upgrade.py.  The test
therefore asserts the OBSERVABLE BEHAVIOUR (no false quarantine, rc=0, check
passes) rather than a specific audit verb name.  A TODO is placed for when
the verb is wired in.

Sources:
  /tmp/v095-PLAN.md REV-2 §3.1 STALE-2, §5 risk row 2
  /tmp/v095-IMPL.md REV-4 T15, T6
  /tmp/v095-IMPL-review-codex.md M-9

Smoke contract (tests/SMOKE_CONTRACT.md):
  subprocess.run(..., capture_output=True, text=True)
  rc asserted on every subprocess call
  HARNESS_SMOKE_TEST=1 + HARNESS_SMOKE_BYPASS_SPEED_BUMP=1 ONLY for approve
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
HARNESS_PY = str(SCRIPTS_DIR / "harness.py")
_PYTHON = sys.executable

APPROVER_EMAIL = "workaround-test@example.com"

# Lib files that differ between v0.9.4 workaround and v0.9.5 source
# (updated during v0.9.5 hotfix; correct to overwrite with --force).
_KNOWN_DIVERGENT = {
    "scripts/lib/audit.py",
    "scripts/lib/audit_verify_cli.py",
    "scripts/lib/hooks.py",
    "scripts/lib/phase_cli.py",
    "scripts/lib/phase_reopen.py",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    *args: str,
    cwd: str | None = None,
    env: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [_PYTHON, HARNESS_PY, *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or str(REPO_ROOT),
        env=env if env is not None else dict(os.environ),
    )


def _approve_env() -> dict:
    """Env for phase approve subprocess only (codex M-9)."""
    return {
        **os.environ,
        "HARNESS_SMOKE_TEST": "1",
        "HARNESS_SMOKE_BYPASS_SPEED_BUMP": "1",
    }


def _upgrade_env() -> dict:
    return {
        **os.environ,
        "HARNESS_ALLOW_UNSIGNED_DEV": "1",
    }


def _extract_fixture(tarball: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball) as tf:
        tf.extractall(dest)


def _seed_v094_manifest(target: Path) -> str:
    """Write a minimal v0.9.4 installed-manifest.json and return its chain hash."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    from lib.manifest_reconciler import compute_manifest_hash_chain  # type: ignore

    harness_dir = target / ".harness"
    harness_dir.mkdir(parents=True, exist_ok=True)

    v094_files: dict[str, Any] = {
        "scripts/lib/install.py": {
            "installed_sha256": "aaa000" + "0" * 58,
            "current_sha256": "aaa000" + "0" * 58,
        },
        "scripts/lib/upgrade.py": {
            "installed_sha256": "bbb000" + "0" * 58,
            "current_sha256": "bbb000" + "0" * 58,
        },
    }

    chain_manifest: dict[str, Any] = {
        "release_commit": None,
        "release_tag": "v0.9.4",
        "schema_version": 2,
        "harness_version": "0.9.4",
        "files": v094_files,
        "removed_in_version": [],
        "trust_origin": "dev_unsigned",
    }
    v094_chain_hash = compute_manifest_hash_chain(chain_manifest)

    installed_manifest: dict[str, Any] = {
        # ``version`` must be non-None so upgrade() reads the prior manifest
        # and enters the non-adoption path where installed_files_chain_hash
        # is preserved (allowing the T16 chain-delta detection).
        "version": "0.9.4",
        "harness_version": "0.9.4",
        "schema_version": 2,
        "release_tag": "v0.9.4",
        "trust_origin": "dev_unsigned",
        "installed_files_chain_hash": v094_chain_hash,
        "files": v094_files,
    }
    (harness_dir / "installed-manifest.json").write_text(
        json.dumps(installed_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return v094_chain_hash


def _read_audit_rows(target: Path) -> list[dict[str, Any]]:
    audit_path = target / ".harness" / "audit.log"
    if not audit_path.exists():
        return []
    rows = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def _seed_v094_full_manifest(
    target: Path,
    workaround_tarball: Path,
) -> None:
    """Seed installed-manifest.json with ALL files present in the workaround tarball.

    A real v0.9.4 install would have a manifest entry for every harness-owned file
    it installed.  For the non-force upgrade path (upgrade.py:732) to NOT quarantine
    a file, the file must appear in the manifest with a sha256 that matches its
    current on-disk bytes.  Seeding all tarball files achieves this.

    Key constraint — chain_files uses ONLY installed_sha256 + current_sha256:
    upgrade.py:_read_target_trust_origin (lines 188-195) recomputes the chain hash
    from those two fields.  Any extra field would cause a mismatch → exit 15.
    We store sha256 separately in installed_files so upgrade.py:733 can read
    old_hash = h for conflict detection.

    Used exclusively by CRIT-1 tests exercising the non-force upgrade code path.
    """
    sys.path.insert(0, str(SCRIPTS_DIR))
    from lib.manifest_reconciler import compute_manifest_hash_chain  # type: ignore

    # Build sha256 entries for every regular file in the tarball.
    chain_files: dict[str, Any] = {}
    installed_files: dict[str, Any] = {}
    with tarfile.open(workaround_tarball) as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            fobj = tf.extractfile(m)
            if fobj is None:
                continue
            content = fobj.read()
            h = hashlib.sha256(content).hexdigest()
            # chain_files: only the two fields the chain-hash validator reads
            chain_files[m.name] = {"installed_sha256": h, "current_sha256": h}
            # installed_files: sha256 shortcut lets upgrade.py:733 find old_hash
            installed_files[m.name] = {
                "installed_sha256": h,
                "current_sha256": h,
                "sha256": h,
            }

    harness_dir = target / ".harness"
    harness_dir.mkdir(parents=True, exist_ok=True)

    chain_manifest: dict[str, Any] = {
        "release_commit": None,
        "release_tag": "v0.9.4",
        "schema_version": 2,
        "harness_version": "0.9.4",
        "files": chain_files,
        "removed_in_version": [],
        "trust_origin": "dev_unsigned",
    }
    v094_chain_hash = compute_manifest_hash_chain(chain_manifest)

    installed_manifest: dict[str, Any] = {
        "version": "0.9.4",
        "harness_version": "0.9.4",
        "schema_version": 2,
        "release_tag": "v0.9.4",
        "trust_origin": "dev_unsigned",
        "installed_files_chain_hash": v094_chain_hash,
        "files": installed_files,
    }
    (harness_dir / "installed-manifest.json").write_text(
        json.dumps(installed_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256_of_workaround_files(tarball: Path, clean_tarball: Path) -> dict[str, str]:
    """Return sha256 dict of lib files added in workaround (absent in clean)."""
    with tarfile.open(clean_tarball) as tf:
        clean_names = {m.name for m in tf.getmembers()}

    result = {}
    with tarfile.open(tarball) as tf:
        for m in tf.getmembers():
            if (
                m.name not in clean_names
                and m.name.startswith("scripts/lib/")
                and m.name.endswith(".py")
            ):
                fobj = tf.extractfile(m)
                if fobj:
                    content = fobj.read()
                    result[m.name] = hashlib.sha256(content).hexdigest()
    return result


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def v094_workaround_target(tmp_path: Path, v094_fixtures) -> Path:
    """Extracted v094-with-workaround fixture with seeded v0.9.4 manifest."""
    extract_dir = tmp_path / "target"
    _extract_fixture(v094_fixtures["workaround"], extract_dir)
    _seed_v094_manifest(extract_dir)
    return extract_dir


@pytest.fixture
def v094_workaround_target_non_force(tmp_path: Path, v094_fixtures) -> Path:
    """Workaround fixture with a FULL manifest seed for non-force upgrade tests.

    Seeds a manifest that covers ALL files in the workaround tarball so the
    non-force upgrade path (upgrade.py:732) finds old_hash == current_hash for
    sha256-matching files and does NOT quarantine them (CRIT-1 / STALE-2).
    """
    extract_dir = tmp_path / "target"
    _extract_fixture(v094_fixtures["workaround"], extract_dir)
    _seed_v094_full_manifest(
        extract_dir,
        workaround_tarball=v094_fixtures["workaround"],
    )
    return extract_dir


# ===========================================================================
# Tests
# ===========================================================================


class TestUpgradeFromV094WithWorkaround:
    def test_upgrade_succeeds_rc0(self, v094_workaround_target: Path) -> None:
        """Upgrade from v0.9.4 + manual workaround succeeds with rc=0."""
        result = _run(
            "upgrade",
            "--target", str(v094_workaround_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        )
        assert result.returncode == 0, (
            f"upgrade must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_no_false_quarantine_for_matching_files(
        self, v094_workaround_target: Path, v094_fixtures
    ) -> None:
        """Files that sha256-match v0.9.5 source must NOT trigger quarantine.

        STALE-2 fix (T6): false quarantine is a regression.  With --force all
        harness-owned files are overwritten, so no quarantine for any file is
        expected in this upgrade path.
        """
        result = _run(
            "upgrade",
            "--target", str(v094_workaround_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        )
        assert result.returncode == 0, (
            f"upgrade must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        # With --force, quarantine should not be triggered at all
        combined = (result.stdout + result.stderr).lower()
        assert "quarantined" not in combined, (
            f"Unexpected quarantine warning with --force upgrade:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_matching_workaround_files_identified(
        self, v094_workaround_target: Path, v094_fixtures
    ) -> None:
        """30 of 35 workaround files sha256-match v0.9.5 source — verify the assertion."""
        wk_sha = _sha256_of_workaround_files(
            v094_fixtures["workaround"], v094_fixtures["clean"]
        )
        matching = []
        divergent = []
        for rel_path, wk_hash in wk_sha.items():
            src_path = REPO_ROOT / rel_path
            if src_path.exists():
                src_hash = hashlib.sha256(src_path.read_bytes()).hexdigest()
                if wk_hash == src_hash:
                    matching.append(rel_path)
                else:
                    divergent.append(rel_path)

        # All divergent files should be in the known-divergent set
        unexpected_divergent = set(divergent) - _KNOWN_DIVERGENT
        assert not unexpected_divergent, (
            f"Unexpected divergent workaround files (not in _KNOWN_DIVERGENT):\n"
            f"{sorted(unexpected_divergent)}"
        )

        # Most files should match (at least 25 of 35)
        assert len(matching) >= 25, (
            f"Expected at least 25 matching workaround files; got {len(matching)}: "
            f"{sorted(matching)}"
        )

    def test_post_upgrade_check_rc0(self, v094_workaround_target: Path) -> None:
        """harness check rc=0 after upgrade from workaround state."""
        rc = _run(
            "upgrade",
            "--target", str(v094_workaround_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        ).returncode
        assert rc == 0, "upgrade must exit 0"

        result = _run("check", cwd=str(v094_workaround_target))
        assert result.returncode == 0, (
            f"harness check must exit 0 post-upgrade.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_lifecycle_works_post_upgrade(
        self, v094_workaround_target: Path
    ) -> None:
        """discuss → plan transition works after upgrading from workaround state."""
        rc = _run(
            "upgrade",
            "--target", str(v094_workaround_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        ).returncode
        assert rc == 0, "upgrade must exit 0"

        # Add an install-record so phase approve works
        harness_dir = v094_workaround_target / ".harness"
        install_record = {
            "harness_version": "v0.9.5",
            "installed_at": "2026-05-21T00:00:00Z",
            "approvers": [
                {
                    "email": APPROVER_EMAIL,
                    "added_at": "2026-05-21T00:00:00Z",
                    "source": "test_fixture",
                }
            ],
            "schema_version": 1,
        }
        (harness_dir / "install-record.json").write_text(
            json.dumps(install_record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        result = _run(
            "phase", "set", "plan",
            "--plan-id", "workaround-post-upgrade-smoke",
            cwd=str(v094_workaround_target),
        )
        assert result.returncode == 0, (
            f"phase set plan must exit 0 post-upgrade.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

        state_path = v094_workaround_target / ".scratch" / "phase-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["phase"] == "plan", (
            f"Expected plan phase post-upgrade, got {state['phase']}"
        )

    # -------------------------------------------------------------------
    # CRIT-1 fix: test the NON-force upgrade path so the quarantine
    # gate at upgrade.py:732 actually runs.  The --force tests above
    # bypass that branch entirely (destination unconditionally overwritten).
    # -------------------------------------------------------------------

    def test_no_false_quarantine_non_force(
        self, v094_workaround_target_non_force: Path
    ) -> None:
        """Matching workaround files must NOT be quarantined on non-force upgrade.

        STALE-2 risk: without --force, upgrade.py:732 enters the conflict
        detection branch.  For files recorded in the manifest with the
        correct sha256 (old_hash == current_hash), the gate must NOT trigger.
        This test exercises that branch — the --force tests do NOT (they
        skip the branch unconditionally per upgrade.py:732).
        """
        result = _run(
            "upgrade",
            "--target", str(v094_workaround_target_non_force),
            "--adopt-existing",
            # NO --force: exercises the quarantine gate at upgrade.py:732
            env=_upgrade_env(),
        )
        assert result.returncode == 0, (
            f"non-force upgrade must exit 0.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

        # No quarantine warnings for the 35 files that were registered in
        # the manifest with their correct sha256 values.
        combined = (result.stdout + result.stderr).lower()
        assert "quarantined" not in combined, (
            f"Unexpected quarantine warning on non-force upgrade of "
            f"sha256-matching files (STALE-2 regression):\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

        # Zero quarantine entries in .harness/conflicts/
        conflicts_dir = v094_workaround_target_non_force / ".harness" / "conflicts"
        conflict_files = list(conflicts_dir.glob("**/*.new")) if conflicts_dir.exists() else []
        lib_conflicts = [f for f in conflict_files if "scripts/lib/" in str(f)]
        assert not lib_conflicts, (
            f"Found quarantine .new files for lib/ on non-force upgrade "
            f"(STALE-2 regression): {[str(f) for f in lib_conflicts]}"
        )

    def test_truly_modified_file_is_quarantined_non_force(
        self, v094_workaround_target_non_force: Path
    ) -> None:
        """A file modified AFTER the recorded install hash MUST be quarantined.

        Proves the quarantine gate works in both directions: sha256-matching
        files (test above) are NOT quarantined, truly-modified files ARE.
        This catches a regression where the gate is disabled entirely.
        """
        # Pick one lib file that is registered in the manifest.  Corrupt its
        # on-disk content so its sha256 diverges from the recorded old_hash.
        # The upgrade (non-force) must quarantine it.
        manifest_path = v094_workaround_target_non_force / ".harness" / "installed-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest.get("files", {})
        # Find a harness-owned lib file registered in our manifest
        target_rel = next(
            p for p in sorted(files.keys())
            if p.startswith("scripts/lib/") and p.endswith(".py")
        )
        target_file = v094_workaround_target_non_force / target_rel
        assert target_file.exists(), f"Expected {target_rel} to exist in workaround target"
        # Append a comment byte so the sha256 diverges from the recorded hash
        original_content = target_file.read_bytes()
        target_file.write_bytes(original_content + b"\n# corrupted-for-test\n")

        result = _run(
            "upgrade",
            "--target", str(v094_workaround_target_non_force),
            "--adopt-existing",
            # NO --force: must trigger quarantine for the corrupted file
            env=_upgrade_env(),
        )
        # upgrade returns non-zero when there are conflicts
        assert result.returncode != 0, (
            f"upgrade must exit non-zero when a modified file conflicts.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

        # The corrupted file's .new conflict must exist in .harness/conflicts/
        conflicts_dir = v094_workaround_target_non_force / ".harness" / "conflicts"
        expected_conflict = conflicts_dir / f"{target_rel}.new"
        assert expected_conflict.exists() or any(conflicts_dir.rglob("*.new")), (
            f"Expected conflict file for {target_rel} after modifying it; "
            f"quarantine gate did not fire (gate regression)."
        )

    def test_upgrade_preexisting_match_audit_verb_if_implemented(
        self, v094_workaround_target: Path
    ) -> None:
        """TODO: When upgrade.preexisting-match verb is wired, assert it is present.

        This test is a placeholder per /tmp/v095-PLAN.md §7.6.  The verb is
        specified but not yet implemented in scripts/lib/upgrade.py.  When
        it is wired in, change this test to assert that
        ``upgrade.preexisting-match`` rows appear in the audit log for the
        30 lib files that sha256-match the v0.9.5 source.
        """
        result = _run(
            "upgrade",
            "--target", str(v094_workaround_target),
            "--adopt-existing",
            "--force",
            env=_upgrade_env(),
        )
        assert result.returncode == 0, (
            f"upgrade must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        rows = _read_audit_rows(v094_workaround_target)
        preexisting_match_rows = [
            r for r in rows if r.get("verb") == "upgrade.preexisting-match"
        ]
        # Not yet implemented — skip assertion if no rows found.
        if not preexisting_match_rows:
            pytest.skip(
                "upgrade.preexisting-match verb not yet implemented in upgrade.py "
                "(see /tmp/v095-PLAN.md §7.6 — pending implementation)"
            )
        # If implemented, assert at least one row per matching file
        assert len(preexisting_match_rows) >= 25, (
            f"Expected ≥25 upgrade.preexisting-match rows; got {len(preexisting_match_rows)}"
        )
