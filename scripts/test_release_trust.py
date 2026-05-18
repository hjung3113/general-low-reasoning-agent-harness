"""Tests for scripts/lib/release_trust.py — SSH-signed git tag trust root (§6).

Uses a real git repo in a tempdir with an ephemeral ed25519 key.
Gated on ssh-keygen availability.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Adjust sys.path so `lib.*` imports work when run from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.release_trust import UpgradeTrustError, file_sha256_at_commit, verify_release_tag


def _git(args: list[str], *, cwd: Path, env: dict | None = None, check: bool = True) -> str:
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, ["git"] + args, result.stdout, result.stderr
        )
    return result.stdout.strip()


def _setup_repo(tmp: Path, *, key_file: Path, principal: str = "release@harness") -> tuple[Path, str]:
    """Initialise a test git repo, create a signed tag, return (repo_root, commit_sha)."""
    repo = tmp / "repo"
    repo.mkdir()

    # Minimal git config for the test repo
    _git(["init", "-b", "main"], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    _git(["config", "commit.gpgsign", "false"], cwd=repo)
    _git(["config", "gpg.format", "ssh"], cwd=repo)
    _git(["config", "user.signingKey", str(key_file)], cwd=repo)

    # Create trust directory and allowed-signers
    trust_dir = repo / "docs" / "trust"
    trust_dir.mkdir(parents=True)
    pubkey = (Path(str(key_file) + ".pub")).read_text().strip()
    allowed = trust_dir / "allowed-signers"
    allowed.write_text(f'{principal} namespaces="git" {pubkey}\n')

    # Create a file to commit
    sample = repo / "hello.txt"
    sample.write_text("hello harness\n")
    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", "initial"], cwd=repo)
    commit_sha = _git(["rev-parse", "HEAD"], cwd=repo)

    # Sign the tag — set gpg.ssh.allowedSignersFile locally too so verify works
    _git(["config", "gpg.ssh.allowedSignersFile", str(allowed)], cwd=repo)
    _git(["tag", "-s", "v0.0.1", "-m", "test release"], cwd=repo)

    return repo, commit_sha


@unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen unavailable")
class TestVerifyReleaseTag(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmpdir.name)
        # Generate ephemeral ed25519 key
        cls._key = tmp / "id_ed25519"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(cls._key)],
            check=True,
            capture_output=True,
        )
        cls._repo, cls._commit_sha = _setup_repo(tmp, key_file=cls._key)
        cls._tmp = tmp

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_happy_path_returns_commit_sha(self) -> None:
        """verify_release_tag returns the commit SHA for a correctly signed tag."""
        result = verify_release_tag(self._repo, "v0.0.1")
        self.assertEqual(result, self._commit_sha)

    def test_tampered_allowed_signers_raises(self) -> None:
        """A different (wrong) public key in allowed-signers causes tag_signature_invalid."""
        tmp2 = self._tmp / "wrong_key_repo"
        tmp2.mkdir(exist_ok=True)
        # Generate a different key
        wrong_key = tmp2 / "id_ed25519_wrong"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(wrong_key)],
            check=True,
            capture_output=True,
        )
        # Build a repo clone with the wrong key in allowed-signers
        repo2 = tmp2 / "repo"
        # Copy the repo
        shutil.copytree(str(self._repo), str(repo2))
        # Overwrite allowed-signers with the wrong pubkey
        wrong_pub = (Path(str(wrong_key) + ".pub")).read_text().strip()
        allowed = repo2 / "docs" / "trust" / "allowed-signers"
        allowed.write_text(f'release@harness namespaces="git" {wrong_pub}\n')

        with self.assertRaises(UpgradeTrustError) as ctx:
            verify_release_tag(repo2, "v0.0.1")
        self.assertEqual(ctx.exception.sub_reason, "tag_signature_invalid")

    def test_missing_tag_raises(self) -> None:
        """A non-existent tag raises UpgradeTrustError with sub_reason=tag_not_found."""
        with self.assertRaises(UpgradeTrustError) as ctx:
            verify_release_tag(self._repo, "v999.0.0")
        self.assertEqual(ctx.exception.sub_reason, "tag_not_found")

    def test_file_sha256_at_commit_correct_hash(self) -> None:
        """file_sha256_at_commit returns the correct sha256 for an existing path."""
        sha = file_sha256_at_commit(self._repo, self._commit_sha, "hello.txt")
        expected = hashlib.sha256("hello harness\n".encode("utf-8")).hexdigest()
        self.assertEqual(sha, expected)

    def test_file_sha256_at_commit_absent_path_raises(self) -> None:
        """file_sha256_at_commit raises path_missing_in_signed_tree for a missing path."""
        with self.assertRaises(UpgradeTrustError) as ctx:
            file_sha256_at_commit(self._repo, self._commit_sha, "no_such_file.txt")
        self.assertEqual(ctx.exception.sub_reason, "path_missing_in_signed_tree")

    def test_exit_code_constant(self) -> None:
        """UpgradeTrustError carries EXIT_RELEASE_TRUST_INVALID as exit_code."""
        from lib.exitcodes import EXIT_RELEASE_TRUST_INVALID
        err = UpgradeTrustError("tag_not_found")
        self.assertEqual(err.exit_code, EXIT_RELEASE_TRUST_INVALID)
        self.assertEqual(EXIT_RELEASE_TRUST_INVALID, 17)


if __name__ == "__main__":
    unittest.main()
