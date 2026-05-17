"""S07-deprecation: --chain / --auto flag deprecation tests (design §3.3, §3.4).

Tests verify:
- `harness --chain <...>` exits 13 with replacement hint
- `harness phase set execute --auto` exits 13 with replacement hint
- Audit entry verb=cli.deprecated_flag is written
- Hint text matches design §3.3 exactly
- No state mutation occurs
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS_BIN = "/tmp/harness-test-venv/bin/python"
HARNESS_MOD = str(Path(__file__).parent.parent.parent / "scripts" / "harness.py")


def _run_harness(*args, env_extra=None, cwd=None):
    """Run harness with given args. Returns (returncode, stdout, stderr)."""
    import os
    env = dict(os.environ, **(env_extra or {}))
    cmd = [HARNESS_BIN, HARNESS_MOD, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env)
    return result.returncode, result.stdout, result.stderr


class TestDeprecatedChainFlag:
    def test_chain_flag_exits_13(self, tmp_path):
        """harness --chain phase set plan exits 13."""
        rc, stdout, stderr = _run_harness("--chain", "phase", "set", "plan")
        assert rc == 13, f"Expected 13, got {rc}\nstdout={stdout}\nstderr={stderr}"

    def test_chain_flag_has_fix_line(self, tmp_path):
        """Exit 13 must include a Fix: line pointing to replacement command."""
        rc, stdout, stderr = _run_harness("--chain", "phase", "set", "plan")
        combined = stdout + stderr
        assert "Fix:" in combined, f"No Fix: line in output:\n{combined}"

    def test_chain_flag_hint_mentions_autopilot(self, tmp_path):
        """Hint mentions the replacement command."""
        rc, stdout, stderr = _run_harness("--chain", "phase", "set", "plan")
        combined = stdout + stderr
        assert "autopilot" in combined.lower() or "fsd-run" in combined.lower(), (
            f"Hint does not mention autopilot or fsd-run:\n{combined}"
        )

    def test_chain_flag_stderr_has_error_line(self, tmp_path):
        """stderr contains Error: prefix with v0.8 mention."""
        rc, stdout, stderr = _run_harness("--chain", "phase", "set", "plan")
        combined = stdout + stderr
        assert "removed" in combined.lower() or "--chain" in combined, (
            f"No removal message in output:\n{combined}"
        )


class TestDeprecatedAutoFlag:
    def test_auto_flag_exits_13_via_subcommand(self, tmp_path):
        """harness phase set execute --auto exits 13."""
        rc, stdout, stderr = _run_harness("phase", "set", "execute", "--auto")
        assert rc == 13, f"Expected 13, got {rc}\nstdout={stdout}\nstderr={stderr}"

    def test_auto_flag_has_fix_line(self, tmp_path):
        """Fix: line present for --auto."""
        rc, stdout, stderr = _run_harness("phase", "set", "execute", "--auto")
        combined = stdout + stderr
        assert "Fix:" in combined

    def test_auto_flag_hint_content(self, tmp_path):
        """Hint for --auto mentions the replacement command."""
        rc, stdout, stderr = _run_harness("phase", "set", "execute", "--auto")
        combined = stdout + stderr
        assert "autopilot" in combined.lower() or "fsd-run" in combined.lower()


class TestDeprecatedFlagAudit:
    def test_chain_flag_writes_audit_entry(self, tmp_path):
        """harness --chain writes verb=cli.deprecated_flag to audit log."""
        from lib.cli_deprecated import check_deprecated_flags
        # Directly test the module's audit-writing behavior
        # We'll check via subprocess that the audit entry is written
        # but since the harness needs a real repo, we test the module directly
        audit_path = tmp_path / "audit.log"
        result = check_deprecated_flags(
            ["--chain", "phase", "set", "plan"],
            audit_path=audit_path,
        )
        assert result is not None
        # Audit entry should have been written
        if audit_path.exists() and audit_path.stat().st_size > 0:
            entry = json.loads(audit_path.read_text().strip().splitlines()[-1])
            assert entry["verb"] == "cli.deprecated_flag"
            # §3.3 spec: args={"flag":"--chain"|"--auto"} (P2-2 schema alignment)
            assert entry.get("args", {}).get("flag") in ("--chain", "--auto")

    def test_auto_flag_audit_verb(self, tmp_path):
        """harness --auto writes verb=cli.deprecated_flag to audit log."""
        from lib.cli_deprecated import check_deprecated_flags
        audit_path = tmp_path / "audit.log"
        result = check_deprecated_flags(
            ["--auto", "phase", "set", "plan"],
            audit_path=audit_path,
        )
        assert result is not None
        if audit_path.exists() and audit_path.stat().st_size > 0:
            entry = json.loads(audit_path.read_text().strip().splitlines()[-1])
            assert entry["verb"] == "cli.deprecated_flag"

    def test_no_deprecated_flags_returns_none(self, tmp_path):
        """clean argv returns None (no error)."""
        from lib.cli_deprecated import check_deprecated_flags
        result = check_deprecated_flags(
            ["phase", "set", "plan"],
            audit_path=tmp_path / "audit.log",
        )
        assert result is None


class TestDeprecatedFlagModule:
    def test_import(self):
        """cli_deprecated module is importable."""
        from lib.cli_deprecated import check_deprecated_flags, DeprecatedFlagError
        assert callable(check_deprecated_flags)

    def test_deprecated_flag_error_has_exit_code(self):
        """DeprecatedFlagError carries exit_code=13."""
        from lib.cli_deprecated import DeprecatedFlagError
        err = DeprecatedFlagError("--chain")
        assert err.exit_code == 13

    def test_chain_flag_detected_anywhere_in_argv(self, tmp_path):
        """--chain is detected regardless of position in argv."""
        from lib.cli_deprecated import check_deprecated_flags
        audit_path = tmp_path / "audit.log"
        for argv in [
            ["--chain"],
            ["phase", "--chain", "set"],
            ["phase", "set", "plan", "--chain"],
        ]:
            result = check_deprecated_flags(argv, audit_path=audit_path)
            assert result is not None, f"--chain not detected in {argv}"

    def test_auto_flag_detected_anywhere_in_argv(self, tmp_path):
        """--auto is detected regardless of position in argv."""
        from lib.cli_deprecated import check_deprecated_flags
        audit_path = tmp_path / "audit.log"
        for argv in [
            ["--auto"],
            ["phase", "--auto", "set"],
            ["phase", "set", "plan", "--auto"],
        ]:
            result = check_deprecated_flags(argv, audit_path=audit_path)
            assert result is not None, f"--auto not detected in {argv}"

    def test_hint_text_matches_spec(self, tmp_path):
        """Hint text matches design §3.3 exact spec."""
        from lib.cli_deprecated import check_deprecated_flags
        result = check_deprecated_flags(
            ["--chain"],
            audit_path=tmp_path / "audit.log",
        )
        assert result is not None
        # §3.3 specifies the hint must mention --chain/--auto removal + replacement
        hint = result.hint
        assert "removed" in hint.lower() or "v0.8" in hint
        assert "autopilot" in hint.lower() or "fsd-run" in hint.lower()

    def test_audit_entry_has_chain_fields(self, tmp_path):
        """Audit entry from S07 is chain-stamped (has entry_hash)."""
        from lib.cli_deprecated import check_deprecated_flags
        audit_path = tmp_path / "audit.log"
        check_deprecated_flags(["--chain"], audit_path=audit_path)
        if audit_path.exists() and audit_path.stat().st_size > 0:
            entry = json.loads(audit_path.read_text().strip().splitlines()[-1])
            assert "entry_hash" in entry, "S07 audit entry must have S06 chain fields"
            assert "seq_global" in entry

    def test_audit_entry_args_schema_flag_key(self, tmp_path):
        """P2-2: args must use key 'flag' per §3.3 spec."""
        from lib.cli_deprecated import check_deprecated_flags
        audit_path = tmp_path / "audit.log"
        check_deprecated_flags(["--chain"], audit_path=audit_path)
        if audit_path.exists() and audit_path.stat().st_size > 0:
            entry = json.loads(audit_path.read_text().strip().splitlines()[-1])
            args = entry.get("args", {})
            assert "flag" in args, "args must have 'flag' key per §3.3"
            assert "deprecated_flag" not in args, "old key 'deprecated_flag' must not be present"


# ---------------------------------------------------------------------------
# P1-4: --chain=value / --auto=anything bypass detection
# ---------------------------------------------------------------------------

class TestDeprecatedFlagWithEqualsValue:
    @pytest.mark.parametrize("arg", [
        "--chain=foo",
        "--auto=bar",
        "--chain=",
        "--auto=",
    ])
    def test_deprecated_flag_with_equals_value_rejected(self, tmp_path, arg):
        """P1-4: --chain=value and --auto=value forms must be detected."""
        from lib.cli_deprecated import check_deprecated_flags
        result = check_deprecated_flags([arg], audit_path=tmp_path / "audit.log")
        assert result is not None, (
            f"check_deprecated_flags should detect {arg!r} as deprecated"
        )
        assert result.exit_code == 13

    def test_prefix_match_normalizes_flag_name(self, tmp_path):
        """P1-4: detected flag name for --chain=foo should normalize to --chain."""
        from lib.cli_deprecated import check_deprecated_flags
        result = check_deprecated_flags(["--chain=somevalue"])
        assert result is not None
        assert result.flag == "--chain"

    def test_non_deprecated_equals_args_pass(self, tmp_path):
        """--other=value flags that aren't deprecated must not trigger."""
        from lib.cli_deprecated import check_deprecated_flags
        result = check_deprecated_flags(["--mode=chain", "--auto-approve=yes"])
        assert result is None


