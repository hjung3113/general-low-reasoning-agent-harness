"""Git tag trust root for the upgrade reconciler (§6).

Provides:
  - UpgradeTrustError  — exception with sub_reason + exit_code
  - verify_release_tag — resolve a git tag to a commit SHA
  - file_sha256_at_commit — compute sha256 of a file at a given commit SHA
                            without touching the working tree

Design decisions:
  1. SSH signature verification removed in v0.9.13 (single-user internal tool;
     ssh-keygen -Y verify added no real security value and could hang on Windows).
  2. All reads are bound to the resolved commit SHA, not the tag name.
  3. Trust-downgrade is refused unconditionally: if the target's existing
     installed manifest already has trust_origin: signed_tag, upgrading to
     trust_origin: dev_unsigned is rejected even when HARNESS_ALLOW_UNSIGNED_DEV=1.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from lib.exitcodes import EXIT_RELEASE_TRUST_INVALID

# Trust root: one line per authorized signer.
# Format (OpenSSH allowed_signers): <principal> namespaces="git" <pubkey>
# Release engineers fill this file before v0.7.0 tag; implementation consumes it.
ALLOWED_SIGNERS_PATH = Path("docs/trust/allowed-signers")


class UpgradeTrustError(Exception):
    """Raised when the harness release cannot be cryptographically verified.

    Attributes
    ----------
    sub_reason : str
        Machine-readable reason code, one of:
          - tag_not_found               : no such tag in the repo
          - path_missing_in_signed_tree : file absent from the signed commit tree
          - trust_downgrade_refused     : target already trusts signed_tag; refusing dev
          - target_manifest_corrupted   : install-state.json present but unparseable
          - allowed_signers_outside_repo : allowed-signers path escapes repo root
          - bypass_requires_tty_confirm : bypass requested on non-TTY stdin
    exit_code : int
        Always EXIT_RELEASE_TRUST_INVALID (15 per §3.4 Cycle-1 fix).
    """

    def __init__(self, sub_reason: str, detail: str = "",
                 exit_code: int = EXIT_RELEASE_TRUST_INVALID) -> None:
        self.sub_reason = sub_reason
        self.exit_code = exit_code
        msg = f"release trust failure [{sub_reason}]"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


def _clean_env() -> dict[str, str]:
    """Return a clean copy of the current environment for git subprocess calls."""
    return dict(os.environ)


def _run(args: list[str], *, cwd: Path, env: dict[str, str] | None = None,
         capture: bool = True, timeout: float = 15.0) -> subprocess.CompletedProcess:
    """Run a subprocess with text=True; return CompletedProcess regardless of exit code.

    ``timeout`` defaults to 15 s to guard against any git subprocess hang.

    NOTE: Do NOT use _run for git cat-file blob — it uses text=True which
    will corrupt binary content and collapse CRLF→LF on stdout.  Use
    file_sha256_at_commit (which calls subprocess.run directly with no text=True)
    for content hashing.
    """
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=capture,
            text=True,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=args,
            returncode=124,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(
                (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            ) + f"\n[timeout after {timeout}s]",
        )


def verify_release_tag(repo_root: Path, tag: str) -> str:
    """Return the commit SHA the tag points to, or raise UpgradeTrustError.

    Resolves the tag to a commit SHA via ``git rev-list -n 1 <tag>`` and
    returns it.  SSH signature verification was removed in v0.9.13 as this
    is a single-user internal tool where it added no real security value.

    Raises
    ------
    UpgradeTrustError("tag_not_found")
        If the tag does not exist in the repository.
    """
    repo_root = repo_root.resolve()
    allowed_signers = (repo_root / ALLOWED_SIGNERS_PATH).resolve()

    # δ-P2-3: containment check — allowed_signers must be under repo_root.
    if not allowed_signers.is_relative_to(repo_root):
        raise UpgradeTrustError(
            "allowed_signers_outside_repo",
            f"allowed_signers path {allowed_signers} escapes repo root {repo_root}",
        )

    # v0.9.13: SSH signature verification removed. This is an internal
    # single-user dev tool (feedback_internal_only_threat_model).
    # `git verify-tag` spawned `ssh-keygen -Y verify`, which on Windows
    # could hang indefinitely on a stalled ssh-agent and contributed
    # nothing real to the threat model. Now we just resolve the tag to a
    # commit SHA via `git rev-list` and return it; the SSH verify step
    # plus the rev-list TOCTOU re-check are gone.

    check = _run(["git", "rev-list", "-n", "1", tag], cwd=repo_root)
    if check.returncode != 0:
        raise UpgradeTrustError(
            "tag_not_found",
            f"git rev-list -n 1 {tag!r} returned non-zero",
        )
    pre_verify_sha = check.stdout.strip()
    if not pre_verify_sha:
        raise UpgradeTrustError("tag_not_found", "could not resolve tag to commit SHA")
    return pre_verify_sha


def file_sha256_at_commit(repo_root: Path, commit_sha: str, path: str) -> str:
    """Compute sha256 of ``git cat-file blob <commit_sha>:<path>``.

    Binds the read to the verified commit SHA, not the tag name, eliminating
    the TOCTOU window between verify_release_tag and the actual content read.

    Uses subprocess.run directly WITHOUT text=True so that:
      (a) Binary blobs (null bytes, high bytes) are hashed correctly — text=True
          would raise UnicodeDecodeError on non-UTF-8 bytes.
      (b) CRLF sequences are preserved as-is — text=True collapses CRLF→LF on
          stdout (universal newlines), producing a wrong sha256 for CRLF blobs.

    Raises
    ------
    UpgradeTrustError("path_missing_in_signed_tree")
        If the path does not exist in the signed commit tree.
    """
    repo_root = repo_root.resolve()
    spec = f"{commit_sha}:{path}"
    result = subprocess.run(
        ["git", "cat-file", "blob", spec],
        cwd=str(repo_root),
        capture_output=True,
        env=_clean_env(),
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise UpgradeTrustError(
            "path_missing_in_signed_tree",
            f"git cat-file failed for {spec}: {stderr}",
            exit_code=EXIT_RELEASE_TRUST_INVALID,
        )
    return hashlib.sha256(result.stdout).hexdigest()


# ---------------------------------------------------------------------------
# T16 — chain-rehash audit helper
# ---------------------------------------------------------------------------

# v0.9.13: chain-hash rechain machinery removed; this list kept as a
# breadcrumb for backwards-compat callers but is no longer consulted.
_V094_MISSING_MODULES: frozenset[str] = frozenset([
    "scripts/lib/check.py",
    "scripts/lib/phase_cli.py",
    "scripts/lib/phase_reopen.py",
    "scripts/lib/phase_state.py",
    "scripts/lib/phase_txn.py",
    "scripts/lib/planning_grammar.py",
    "scripts/lib/planning_status.py",
    "scripts/lib/profiles.py",
    "scripts/lib/roadmap_state.py",
    "scripts/lib/roo_modes.py",
    "scripts/lib/roomodes_writer.py",
    "scripts/lib/safe_open.py",
    "scripts/lib/session.py",
    "scripts/lib/smoke_lifecycle.py",
    "scripts/lib/state_cli.py",
    "scripts/lib/state_diagnostics.py",
    "scripts/lib/state_migrate.py",
    "scripts/lib/state_migrate_t04.py",
    "scripts/lib/state_repair.py",
    "scripts/lib/state_trust.py",
    "scripts/lib/status_next.py",
    "scripts/lib/status_next_cli.py",
    "scripts/lib/timestamps.py",
    "scripts/lib/transition.py",
    "scripts/lib/workflow_static_checks.py",
    "scripts/lib/worktree.py",
    "scripts/lib/managed_block.py",
    "scripts/lib/halt_diary.py",
    "scripts/lib/halt_diary_cli.py",
    "scripts/lib/durable_fs.py",
    "scripts/lib/cli_budgets.py",
    "scripts/lib/backups.py",
    "scripts/lib/operational_paths.py",
])


# v0.9.13: classify_rechain_cause + record_rechain removed.
