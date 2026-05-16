#!/usr/bin/env python3
"""Tests for scripts/lib/state_migrate.py and scripts/migrate_state.py.

Owning plan: .planning/phases/02b-hardening/plans/02b-02-T0-1-PLAN.md Block C.
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1 (module
``state_migrate.py``) and §3 (flat test path, fixtures at
``scripts/fixtures/migrate/``).

Tests T-10..T-21 from the plan.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import state_migrate  # noqa: E402
from lib import atomic_io  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "scripts" / "fixtures" / "migrate"


def _read_input() -> dict:
    return json.loads((FIXTURES / "phase_state_v0_input.json").read_text(encoding="utf-8"))


def _read_golden_bytes() -> bytes:
    return (FIXTURES / "phase_state_v0_to_v2_golden.json").read_bytes()


class StateMigratePureTests(unittest.TestCase):
    # T-10: byte-equal golden
    def test_migrate_forward_v0_to_v2_byte_output_matches_artifact_5_golden(self) -> None:
        state = _read_input()
        out_bytes = state_migrate.serialize(state_migrate.forward(state))
        self.assertEqual(out_bytes, _read_golden_bytes())

    # T-11: round-trip json.loads equality
    def test_migrate_reverse_v2_to_v0_json_equal_to_input(self) -> None:
        state = _read_input()
        forward = state_migrate.forward(state)
        reverse = state_migrate.reverse(forward)
        self.assertEqual(reverse, state)

    # T-12: forward idempotent at json.loads level
    def test_migrate_forward_is_idempotent_at_json_loads_level(self) -> None:
        state = _read_input()
        once = state_migrate.forward(state)
        twice = state_migrate.forward(once)
        self.assertEqual(once, twice)

    # T-19: reverse writes approved=false for done per 3a
    def test_migrate_reverse_writes_approved_false_for_done_per_sub_decision_3a(self) -> None:
        v2 = {
            "phase": "done",
            "approved_by": "user",
            "approved_at": "2026-05-14T15:00:00.000000000Z",
            "updated_at": "2026-05-15T00:00:00.000000000Z",
            "updated_by": "test",
            "state_schema_version": 2,
            "automation_mode": "manual",
            "auto_selected": [],
        }
        v0 = state_migrate.reverse(v2)
        self.assertEqual(v0.get("approved"), False)

    # T-20: reverse removes state_schema_version
    def test_migrate_reverse_removes_state_schema_version_key(self) -> None:
        v2 = state_migrate.forward(_read_input())
        v0 = state_migrate.reverse(v2)
        self.assertNotIn("state_schema_version", v0)

    # T-21: canonical serialization rules (sort_keys, indent=2, trailing newline)
    def test_migrate_forward_uses_canonical_serialization_rules(self) -> None:
        state = _read_input()
        out_bytes = state_migrate.serialize(state_migrate.forward(state))
        self.assertTrue(out_bytes.endswith(b"\n"))
        # No double trailing newline.
        self.assertFalse(out_bytes.endswith(b"\n\n"))
        # 2-space indent: first non-bracket line should start with two spaces.
        text = out_bytes.decode("utf-8")
        lines = text.splitlines()
        self.assertTrue(any(ln.startswith("  ") for ln in lines))
        # sort_keys: top-level keys appear in alphabetical order.
        parsed = json.loads(text)
        top_keys = list(parsed.keys())
        # json.loads preserves order on cpython 3.7+; output was produced with
        # sort_keys so it should be alphabetical.
        # Re-parse from raw text via regex to capture on-disk order is
        # overkill; we instead check that ``state_schema_version`` precedes
        # ``updated_at`` lexicographically and that they appear in that order
        # in the text.
        idx_sv = text.index('"state_schema_version"')
        idx_ua = text.index('"updated_at"')
        self.assertLess(idx_sv, idx_ua)


class StateMigrateSidecarTests(unittest.TestCase):
    # T-17: sidecar contents match G1-E schema
    def test_migrate_sidecar_contents_match_g1e_schema(self) -> None:
        payload = state_migrate.sidecar_payload(
            target_path="/tmp/foo.json",
            pre_hash="a" * 64,
            expected_post_hash="b" * 64,
            migrator_version="t0-1-v1",
        )
        self.assertEqual(
            set(payload.keys()),
            {"pre_hash", "expected_post_hash", "target_path", "migrator_version",
             "started_at", "direction"},
        )
        # Default direction is "forward" when not explicitly passed.
        self.assertEqual(payload["direction"], "forward")
        self.assertEqual(payload["pre_hash"], "a" * 64)
        self.assertEqual(payload["expected_post_hash"], "b" * 64)
        self.assertEqual(payload["target_path"], "/tmp/foo.json")
        self.assertEqual(payload["migrator_version"], "t0-1-v1")
        self.assertRegex(payload["started_at"], r"^\d{4}-\d{2}-\d{2}T")


class StateMigrateFileProtocolTests(unittest.TestCase):
    def _make_target(self, tmp: Path) -> Path:
        target = tmp / "phase-state.json"
        # Copy the v0 input verbatim as the live state.
        target.write_text(
            (FIXTURES / "phase_state_v0_input.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return target

    # T-13: sidecar + bak before replacing target on simulated crash
    def test_migrate_writes_bak_before_replacing_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / ".harness" / "backups").mkdir(parents=True)
            target = self._make_target(tmp)
            pre_bytes = target.read_bytes()

            # Patch atomic_write_text in state_migrate's namespace so the
            # target-write step (step 3) fails after sidecar (step 1) AND bak
            # (step 2) have already landed.
            real_write = atomic_io.atomic_write_text
            call_log: list[Path] = []

            def fake_write(path, content, *, mode=0o644):
                call_log.append(Path(path))
                # Allow sidecar write to succeed; fail the target write.
                if Path(path) == target:
                    raise RuntimeError("simulated crash mid-step-3")
                return real_write(path, content, mode=mode)

            with mock.patch.object(state_migrate, "atomic_write_text", side_effect=fake_write):
                with self.assertRaises(RuntimeError):
                    state_migrate.migrate_file(
                        target, direction="forward", backups_dir=tmp / ".harness" / "backups"
                    )
            # Target is unchanged (atomic_write_text failed before os.replace,
            # so the original is preserved).
            self.assertEqual(target.read_bytes(), pre_bytes)
            # A .bak file exists.
            baks = list((tmp / ".harness" / "backups").glob("phase-state.json.pre-repair.*.bak"))
            self.assertEqual(len(baks), 1)
            self.assertEqual(baks[0].read_bytes(), pre_bytes)
            # A sidecar exists alongside the .bak.
            sidecars = list((tmp / ".harness" / "backups").glob("*.bak.resume.json"))
            self.assertEqual(len(sidecars), 1)

    # T-14: refuse to overwrite existing .bak via O_EXCL
    def test_migrate_refuses_to_overwrite_existing_bak_via_o_excl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups = tmp / ".harness" / "backups"
            backups.mkdir(parents=True)
            target = self._make_target(tmp)
            pre_bytes = target.read_bytes()

            # Pre-create a colliding .bak by patching the timestamp helper so
            # both the prior fake-bak and the migrator pick the same name.
            fixed_ts = "20260516T193045000000000Z"
            with mock.patch.object(
                state_migrate, "_compact_utc_nanos", return_value=fixed_ts
            ), mock.patch.object(state_migrate, "_pid", return_value=12345):
                pre_existing = backups / f"phase-state.json.pre-repair.{fixed_ts}.12345.bak"
                pre_existing.write_bytes(b"DO NOT OVERWRITE")

                with self.assertRaises(SystemExit) as ctx:
                    state_migrate.migrate_file(
                        target, direction="forward", backups_dir=backups
                    )
                self.assertEqual(ctx.exception.code, 1)
                msg = str(ctx.exception)
                self.assertIn("--resume", msg)
                self.assertIn("remove", msg.lower())

            # Target untouched.
            self.assertEqual(target.read_bytes(), pre_bytes)
            # Pre-existing bak untouched.
            self.assertEqual(pre_existing.read_bytes(), b"DO NOT OVERWRITE")

    # T-18: uses T0-A atomic primitive for all writes (sidecar + final target)
    def test_migrate_uses_t0a_primitive_for_all_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups = tmp / ".harness" / "backups"
            backups.mkdir(parents=True)
            target = self._make_target(tmp)

            real_write = atomic_io.atomic_write_text
            calls: list[Path] = []

            def counting_write(path, content, *, mode=0o644):
                calls.append(Path(path))
                return real_write(path, content, mode=mode)

            with mock.patch.object(
                state_migrate, "atomic_write_text", side_effect=counting_write
            ):
                state_migrate.migrate_file(
                    target, direction="forward", backups_dir=backups
                )

            # At least one call for the sidecar and one for the final target.
            self.assertGreaterEqual(len(calls), 2)
            target_calls = [p for p in calls if p == target]
            self.assertEqual(len(target_calls), 1)
            sidecar_calls = [p for p in calls if p.name.endswith(".bak.resume.json")]
            self.assertGreaterEqual(len(sidecar_calls), 1)

    # T-15: resume completes after step 2 crash
    def test_migrate_resume_completes_after_step_2_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups = tmp / ".harness" / "backups"
            backups.mkdir(parents=True)
            target = self._make_target(tmp)
            pre_bytes = target.read_bytes()

            # Simulate a step-2 crash via the same pattern as T-13.
            real_write = atomic_io.atomic_write_text

            def fake_write(path, content, *, mode=0o644):
                if Path(path) == target:
                    raise RuntimeError("simulated crash mid-step-3")
                return real_write(path, content, mode=mode)

            with mock.patch.object(
                state_migrate, "atomic_write_text", side_effect=fake_write
            ):
                with self.assertRaises(RuntimeError):
                    state_migrate.migrate_file(
                        target, direction="forward", backups_dir=backups
                    )
            self.assertEqual(target.read_bytes(), pre_bytes)
            sidecars = list(backups.glob("*.bak.resume.json"))
            self.assertEqual(len(sidecars), 1)

            # Now resume: write should complete and sidecar should be removed.
            state_migrate.resume(target, backups_dir=backups)
            self.assertEqual(target.read_bytes(), _read_golden_bytes())
            self.assertEqual(list(backups.glob("*.bak.resume.json")), [])

    # T-16: resume detects already-complete target
    def test_migrate_resume_detects_already_complete_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups = tmp / ".harness" / "backups"
            backups.mkdir(parents=True)
            target = tmp / "phase-state.json"
            # Target is already migrated.
            target.write_bytes(_read_golden_bytes())
            golden = _read_golden_bytes()
            post_hash = hashlib.sha256(golden).hexdigest()
            pre_hash = hashlib.sha256(
                (FIXTURES / "phase_state_v0_input.json").read_bytes()
            ).hexdigest()

            sidecar = backups / "phase-state.json.pre-repair.fixed.12345.bak.resume.json"
            sidecar.write_text(
                json.dumps(
                    {
                        "pre_hash": pre_hash,
                        "expected_post_hash": post_hash,
                        "target_path": str(target),
                        "migrator_version": "t0-1-v1",
                        "started_at": "2026-05-16T19:30:45.000000000Z",
                        "direction": "forward",
                    }
                ),
                encoding="utf-8",
            )

            state_migrate.resume(target, backups_dir=backups)
            self.assertEqual(target.read_bytes(), golden)
            self.assertEqual(list(backups.glob("*.bak.resume.json")), [])


class StateMigrateReverseVersionGuardTests(unittest.TestCase):
    """T0-1 SM2: --reverse must refuse v0 / unknown-version inputs."""

    def _write_target(self, tmp: Path, state: dict) -> Path:
        target = tmp / "phase-state.json"
        target.write_text(json.dumps(state) + "\n", encoding="utf-8")
        return target

    def test_reverse_refuses_on_v0_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups = tmp / ".harness" / "backups"
            backups.mkdir(parents=True)
            # v0: no state_schema_version key.
            target = self._write_target(tmp, {"phase": "discuss", "approved": False})
            with self.assertRaises(SystemExit) as ctx:
                state_migrate.migrate_file(target, direction="reverse", backups_dir=backups)
            self.assertEqual(ctx.exception.code, 2)
            msg = str(ctx.exception)
            self.assertIn("v0", msg.lower())

    def test_reverse_refuses_on_unknown_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups = tmp / ".harness" / "backups"
            backups.mkdir(parents=True)
            target = self._write_target(tmp, {"phase": "discuss", "state_schema_version": 99})
            with self.assertRaises(SystemExit) as ctx:
                state_migrate.migrate_file(target, direction="reverse", backups_dir=backups)
            self.assertEqual(ctx.exception.code, 2)
            self.assertIn("unknown", str(ctx.exception).lower())


class StateMigrateResumeDirectionTests(unittest.TestCase):
    """T0-1 CC3+SM1: sidecar must record direction; resume must dispatch on it."""

    def test_sidecar_payload_includes_direction(self) -> None:
        payload = state_migrate.sidecar_payload(
            target_path="/tmp/foo.json",
            pre_hash="a" * 64,
            expected_post_hash="b" * 64,
            direction="reverse",
        )
        self.assertEqual(payload.get("direction"), "reverse")

    def test_resume_dispatches_to_reverse_when_sidecar_reverse(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups = tmp / ".harness" / "backups"
            backups.mkdir(parents=True)
            target = tmp / "phase-state.json"
            # Start with a v2-shape (post forward); reverse should yield v0.
            v2_bytes = (FIXTURES / "phase_state_v0_to_v2_golden.json").read_bytes()
            target.write_bytes(v2_bytes)
            v0_bytes = state_migrate.serialize(
                state_migrate.reverse(json.loads(v2_bytes.decode("utf-8")))
            )
            pre_hash = hashlib.sha256(v2_bytes).hexdigest()
            post_hash = hashlib.sha256(v0_bytes).hexdigest()

            sidecar = backups / "phase-state.json.pre-repair.fixed.0.bak.resume.json"
            sidecar.write_text(
                json.dumps({
                    "pre_hash": pre_hash,
                    "expected_post_hash": post_hash,
                    "target_path": str(target),
                    "migrator_version": "t0-1-v1",
                    "started_at": "2026-05-16T19:30:45.000000000Z",
                    "direction": "reverse",
                }),
                encoding="utf-8",
            )
            state_migrate.resume(target, backups_dir=backups)
            self.assertEqual(target.read_bytes(), v0_bytes)
            self.assertEqual(list(backups.glob("*.bak.resume.json")), [])

    def test_resume_refuses_legacy_sidecar_without_direction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backups = tmp / ".harness" / "backups"
            backups.mkdir(parents=True)
            target = tmp / "phase-state.json"
            target.write_bytes(b"{}\n")
            sidecar = backups / "phase-state.json.pre-repair.fixed.0.bak.resume.json"
            # No `direction` key.
            sidecar.write_text(
                json.dumps({
                    "pre_hash": "0" * 64,
                    "expected_post_hash": "1" * 64,
                    "target_path": str(target),
                    "migrator_version": "t0-1-v1",
                    "started_at": "2026-05-16T19:30:45.000000000Z",
                }),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as ctx:
                state_migrate.resume(target, backups_dir=backups)
            self.assertEqual(ctx.exception.code, 7)
            self.assertIn("direction", str(ctx.exception))


class StateMigrateCLITests(unittest.TestCase):
    def test_cli_forward_dry_run_on_input_fixture(self) -> None:
        """migrate_state.py --forward --dry-run runs and prints expected JSON.

        Round-trip-style verification.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            target = tmp / "phase-state.json"
            shutil.copyfile(FIXTURES / "phase_state_v0_input.json", target)
            cmd = [
                sys.executable,
                str(REPO_ROOT / "scripts" / "migrate_state.py"),
                "--forward",
                "--dry-run",
                "--target",
                str(target),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, check=False)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            # Output should be the canonical golden bytes.
            self.assertEqual(r.stdout, _read_golden_bytes().decode("utf-8"))
            # Target unchanged under --dry-run.
            self.assertEqual(target.read_bytes(), (FIXTURES / "phase_state_v0_input.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
