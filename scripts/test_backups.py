#!/usr/bin/env python3
"""Tests for scripts/lib/backups.py.

Owning slice: T0-1 CC5 (extraction); per CONTRACT-PIN §1, T0-5 ultimately
owns this module and may patch the retention policy.

Coverage:
- write_backup_with_excl_and_prune: happy path + O_EXCL refusal + O_NOFOLLOW
  refusal + retention prune at N+1.
- Backup directory created with 0o700 mode (SM3).
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import backups  # noqa: E402


class WriteBackupHappyPathTests(unittest.TestCase):
    def test_write_backup_creates_bak_with_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups_dir = tmp / ".harness" / "backups"
            target = tmp / "phase-state.json"
            target.write_bytes(b"original")
            bak = backups.write_backup_with_excl_and_prune(
                target, source_bytes=b"original", backups_dir=backups_dir,
            )
            self.assertTrue(bak.exists())
            self.assertEqual(bak.read_bytes(), b"original")
            self.assertEqual(bak.parent, backups_dir)
            # CONTRACT-PIN §6.1 filename grammar.
            self.assertTrue(bak.name.startswith("phase-state.json.pre-repair."))
            self.assertTrue(bak.name.endswith(".bak"))


class BackupsDirModeTests(unittest.TestCase):
    def test_backups_dir_created_with_0700(self) -> None:
        """SM3: fresh backups directory must be created with mode 0o700."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups_dir = tmp / ".harness" / "backups"
            target = tmp / "phase-state.json"
            target.write_bytes(b"original")
            backups.write_backup_with_excl_and_prune(
                target, source_bytes=b"original", backups_dir=backups_dir,
            )
            mode = stat.S_IMODE(backups_dir.stat().st_mode)
            self.assertEqual(mode, 0o700,
                             f"expected 0o700, got {oct(mode)}")


class WriteBackupExclRefusalTests(unittest.TestCase):
    def test_write_backup_refuses_existing_bak_via_o_excl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups_dir = tmp / ".harness" / "backups"
            backups_dir.mkdir(parents=True)
            target = tmp / "phase-state.json"
            target.write_bytes(b"x")

            fixed_ts = "20260516T193045000000000Z"
            with mock.patch.object(backups, "_compact_utc_nanos", return_value=fixed_ts), \
                 mock.patch.object(backups, "_pid", return_value=12345):
                preexisting = backups_dir / f"phase-state.json.pre-repair.{fixed_ts}.12345.bak"
                preexisting.write_bytes(b"DO NOT OVERWRITE")
                with self.assertRaises(SystemExit):
                    backups.write_backup_with_excl_and_prune(
                        target, source_bytes=b"x", backups_dir=backups_dir,
                    )
                self.assertEqual(preexisting.read_bytes(), b"DO NOT OVERWRITE")


class WriteBackupNofollowTests(unittest.TestCase):
    def test_write_backup_refuses_symlink_target(self) -> None:
        """SM3: O_NOFOLLOW must refuse writing through a symlink at the .bak path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups_dir = tmp / ".harness" / "backups"
            backups_dir.mkdir(parents=True)
            target = tmp / "phase-state.json"
            target.write_bytes(b"x")

            # Force a deterministic .bak name and point that name at a symlink
            # whose target is some innocent file.
            fixed_ts = "20260516T193045000000000Z"
            decoy = tmp / "decoy"
            decoy.write_bytes(b"DECOY")
            with mock.patch.object(backups, "_compact_utc_nanos", return_value=fixed_ts), \
                 mock.patch.object(backups, "_pid", return_value=99):
                bak_path = backups_dir / f"phase-state.json.pre-repair.{fixed_ts}.99.bak"
                os.symlink(decoy, bak_path)
                with self.assertRaises((SystemExit, OSError)):
                    backups.write_backup_with_excl_and_prune(
                        target, source_bytes=b"x", backups_dir=backups_dir,
                    )
                # Decoy never touched.
                self.assertEqual(decoy.read_bytes(), b"DECOY")


class CollisionRetryTests(unittest.TestCase):
    """T0-1 CC4: O_EXCL collision must be retried up to 3 times before erroring."""

    def test_write_backup_retries_on_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups_dir = tmp / ".harness" / "backups"
            backups_dir.mkdir(parents=True)
            target = tmp / "phase-state.json"
            target.write_bytes(b"x")

            # Pre-create a colliding .bak at the first timestamp value the
            # generator will return; the second call must produce a fresh
            # name and succeed.
            collide_ts = "20260516T193045000000000Z"
            fresh_ts = "20260516T193046000000000Z"
            collided = backups_dir / f"phase-state.json.pre-repair.{collide_ts}.42.bak"
            collided.write_bytes(b"PRE-EXISTING")

            timestamps = iter([collide_ts, fresh_ts, fresh_ts])
            with mock.patch.object(backups, "_compact_utc_nanos",
                                   side_effect=lambda: next(timestamps)), \
                 mock.patch.object(backups, "_pid", return_value=42):
                bak = backups.write_backup_with_excl_and_prune(
                    target, source_bytes=b"x", backups_dir=backups_dir,
                )
            # Distinct path from the colliding pre-existing one.
            self.assertNotEqual(bak, collided)
            self.assertTrue(bak.exists())
            self.assertEqual(bak.read_bytes(), b"x")
            self.assertEqual(collided.read_bytes(), b"PRE-EXISTING")


class RetentionPruneTests(unittest.TestCase):
    def test_retention_prunes_oldest_above_limit(self) -> None:
        """Eleventh backup of the same basename evicts the oldest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups_dir = tmp / ".harness" / "backups"
            backups_dir.mkdir(parents=True)
            target = tmp / "phase-state.json"
            target.write_bytes(b"x")

            # Pre-seed 10 .bak files with monotonically increasing timestamp
            # components so sort-by-name == sort-by-time.
            seeded = []
            for i in range(10):
                ts = f"20260101T0000{i:02d}000000000Z"
                p = backups_dir / f"phase-state.json.pre-repair.{ts}.0.bak"
                p.write_bytes(f"seed-{i}".encode())
                seeded.append(p)
            oldest = seeded[0]
            self.assertTrue(oldest.exists())

            # Write the 11th: oldest should be evicted, keeping 10 total.
            backups.write_backup_with_excl_and_prune(
                target, source_bytes=b"x", backups_dir=backups_dir, retention=10,
            )
            current = sorted(backups_dir.glob("phase-state.json.pre-repair.*.bak"))
            self.assertEqual(len(current), 10,
                             f"expected 10 after prune, got {len(current)}")
            self.assertFalse(oldest.exists(),
                             "oldest backup should have been pruned")


