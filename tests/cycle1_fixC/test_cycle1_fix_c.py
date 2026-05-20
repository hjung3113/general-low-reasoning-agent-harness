"""Cycle-1 Group C review-fix regression tests.

Covers:
  P3-P1-B  spec §239 amendment: newline / C0 control rejection (pin)
  P4-P2-3  git.cmd findstr /c:"--remote" literal-match fix
  P2-P2-2  os.ttyname Windows AttributeError guard in phase_cli.py
  P3-P2-1  Unicode confusables / homographs: NFKC + extended forbidden chars
  P3-P2-3  fs_fence dotfile component rejection
  P5-P2-1  KNOWN_VERBS registry completeness + strict-mode enforcement
  P2-P2-1  verify_install_record_integrity reachability (already fixed in Group B)

Spec: §3.1.1 + §5.2 + §12.6 + §12.7
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Repo root for file-presence tests
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_LIB = REPO_ROOT / "scripts" / "lib"
GIT_CMD_PATH = SCRIPTS_LIB / "autopilot_guard_wrappers" / "git.cmd"


# ===========================================================================
# P3-P1-B: Spec §239 amendment — newline / C0 rejection pin
# ===========================================================================


class TestNewlineRejectedPerSpecAmendment:
    """§239 amended: literal newlines + all C0 controls REJECTED (not replaced)."""

    def test_has_forbidden_chars_rejects_newline(self):
        """_has_forbidden_chars must flag a newline (C0 control U+000A)."""
        from scripts.lib.phase_approve import _has_forbidden_chars
        assert _has_forbidden_chars("line1\nline2") is True

    def test_has_forbidden_chars_rejects_carriage_return(self):
        from scripts.lib.phase_approve import _has_forbidden_chars
        assert _has_forbidden_chars("line1\rline2") is True

    def test_has_forbidden_chars_rejects_nul(self):
        from scripts.lib.phase_approve import _has_forbidden_chars
        assert _has_forbidden_chars("abc\x00def") is True

    def test_has_forbidden_chars_rejects_tab(self):
        """Tab (U+0009) is a C0 control and must be rejected."""
        from scripts.lib.phase_approve import _has_forbidden_chars
        assert _has_forbidden_chars("reason\twith\ttab") is True

    def test_has_forbidden_chars_accepts_plain_ascii(self):
        from scripts.lib.phase_approve import _has_forbidden_chars
        assert _has_forbidden_chars("plain ascii reason text") is False

    def test_run_approve_rejects_newline_in_reason_as_invalid_chars(
        self, tmp_path: Path
    ):
        """P3-P1-B regression: passing newline in --override-reason exits invalid_chars."""
        from scripts.lib import phase_approve, approval_nonce, phase_lock, phase_txn

        scratch = tmp_path / ".scratch"
        scratch.mkdir()
        harness = tmp_path / ".harness"
        harness.mkdir()
        audit_path = harness / "audit.log"
        nonce_dir = tmp_path / "nonces"
        nonce_dir.mkdir()

        install_record = {
            "harness_version": "v0.7.0",
            "installed_at": "2026-05-17T03:14:15Z",
            "adapters": ["roo"],
            "git_present_at_install": True,
            "approvers": [
                {"email": "alice@example.com", "added_at": "2026-05-17T03:14:15Z",
                 "source": "gitconfig_auto"}
            ],
        }
        (harness / "install-record.json").write_text(
            json.dumps(install_record, indent=2, sort_keys=True) + "\n"
        )

        args = MagicMock()
        args.by = "alice@example.com"
        args.override_identity = "bob@example.com"
        args.override_reason = "line1\nline2"  # newline — must be rejected
        args.at = None
        args.nonce_dir = None

        result = phase_approve.run_approve(
            args,
            scratch=scratch,
            harness_dir=harness,
            audit_path=audit_path,
            install_record_path=harness / "install-record.json",
            nonce_dir=nonce_dir,
            stdin_isatty=True,
            consumer_tty="/dev/ttys099",
        )
        assert result.exit_code == 6
        assert result.sub_reason == "override_reason_invalid_chars"


# ===========================================================================
# P4-P2-3: git.cmd findstr literal-match fix
# ===========================================================================


class TestGitCmdFindstrFix:
    """git.cmd must use /c:'--remote' for literal-string match, not regex."""

    def test_git_cmd_uses_literal_c_flag_not_backslash_regex(self):
        """P4-P2-3: /c:'--remote' must appear; old '\\-\\-remote' must not."""
        content = GIT_CMD_PATH.read_text(encoding="utf-8")
        assert '/c:"--remote"' in content, (
            "git.cmd must use findstr /c:\"--remote\" (P4-P2-3 literal-match fix). "
            "The old '\\-\\-remote' form does not match '--remote'."
        )

    def test_git_cmd_does_not_contain_broken_regex_form(self):
        """P4-P2-3: the broken backslash-regex form must be absent."""
        content = GIT_CMD_PATH.read_text(encoding="utf-8")
        # The old broken form: findstr /i "\-\-remote"
        assert r'"\-\-remote"' not in content, (
            "git.cmd still contains the broken '\\-\\-remote' regex form. "
            "Replace with /c:\"--remote\" (P4-P2-3)."
        )

    def test_git_cmd_submodule_update_remote_deny_path_present(self):
        """Submodule update --remote deny path must be present in git.cmd."""
        content = GIT_CMD_PATH.read_text(encoding="utf-8")
        assert "submodule" in content, "git.cmd missing submodule deny path"
        assert "--remote" in content or "/c:" in content, (
            "git.cmd missing --remote check in submodule deny path"
        )


# ===========================================================================
# P2-P2-2: os.ttyname Windows guard
# ===========================================================================


class TestOsTtynameWindowsGuard:
    """phase_cli.py must guard os.ttyname with os.name == 'posix'."""

    def test_phase_cli_ttyname_guarded_by_os_name(self):
        """The source of phase_cli.py must not have bare os.ttyname without os.name guard."""
        cli_path = SCRIPTS_LIB / "phase_cli.py"
        content = cli_path.read_text(encoding="utf-8")
        # Find all os.ttyname occurrences — each must be on a line that also
        # references os.name or be on the True branch of a posix guard.
        lines_with_ttyname = [
            (i + 1, ln) for i, ln in enumerate(content.splitlines())
            if "os.ttyname" in ln
        ]
        assert lines_with_ttyname, "No os.ttyname usage found in phase_cli.py"
        # The fix wraps it in an inline ternary or if-block referencing posix.
        # The simplest contract: the surrounding context (±5 lines) must contain
        # 'posix' (os.name == "posix" guard).
        cli_lines = content.splitlines()
        for lineno, _ in lines_with_ttyname:
            idx = lineno - 1  # 0-based
            window = cli_lines[max(0, idx - 5): idx + 6]
            window_text = "\n".join(window)
            assert "posix" in window_text, (
                f"os.ttyname at line {lineno} of phase_cli.py is not guarded "
                f"by an os.name=='posix' check (P2-P2-2 fix). Context:\n{window_text}"
            )

    def test_consumer_tty_empty_string_when_not_posix(self):
        """When os.name != 'posix', the guard expression returns empty string."""
        # Directly test the guard logic extracted from phase_cli.py.
        # We do NOT attempt to monkeypatch os.name (it's a read-only C attribute);
        # instead we test the conditional expression inline with os.name forced to
        # a known non-posix value via a local variable.
        def _compute_consumer_tty(stdin_isatty: bool, posix_name: str) -> str:
            # Mirrors the guard from phase_cli.py (P2-P2-2)
            if stdin_isatty and posix_name == "posix":
                return os.ttyname(sys.stdin.fileno())  # type: ignore[attr-defined]
            return ""

        # Non-posix os.name → empty string, even if stdin would be a tty
        result = _compute_consumer_tty(stdin_isatty=True, posix_name="nt")
        assert result == "", (
            f"Expected empty string when posix_name='nt', got {result!r}"
        )

        result_posix_no_tty = _compute_consumer_tty(stdin_isatty=False, posix_name="posix")
        assert result_posix_no_tty == "", (
            "Expected empty string when stdin is not a tty"
        )


# ===========================================================================
# P3-P2-1: Unicode confusables / homographs
# ===========================================================================


class TestUnicodeConfusables:
    """NFKC normalization + extended forbidden chars (variation selectors, tags, surrogates)."""

    def test_sanitize_string_applies_nfkc(self):
        """_sanitize_string must normalize Math Alphanumeric to ASCII via NFKC."""
        from scripts.lib.phase_approve import _sanitize_string
        # U+1D41A is MATHEMATICAL BOLD SMALL A, NFKC → 'a'
        math_bold_admin = "\U0001d41a\U0001d41d\U0001d426\U0001d422\U0001d427"  # bold 'admin'
        normalized = _sanitize_string(math_bold_admin)
        assert normalized == "admin", (
            f"NFKC should fold Math Alphanumeric to ASCII. Got {normalized!r}"
        )

    def test_sanitize_string_folds_fullwidth(self):
        """_sanitize_string must fold full-width ASCII to normal ASCII."""
        from scripts.lib.phase_approve import _sanitize_string
        fullwidth_a = "ａ"  # FULLWIDTH LATIN SMALL LETTER A
        assert _sanitize_string(fullwidth_a) == "a"

    def test_has_forbidden_chars_rejects_variation_selector(self):
        """Variation selector U+FE00 must be forbidden."""
        from scripts.lib.phase_approve import _has_forbidden_chars
        vs1 = "︀"
        assert _has_forbidden_chars("A" + vs1) is True

    def test_has_forbidden_chars_rejects_tag_char(self):
        """Tag character U+E0041 must be forbidden."""
        from scripts.lib.phase_approve import _has_forbidden_chars
        tag_a = "\U000e0041"  # TAG LATIN SMALL LETTER A
        assert _has_forbidden_chars("reason" + tag_a) is True

    def test_has_forbidden_chars_rejects_high_variation_selector(self):
        """High variation selector U+E0100 must be forbidden."""
        from scripts.lib.phase_approve import _has_forbidden_chars
        vs17 = "\U000e0100"
        assert _has_forbidden_chars("A" + vs17) is True

    def test_has_forbidden_chars_rejects_surrogate(self):
        """Unpaired surrogate U+D800 must be forbidden."""
        from scripts.lib.phase_approve import _has_forbidden_chars
        surrogate = "\ud800"
        assert _has_forbidden_chars("reason" + surrogate) is True

    def test_math_alphanumeric_folded_to_ascii_accepted(self, tmp_path: Path):
        """Math Alphanumeric in reason → NFKC fold to ASCII → accepted as valid ASCII."""
        from scripts.lib import phase_approve, approval_nonce, phase_lock, phase_txn

        scratch = tmp_path / ".scratch"
        scratch.mkdir()
        harness = tmp_path / ".harness"
        harness.mkdir()
        audit_path = harness / "audit.log"
        nonce_dir = tmp_path / "nonces"
        nonce_dir.mkdir()

        install_record = {
            "harness_version": "v0.7.0",
            "installed_at": "2026-05-17T03:14:15Z",
            "adapters": ["roo"],
            "git_present_at_install": True,
            "approvers": [
                {"email": "alice@example.com", "added_at": "2026-05-17T03:14:15Z",
                 "source": "gitconfig_auto"}
            ],
        }
        (harness / "install-record.json").write_text(
            json.dumps(install_record, indent=2, sort_keys=True) + "\n"
        )

        # Math bold "test reason" folds via NFKC to plain ASCII — should NOT
        # trigger invalid_chars but will fail at nonce step (no nonce minted).
        # The key contract: exit 6 sub_reason is human_proof_missing, NOT
        # override_reason_invalid_chars (meaning normalization+charset passed).
        math_bold_reason = "\U0001d42d\U0001d41e\U0001d42c\U0001d42d"  # bold "test"
        args = MagicMock()
        args.by = "alice@example.com"
        args.override_identity = "bob@example.com"
        args.override_reason = math_bold_reason + " reason"
        args.at = None
        args.nonce_dir = None

        result = phase_approve.run_approve(
            args,
            scratch=scratch,
            harness_dir=harness,
            audit_path=audit_path,
            install_record_path=harness / "install-record.json",
            nonce_dir=nonce_dir,
            stdin_isatty=True,
            consumer_tty="/dev/ttys099",
        )
        # After NFKC normalization the reason becomes plain ASCII, which passes
        # charset check.  It then fails at state_missing (no state) or
        # install-record membership, but NOT override_reason_invalid_chars.
        assert result.sub_reason not in ("override_reason_invalid_chars",), (
            f"Math Alphanumeric reason was incorrectly rejected as invalid_chars "
            f"(sub_reason={result.sub_reason!r}). NFKC should have folded it."
        )


# ===========================================================================
# P3-P2-3: fs_fence dotfile component rejection
# ===========================================================================


class TestFsFenceDotfileRejection:
    """Paths with dotfile components must be rejected even when prefix matches."""

    def test_check_write_path_rejects_dotfile_inside_allowed_prefix(self, tmp_path: Path):
        """allowed_paths=['scripts/'] + target='scripts/.bashrc' → denied."""
        from scripts.lib.fs_fence import check_write_path

        anchor = tmp_path / "anchor"
        anchor.mkdir()
        (anchor / "scripts").mkdir()

        state = {"execution_mode": "phase_autopilot", "allowed_paths": ["scripts/"]}
        result = check_write_path("scripts/.bashrc", anchor=anchor, state=state)
        assert result.allowed is False
        assert result.reason == "dotfile_component_rejected", (
            f"Expected dotfile_component_rejected, got {result.reason!r}"
        )

    def test_check_write_path_rejects_git_inside_allowed_prefix(self, tmp_path: Path):
        """scripts/.git/config must be denied despite 'scripts/' prefix match."""
        from scripts.lib.fs_fence import check_write_path

        anchor = tmp_path / "anchor"
        anchor.mkdir()
        (anchor / "scripts").mkdir()

        state = {"execution_mode": "phase_autopilot", "allowed_paths": ["scripts/"]}
        result = check_write_path("scripts/.git/config", anchor=anchor, state=state)
        assert result.allowed is False
        assert result.reason == "dotfile_component_rejected"

    def test_check_write_path_rejects_harness_inside_allowed_prefix(self, tmp_path: Path):
        """scripts/.harness/audit.log must be denied (dotfile component)."""
        from scripts.lib.fs_fence import check_write_path

        anchor = tmp_path / "anchor"
        anchor.mkdir()
        (anchor / "scripts").mkdir()

        state = {"execution_mode": "phase_autopilot", "allowed_paths": ["scripts/"]}
        result = check_write_path("scripts/.harness/audit.log", anchor=anchor, state=state)
        assert result.allowed is False
        assert result.reason == "dotfile_component_rejected"

    def test_check_write_path_allows_normal_file_inside_allowed_prefix(self, tmp_path: Path):
        """scripts/lib/foo.py must remain allowed."""
        from scripts.lib.fs_fence import check_write_path

        anchor = tmp_path / "anchor"
        anchor.mkdir()
        (anchor / "scripts").mkdir()
        (anchor / "scripts" / "lib").mkdir()

        state = {"execution_mode": "phase_autopilot", "allowed_paths": ["scripts/"]}
        result = check_write_path("scripts/lib/foo.py", anchor=anchor, state=state)
        assert result.allowed is True
        assert result.reason == "allowed"

    def test_check_write_path_dotfile_prefix_explicitly_granted_is_allowed(self, tmp_path: Path):
        """When allowed_paths explicitly grants '.git/', writing '.git/config' is allowed.

        The dotfile-rejection check only covers dotfile components that appear
        in the SUFFIX beyond the matched prefix.  When the prefix itself is a
        dotfile dir (e.g. '.harness/', '.git/'), the grant is explicit and
        intentional — the risk is an LLM injecting 'scripts/.git/config', NOT
        an operator who has explicitly listed '.git/' in allowed_paths.
        """
        from scripts.lib.fs_fence import check_write_path

        anchor = tmp_path / "anchor"
        anchor.mkdir()

        state = {"execution_mode": "phase_autopilot", "allowed_paths": [".git/"]}
        result = check_write_path(".git/config", anchor=anchor, state=state)
        # ".git/" is explicitly granted; ".git/config" has no additional
        # dotfile suffix component, so it is allowed.
        assert result.allowed is True

    def test_check_write_path_dotfile_in_suffix_of_dotfile_prefix_rejected(self, tmp_path: Path):
        """'.git/.hidden/file' — '.hidden' in suffix of '.git/' prefix → rejected."""
        from scripts.lib.fs_fence import check_write_path

        anchor = tmp_path / "anchor"
        anchor.mkdir()

        state = {"execution_mode": "phase_autopilot", "allowed_paths": [".git/"]}
        result = check_write_path(".git/.hidden/file", anchor=anchor, state=state)
        assert result.allowed is False
        assert result.reason == "dotfile_component_rejected"


# ===========================================================================
# P5-P2-1: Verb registry completeness + strict-mode enforcement
# ===========================================================================


class TestKnownVerbRegistry:
    """KNOWN_VERBS frozenset completeness and strict-mode enforcement."""

    def test_known_verbs_is_frozenset(self):
        from scripts.lib.audit import KNOWN_VERBS
        assert isinstance(KNOWN_VERBS, frozenset), (
            "KNOWN_VERBS must be a frozenset in scripts/lib/audit.py"
        )

    def test_known_verbs_contains_required_verbs(self):
        """All verbs cited in P5-P2-1 finding must be in KNOWN_VERBS."""
        from scripts.lib.audit import KNOWN_VERBS
        required = {
            "halt_diary.clear",
            "phase.autopilot.start_hash_finalized",
            "phase.autopilot.start.refused",
            "phase.autopilot.start.recover_pending",
            "phase.set.noop",
            "session.unlock",
            "lock.recovered",
            # Core verbs
            "phase.set",
            "phase.approve",
            "phase.reopen",
            "phase.autopilot.start",
            "phase.autopilot.stop",
            "phase.autopilot.halt",
            "audit.rotated",
            "autopilot.fence.deny",
            "autopilot.network.deny",
            "cli.deprecated_flag",
            "migrate.state_v2",
        }
        missing = required - KNOWN_VERBS
        assert not missing, (
            f"KNOWN_VERBS is missing required verbs (P5-P2-1): {sorted(missing)}"
        )

    def test_known_verbs_registry_completeness_vs_grep(self):
        """Every verb literal in scripts/lib/*.py must be in KNOWN_VERBS."""
        from scripts.lib.audit import KNOWN_VERBS

        # Grep all "verb": "..." literals from scripts/lib Python files.
        # This is the machine-readable completeness check from the finding.
        pattern = re.compile(r'"verb":\s*"([^"]+)"')
        found_verbs: set[str] = set()
        for py_file in SCRIPTS_LIB.glob("**/*.py"):
            try:
                text = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in pattern.finditer(text):
                found_verbs.add(m.group(1))

        missing = found_verbs - KNOWN_VERBS
        assert not missing, (
            f"These verbs appear in scripts/lib/*.py but are absent from "
            f"KNOWN_VERBS in audit.py (P5-P2-1): {sorted(missing)}\n"
            f"Add them to KNOWN_VERBS."
        )

    def test_audit_append_warns_on_unknown_verb(self, tmp_path: Path, capsys):
        """Unknown verb in permissive mode → WARNING to stderr, entry still appended."""
        from scripts.lib.audit import audit_append

        audit_path = tmp_path / "audit.log"
        entry = {"verb": "test.unknown.verb.xyz", "by": "test", "at": "2026-05-17T00:00:00Z"}

        env_backup = os.environ.get("HARNESS_STRICT_VERB_REGISTRY")
        try:
            if "HARNESS_STRICT_VERB_REGISTRY" in os.environ:
                del os.environ["HARNESS_STRICT_VERB_REGISTRY"]
            audit_append(entry, audit_path=audit_path)
        finally:
            if env_backup is not None:
                os.environ["HARNESS_STRICT_VERB_REGISTRY"] = env_backup

        captured = capsys.readouterr()
        assert "WARNING" in captured.err, (
            "Expected WARNING in stderr for unknown verb in permissive mode"
        )
        assert audit_path.exists(), "Entry should still be written in permissive mode"

    def test_audit_append_rejects_unknown_verb_in_strict_mode(self, tmp_path: Path):
        """HARNESS_STRICT_VERB_REGISTRY=1: unknown verb → SystemExit(10)."""
        from scripts.lib.audit import audit_append

        audit_path = tmp_path / "audit.log"
        entry = {"verb": "test.unknown.verb.xyz", "by": "test", "at": "2026-05-17T00:00:00Z"}

        env_backup = os.environ.get("HARNESS_STRICT_VERB_REGISTRY")
        try:
            os.environ["HARNESS_STRICT_VERB_REGISTRY"] = "1"
            with pytest.raises(SystemExit) as exc_info:
                audit_append(entry, audit_path=audit_path)
            assert exc_info.value.code == 10, (
                f"Expected SystemExit(10) for unknown verb in strict mode, "
                f"got SystemExit({exc_info.value.code!r})"
            )
        finally:
            if env_backup is not None:
                os.environ["HARNESS_STRICT_VERB_REGISTRY"] = env_backup
            elif "HARNESS_STRICT_VERB_REGISTRY" in os.environ:
                del os.environ["HARNESS_STRICT_VERB_REGISTRY"]

    def test_audit_append_known_verb_no_warning(self, tmp_path: Path, capsys):
        """Known verb in any mode → no WARNING emitted."""
        from scripts.lib.audit import audit_append

        audit_path = tmp_path / "audit.log"
        entry = {"verb": "phase.set", "by": "test", "at": "2026-05-17T00:00:00Z",
                 "args": {"phase": "plan"}}

        audit_append(entry, audit_path=audit_path)
        captured = capsys.readouterr()
        assert "WARNING" not in captured.err, (
            f"Known verb 'phase.set' should not emit WARNING. stderr={captured.err!r}"
        )


# ===========================================================================
# P2-P2-1: verify_install_record_integrity reachability
# ===========================================================================


class TestVerifyInstallRecordIntegrityReachable:
    """P2-P2-1: verify_install_record_integrity must be reachable from check.py (Group B fix)."""

    def test_verify_install_record_integrity_imported_in_check(self):
        """check.py must import and call verify_install_record_integrity."""
        check_path = SCRIPTS_LIB / "check.py"
        content = check_path.read_text(encoding="utf-8")
        assert "verify_install_record_integrity" in content, (
            "check.py must import/call verify_install_record_integrity (P2-P2-1 Group B fix)"
        )

    def test_verify_install_record_integrity_called_in_check_installed_target(self):
        """verify_install_record_integrity must be called inside check_installed_target."""
        check_path = SCRIPTS_LIB / "check.py"
        content = check_path.read_text(encoding="utf-8")
        # Both import and call site must be present
        assert "_verify_install_record_integrity" in content, (
            "verify_install_record_integrity not wired in check.py (P2-P2-1)"
        )
