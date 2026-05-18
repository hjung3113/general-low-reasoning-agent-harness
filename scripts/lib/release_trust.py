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
    exit_code : int
        Always EXIT_RELEASE_TRUST_INVALID (17).
    """

    def __init__(self, sub_reason: str, detail: str = "") -> None:
        self.sub_reason = sub_reason
        self.exit_code = EXIT_RELEASE_TRUST_INVALID
        msg = f"release trust failure [{sub_reason}]"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


def _run(args: list[str], *, cwd: Path, env: dict[str, str] | None = None,
         capture: bool = True) -> subprocess.CompletedProcess:
    """Run a subprocess; return CompletedProcess regardless of exit code."""
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
    allowed_signers = repo_root / ALLOWED_SIGNERS_PATH

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
    env = dict(os.environ)
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

    Raises
    ------
    UpgradeTrustError("path_missing_in_signed_tree")
        If the path does not exist in the signed commit tree.
    """
    repo_root = repo_root.resolve()
    spec = f"{commit_sha}:{path}"
    result = _run(["git", "cat-file", "blob", spec], cwd=repo_root)
    if result.returncode != 0:
        raise UpgradeTrustError(
            "path_missing_in_signed_tree",
            f"{spec!r} not found in signed commit tree",
        )
    content = result.stdout.encode("utf-8", errors="surrogateescape")
    return hashlib.sha256(content).hexdigest()