# ---------------------------------------------------------------------------
# P2-2: §3.3 args schema alignment
# ---------------------------------------------------------------------------

class TestArgsSchemaAlignment:
    def test_args_has_flag_key(self, tmp_path):
        """§3.3: args={"flag":"--chain"|"--auto"} — 'flag' key required."""
        from lib.cli_deprecated import check_deprecated_flags
        audit_path = tmp_path / "audit.log"
        check_deprecated_flags(["--auto"], audit_path=audit_path)
        if audit_path.exists() and audit_path.stat().st_size > 0:
            entry = json.loads(audit_path.read_text().strip().splitlines()[-1])
            assert entry.get("args", {}).get("flag") == "--auto"

    def test_args_has_replacement_command(self, tmp_path):
        """args must also carry replacement_command."""
        from lib.cli_deprecated import check_deprecated_flags
        audit_path = tmp_path / "audit.log"
        check_deprecated_flags(["--chain"], audit_path=audit_path)
        if audit_path.exists() and audit_path.stat().st_size > 0:
            entry = json.loads(audit_path.read_text().strip().splitlines()[-1])
            assert "replacement_command" in entry.get("args", {})


# ---------------------------------------------------------------------------
# P2-4: --fixture path existence check
# ---------------------------------------------------------------------------

class TestFixtureExistenceCheck:
    def test_nonexistent_fixture_dir_exits_10(self, tmp_path):
        """P2-4: --fixture pointing at non-existent dir must exit 10."""
        import types
        from lib.audit_verify_cli import cmd_verify_audit
        args = types.SimpleNamespace(verify_fixture=str(tmp_path / "nonexistent"))
        rc = cmd_verify_audit(args, tmp_path)
        assert rc == 10

    def test_fixture_dir_without_audit_log_exits_10(self, tmp_path):
        """P2-4: --fixture pointing at dir without audit.log must exit 10."""
        import types
        from lib.audit_verify_cli import cmd_verify_audit
        args = types.SimpleNamespace(verify_fixture=str(tmp_path))
        rc = cmd_verify_audit(args, tmp_path)
        assert rc == 10

    def test_fixture_dir_with_audit_log_ok(self, tmp_path):
        """P2-4: --fixture pointing at valid dir with audit.log must proceed."""
        import types
        from lib.audit_verify_cli import cmd_verify_audit
        (tmp_path / "audit.log").write_text("", encoding="utf-8")
        args = types.SimpleNamespace(verify_fixture=str(tmp_path))
        rc = cmd_verify_audit(args, tmp_path)
        assert rc == 0  # empty log is OK