class ChmodFailureWarningTests(unittest.TestCase):
    """T0-5-SecM2: chmod failures during _ensure_backups_dir MUST warn.

    Previously failures were swallowed silently — leaving operators unaware
    that the directory's mode never reached 0o700 (e.g. on filesystems that
    reject the call, or under restrictive permissions).
    """

    def test_chmod_failure_emits_stderr_warning(self) -> None:
        import io
        import contextlib

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups_dir = tmp / ".harness" / "backups"
            target = tmp / "phase-state.json"
            target.write_bytes(b"x")
            stderr = io.StringIO()
            real_chmod = os.chmod

            def boom(path, mode, **kwargs):
                if str(path) == str(backups_dir):
                    raise PermissionError("simulated")
                return real_chmod(path, mode, **kwargs)

            with mock.patch.object(os, "chmod", side_effect=boom), \
                 contextlib.redirect_stderr(stderr):
                backups.write_backup_with_excl_and_prune(
                    target, source_bytes=b"x", backups_dir=backups_dir,
                )
            msg = stderr.getvalue()
            self.assertIn("WARNING", msg)
            self.assertIn("chmod", msg)
            self.assertIn("0o700", msg)


class PruneSymlinkGuardTests(unittest.TestCase):
    """T0-5-SecM1: prune MUST NOT unlink through a symlink.

    Replacing glob with os.scandir + entry.is_symlink() check ensures a
    hostile or accidentally-planted symlink under `.harness/backups/`
    cannot trick the retention loop into chasing an unlink to an
    arbitrary path. The skipped symlink emits a stderr warning so the
    operator can investigate.
    """

    def test_prune_skips_symlinks_with_warning(self) -> None:
        import io
        import contextlib

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups_dir = tmp / ".harness" / "backups"
            backups_dir.mkdir(parents=True)
            target = tmp / "phase-state.json"
            target.write_bytes(b"x")
            # Seed: 9 plain .bak files (oldest first by name) + 1 SYMLINK
            # at the second-oldest slot pointing at a decoy file.
            decoy = tmp / "decoy"
            decoy.write_bytes(b"DECOY")
            for i in range(9):
                ts = f"20260101T0000{i:02d}000000000Z"
                (backups_dir / f"phase-state.json.pre-repair.{ts}.0.bak").write_bytes(
                    f"seed-{i}".encode()
                )
            # Plant a symlink with a name that would otherwise be pruned
            # first (oldest lex order):
            link_name = "phase-state.json.pre-repair.20250101T000000000000000Z.0.bak"
            os.symlink(decoy, backups_dir / link_name)

            # Now write the 11th backup; prune should evict the oldest
            # PLAIN .bak (seed-0) and SKIP the symlink with a warning.
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                backups.write_backup_with_excl_and_prune(
                    target, source_bytes=b"x", backups_dir=backups_dir, retention=10,
                )

            # Symlink survives.
            self.assertTrue((backups_dir / link_name).is_symlink(),
                            "symlink MUST NOT be unlinked by prune")
            # Decoy untouched.
            self.assertEqual(decoy.read_bytes(), b"DECOY")
            # A stderr warning mentions the skipped entry.
            self.assertIn("symlink", stderr.getvalue().lower())
            self.assertIn(link_name, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
