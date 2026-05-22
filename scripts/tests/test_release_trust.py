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
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def _setup_repo_with_binary(tmp: Path, *, key_file: Path, binary_content: bytes,
                             filename: str = "binary.bin") -> tuple[Path, str]:
    """Initialise a test git repo with a binary file; return (repo_root, commit_sha).

    No signed tag needed — we only exercise file_sha256_at_commit directly.
    """
    repo = tmp / f"repo_binary_{filename.replace('.', '_')}"
    repo.mkdir(exist_ok=True)

    _git(["init", "-b", "main"], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    _git(["config", "commit.gpgsign", "false"], cwd=repo)

    # Disable CRLF translation globally for this repo so binary bytes are stored as-is.
    _git(["config", "core.autocrlf", "false"], cwd=repo)

    (repo / "docs" / "trust").mkdir(parents=True)
    (repo / "docs" / "trust" / "allowed-signers").write_text("# placeholder\n")

    # Write the binary file directly via Path.write_bytes to bypass any Python text encoding.
    (repo / filename).write_bytes(binary_content)
    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", "add binary file"], cwd=repo)
    commit_sha = _git(["rev-parse", "HEAD"], cwd=repo)

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
        self.assertEqual(EXIT_RELEASE_TRUST_INVALID, 15)  # §3.4: 15 is free; 17 is human_action_required


@unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen unavailable")
class TestFileSha256BinaryAndCRLF(unittest.TestCase):
    """δ-P0: verify file_sha256_at_commit is binary-safe and CRLF-preserving."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._tmp = Path(cls._tmpdir.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_binary_blob_correct_sha256(self) -> None:
        """file_sha256_at_commit returns the correct sha256 for binary content with null + high bytes."""
        binary_content = b"\x00\x01\xff\xfe"
        repo, commit_sha = _setup_repo_with_binary(
            self._tmp, key_file=self._tmp / "nonexistent",
            binary_content=binary_content, filename="blob.bin"
        )
        sha = file_sha256_at_commit(repo, commit_sha, "blob.bin")
        expected = hashlib.sha256(binary_content).hexdigest()
        self.assertEqual(sha, expected, (
            "file_sha256_at_commit must hash raw bytes, not text-decoded content"
        ))

    def test_crlf_blob_sha256_not_collapsed(self) -> None:
        """file_sha256_at_commit preserves CRLF — sha256 must match raw CRLF bytes."""
        crlf_content = b"line1\r\nline2\r\n"
        repo, commit_sha = _setup_repo_with_binary(
            self._tmp, key_file=self._tmp / "nonexistent2",
            binary_content=crlf_content, filename="crlf.txt"
        )
        sha = file_sha256_at_commit(repo, commit_sha, "crlf.txt")
        expected_crlf = hashlib.sha256(crlf_content).hexdigest()
        lf_only = hashlib.sha256(b"line1\nline2\n").hexdigest()
        self.assertEqual(sha, expected_crlf, (
            "file_sha256_at_commit must preserve CRLF bytes; "
            f"got sha256={sha!r} but CRLF-expected={expected_crlf!r}, "
            f"LF-collapsed={lf_only!r}"
        ))
        self.assertNotEqual(sha, lf_only, (
            "sha256 must NOT match the LF-collapsed version"
        ))

    def test_allowed_signers_outside_repo_raises(self) -> None:
        """verify_release_tag raises allowed_signers_outside_repo if path escapes repo_root."""
        import tempfile as _tf
        import types
        from pathlib import Path as _P
        from lib import release_trust as _rt

        # Patch ALLOWED_SIGNERS_PATH to an absolute path outside the repo.
        original = _rt.ALLOWED_SIGNERS_PATH
        try:
            # Use an absolute path that starts with /tmp (outside any repo sub-tree).
            _rt.ALLOWED_SIGNERS_PATH = _P("/tmp/evil-allowed-signers")
            with tempfile.TemporaryDirectory() as td:
                repo = _P(td)
                # Init a minimal git repo so rev-list doesn't fail for wrong reason.
                subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=True)
                with self.assertRaises(UpgradeTrustError) as ctx:
                    _rt.verify_release_tag(repo, "v0.0.1")
                self.assertEqual(ctx.exception.sub_reason, "allowed_signers_outside_repo")
        finally:
            _rt.ALLOWED_SIGNERS_PATH = original


if __name__ == "__main__":
    unittest.main()
