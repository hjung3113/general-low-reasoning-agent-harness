"""SSH-signed git tag trust root for the upgrade reconciler (§6).

Provides:
  - UpgradeTrustError  — exception with sub_reason + exit_code
  - verify_release_tag — verify an SSH-signed git tag; return commit SHA
  - file_sha256_at_commit — compute sha256 of a file at a given commit SHA
                            without touching the working tree

Design decisions (mandated by adversarial review):
  1. SSH-signature format only (no GPG).  Git ≥ 2.34 supports gpg.format=ssh.
     Cross-platform: Git for Windows bundles ssh-keygen.  No ephemeral keyring.
  2. All reads after verification are bound to the verified commit SHA, not the
     tag name, to close the TOCTOU window (verify → read).
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
# Release engineers fill this file before v0.8.0 tag; implementation consumes it.
ALLOWED_SIGNERS_PATH = Path("docs/trust/allowed-signers")


class UpgradeTrustError(Exception):
    """Raised when the harness release cannot be cryptographically verified.

    Attributes
    ----------
    sub_reason : str
        Machine-readable reason code, one of:
          - tag_not_found           : no such tag in the repo
          - tag_signature_invalid   : git verify-tag returned non-zero
          - path_missing_in_signed_tree : file absent from the signed commit tree
          - trust_downgrade_refused : target already trusts signed_tag; refusing dev
          - target_manifest_corrupted : install-state.json present but unparseable
          - allowed_signers_outside_repo : allowed-signers path escapes repo root
          - bypass_requires_tty_confirm : bypass requested on non-TTY stdin
    exit_code : int
        Always EXIT_RELEASE_TRUST_INVALID (17).
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
    """Return a clean copy of the current environment for git subprocess calls.

    This helper centralises env preparation so callers can extend it
    (e.g. inject GIT_CONFIG_PARAMETERS) without duplicating dict(os.environ).
    """
    return dict(os.environ)


def _run(args: list[str], *, cwd: Path, env: dict[str, str] | None = None,
         capture: bool = True) -> subprocess.CompletedProcess:
    """Run a subprocess with text=True; return CompletedProcess regardless of exit code.

    NOTE: Do NOT use _run for git cat-file blob — it uses text=True which
    will corrupt binary content and collapse CRLF→LF on stdout.  Use
    file_sha256_at_commit (which calls subprocess.run directly with no text=True)
    for content hashing.
    """
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=capture,
        text=True,
        env=env,
    )


def verify_release_tag(repo_root: Path, tag: str) -> str:
    """Return the verified commit SHA the tag points to, or raise UpgradeTrustError.

    Steps:
      1. Set GIT_CONFIG_PARAMETERS to point gpg.ssh.allowedSignersFile at
         ``repo_root / ALLOWED_SIGNERS_PATH``.
      2. Run ``git verify-tag <tag>``; on non-zero exit raise
         UpgradeTrustError("tag_signature_invalid").
      3. Run ``git rev-list -n 1 <tag>`` to resolve to commit SHA.
      4. Return commit_sha.

    Raises
    ------
    UpgradeTrustError("tag_not_found")
        If the tag does not exist in the repository.
    UpgradeTrustError("tag_signature_invalid")
        If git verify-tag exits non-zero (unsigned, wrong key, tampered).
    """
    repo_root = repo_root.resolve()
    allowed_signers = (repo_root / ALLOWED_SIGNERS_PATH).resolve()

    # δ-P2-3: containment check — allowed_signers must be under repo_root.
    if not allowed_signers.is_relative_to(repo_root):
        raise UpgradeTrustError(
            "allowed_signers_outside_repo",
            f"allowed_signers path {allowed_signers} escapes repo root {repo_root}",
        )

    # Step 1: check the tag exists at all.
    check = _run(["git", "rev-list", "-n", "1", tag], cwd=repo_root)
    if check.returncode != 0:
        raise UpgradeTrustError(
            "tag_not_found",
            f"git rev-list -n 1 {tag!r} returned non-zero",
        )

    # Step 2: verify SSH signature.
    # Inject gpg.ssh.allowedSignersFile via GIT_CONFIG_PARAMETERS so we do not
    # mutate any user or system gitconfig.
    env = _clean_env()
    env["GIT_CONFIG_PARAMETERS"] = (
        f"'gpg.ssh.allowedSignersFile={allowed_signers}'"
    )
    verify = _run(["git", "verify-tag", tag], cwd=repo_root, env=env)
    if verify.returncode != 0:
        raise UpgradeTrustError(
            "tag_signature_invalid",
            (verify.stderr or verify.stdout or "").strip(),
        )

    # Step 3: resolve to commit SHA (already ran above; re-use output).
    commit_sha = check.stdout.strip()
    if not commit_sha:
        raise UpgradeTrustError("tag_signature_invalid", "could not resolve tag to commit SHA")
    return commit_sha


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
