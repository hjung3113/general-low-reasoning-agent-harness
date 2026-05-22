#!/usr/bin/env python3
"""Build reproducible v0.9.4 test fixtures for T15 upgrade-compat tests.

Produces two tarballs in --output-dir:
  v094-clean.tar.gz           — vanilla v0.9.4 init (missing 35 lib modules)
  v094-with-workaround.tar.gz — same + the 35 missing lib modules copied in

Tarballs are byte-identical across macOS, Linux, and different cwds because:
  • TarInfo.mtime = 0, uid/gid = 0, uname/gname = ""
  • mode = 0o644 (files) / 0o755 (dirs); all normalised
  • entries sorted lexicographically before adding
  • gzip written via gzip.GzipFile(mtime=0) — header timestamp suppressed

T7 changes:
  • .harness/ INCLUDED in tarball (needed by T8 upgrade tests to find installed-manifest.json)
  • _normalize_v094_install_state() strips non-deterministic fields from install state
  • HARNESS_FIXED_NOW_ISO env var pins installed_at timestamps
  • run_v094_init raises FixtureBuildError on non-zero exit (Hawk M-7)
  • Determinism self-check: builds twice in separate temp dirs; asserts sha256 equal

CI always rebuilds; tarballs are gitignored; only .sha256 files are checked-in.

Usage:
    python3 scripts/build_v094_fixture.py [--output-dir tests/fixtures]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

# Fixed epoch — 2026-05-21 00:00:00 UTC — for all TarInfo.mtime entries.
FIXED_MTIME = 1748822400

# Directories / files to exclude when archiving.
# NOTE: .harness is NOT excluded (T7) — fixture must include installed-manifest.json
EXCLUDE_NAMES = {"__pycache__", ".git", ".pytest_cache", ".DS_Store"}


class FixtureBuildError(RuntimeError):
    """Raised when a fixture build step fails in a way that should abort the build."""

# The 35 lib/*.py modules missing from v0.9.4 manifest.json (BUG-1).
MISSING_LIB_MODULES: list[str] = [
    "approval_nonce.py",
    "approve_nonce_cli.py",
    "audit.py",
    "audit_chain.py",
    "audit_rotation.py",
    "ci_provenance.py",
    "durable_fs.py",
    "fsd_wrappers.py",
    "hooks.py",
    "phase_approve.py",
    "phase_autopilot.py",
    "phase_autopilot_cli.py",
    "phase_cli.py",
    "phase_lock.py",
    "phase_preflight.py",
    "phase_reopen.py",
    "phase_state.py",
    "phase_txn.py",
    "roomodes_writer.py",
    "safe_open.py",
    "session.py",
    "state_trust.py",
    "timestamps.py",
    "transition.py",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _should_skip(name: str) -> bool:
    return name in EXCLUDE_NAMES


def build_deterministic_tarball(source_dir: Path, output_path: Path) -> str:
    """Create a deterministic gzip tarball from source_dir and write to output_path.

    Returns the sha256 hex digest of the produced tarball.
    """
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w:") as tar:  # type: ignore[arg-type]
            # Collect all entries, sorted lexicographically for determinism.
            entries: list[Path] = []
            for root, dirs, files in os.walk(source_dir):
                # Prune excluded dirs in-place so os.walk skips them.
                dirs[:] = sorted(d for d in dirs if not _should_skip(d))
                root_path = Path(root)
                rel_root = root_path.relative_to(source_dir)
                if rel_root != Path("."):
                    entries.append(root_path)
                for fname in sorted(files):
                    if not _should_skip(fname):
                        entries.append(root_path / fname)

            # Sort all collected paths lexicographically by their archive name.
            entries.sort(key=lambda p: str(p.relative_to(source_dir)))

            for entry in entries:
                rel = entry.relative_to(source_dir)
                info = tarfile.TarInfo(name=str(rel))
                info.mtime = FIXED_MTIME
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                if entry.is_dir():
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    tar.addfile(info)
                else:
                    info.mode = 0o644
                    info.size = entry.stat().st_size
                    with open(entry, "rb") as fh:
                        tar.addfile(info, fh)

    raw = buf.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(raw)
    return digest


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"+ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def setup_worktree(tag: str, worktree_path: Path) -> None:
    if worktree_path.exists():
        print(f"  Removing existing worktree at {worktree_path}", flush=True)
        run(["git", "worktree", "remove", "--force", str(worktree_path)], cwd=repo_root(), check=False)
        shutil.rmtree(worktree_path, ignore_errors=True)
    run(["git", "worktree", "add", "--detach", str(worktree_path), tag], cwd=repo_root())


def teardown_worktree(worktree_path: Path) -> None:
    run(["git", "worktree", "remove", "--force", str(worktree_path)], cwd=repo_root(), check=False)
    shutil.rmtree(worktree_path, ignore_errors=True)


def _recompute_chain_hash(data: dict) -> str:
    """Recompute installed_files_chain_hash from the manifest dict.

    Mirrors compute_manifest_hash_chain + verify_manifest_chain normalization
    in scripts/lib/manifest_reconciler.py.  Duplicated here to avoid importing
    lib at fixture-build time (import path may not be on sys.path during
    worktree init runs).

    IMPORTANT: the chain covers only installed_sha256/current_sha256 per file
    entry (other fields like policy, owner, sha256 are NOT part of the chain).
    This matches the normalization in verify_manifest_chain (lines ~370-378).
    """
    schema_version = data.get("schema_version", 0)
    harness_version = data.get("harness_version", "")
    raw_files: dict = data.get("files", {})
    removed: list = data.get("removed_in_version", [])
    trust_origin = data.get("trust_origin") or ""
    release_tag = data.get("release_tag") or ""
    release_commit = data.get("release_commit") or ""

    # Normalize files: only installed_sha256 + current_sha256 (§6 contract)
    normalized_files: dict = {
        path: {
            k: entry[k]
            for k in ("installed_sha256", "current_sha256")
            if k in entry
        }
        for path, entry in raw_files.items()
        if isinstance(entry, dict)
    }

    chain_parts: list[str] = [
        f"schema_version={schema_version}",
        f"harness_version={harness_version}",
        f"trust_origin={trust_origin}",
        f"release_tag={release_tag}",
        f"release_commit={release_commit}",
    ]
    for file_path in sorted(normalized_files.keys()):
        entry = normalized_files[file_path]
        entry_repr = json.dumps({k: entry[k] for k in sorted(entry.keys())}, sort_keys=True)
        chain_parts.append(f"file:{file_path}:{entry_repr}")
    for removed_entry in sorted(removed, key=lambda e: e.get("path", "")):
        removed_repr = json.dumps(
            {k: removed_entry[k] for k in sorted(removed_entry.keys())}, sort_keys=True
        )
        chain_parts.append(f"removed:{removed_repr}")

    canonical = "\n".join(chain_parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_v094_install_state(target_dir: Path) -> None:
    """Normalize the v0.9.4 installed-manifest.json for determinism.

    Strips non-deterministic fields:
    - installed_at: replaced with HARNESS_FIXED_NOW_ISO env value or a fixed constant
    - git_user_email_at_install_sha256: set to None
    - source: set to a placeholder string (path is build-environment-specific)
    - trust_origin: set to "dev_unsigned" (real fixture has "signed_tag" from git tag;
      tests upgrade with HARNESS_ALLOW_UNSIGNED_DEV=1 which blocks signed_tag→dev_unsigned
      downgrade, so we normalize to dev_unsigned to allow test upgrades)
    - release_tag / release_commit: set to None (fixture-specific, not relevant for test upgrades)
    - installed_files_chain_hash: recomputed after normalization (trust fields change it)
    """
    manifest_path = target_dir / ".harness" / "installed-manifest.json"
    if not manifest_path.exists():
        return
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  WARNING: cannot normalize install state: {exc}", file=sys.stderr, flush=True)
        return

    fixed_now = os.environ.get("HARNESS_FIXED_NOW_ISO", "2026-05-21T00:00:00Z")
    data["git_user_email_at_install_sha256"] = None
    data["source"] = "__fixture__"
    # Always dev_unsigned: no trust ceremony in this internal tool.
    data["trust_origin"] = "dev_unsigned"
    data["release_tag"] = None
    data["release_commit"] = None
    # Normalize installed_at for all file entries
    if isinstance(data.get("files"), dict):
        for file_info in data["files"].values():
            if isinstance(file_info, dict) and "installed_at" in file_info:
                file_info["installed_at"] = fixed_now
    # Recompute chain hash after trust fields changed (chain covers trust_origin,
    # release_tag, release_commit — see compute_manifest_hash_chain in manifest_reconciler.py).
    data["installed_files_chain_hash"] = _recompute_chain_hash(data)
    manifest_path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_v094_init(harness_py: Path, target_dir: Path) -> None:
    """Run v0.9.4 harness.py init --target <target> --adapters none.

    Raises FixtureBuildError on non-zero exit code (Hawk M-7).
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    fixed_now = env.get("HARNESS_FIXED_NOW_ISO", "2026-05-21T00:00:00Z")
    env["HARNESS_FIXED_NOW_ISO"] = fixed_now
    result = subprocess.run(
        [sys.executable, str(harness_py), "init", "--target", str(target_dir), "--adapters", "none"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    print(result.stdout[-2000:] if result.stdout else "", flush=True)
    if result.returncode != 0:
        raise FixtureBuildError(
            f"harness init exited {result.returncode};\n"
            f"stdout: {result.stdout[-500:]}\n"
            f"stderr: {result.stderr[-500:]}"
        )


def _build_all_once(worktree_path: Path, harness_py: Path, output_dir: Path) -> tuple[str, str]:
    """Run the full fixture build once, normalizing and producing tarballs.

    Returns (clean_digest, workaround_digest).
    """
    clean_target = output_dir / "_build_clean"
    workaround_target = output_dir / "_build_workaround"

    if clean_target.exists():
        shutil.rmtree(clean_target)
    if workaround_target.exists():
        shutil.rmtree(workaround_target)

    # 1. Run init
    run_v094_init(harness_py, clean_target)

    # 2. Normalize install state for determinism
    _normalize_v094_install_state(clean_target)

    # 3. Build clean tarball
    clean_tarball = output_dir / "v094-clean.tar.gz"
    clean_digest = build_deterministic_tarball(clean_target, clean_tarball)

    # 4. Build workaround variant
    shutil.copytree(clean_target, workaround_target)
    workaround_lib_dst = workaround_target / "scripts" / "lib"
    workaround_lib_dst.mkdir(parents=True, exist_ok=True)
    v094_lib_src = worktree_path / "scripts" / "lib"
    copied = 0
    for mod_name in MISSING_LIB_MODULES:
        src = v094_lib_src / mod_name
        dst = workaround_lib_dst / mod_name
        if src.exists():
            shutil.copy2(src, dst)
            copied += 1
        else:
            print(f"  WARNING: missing source module {src}", file=sys.stderr, flush=True)
    print(f"  Copied {copied}/{len(MISSING_LIB_MODULES)} missing lib modules", flush=True)

    # 5. Build workaround tarball
    workaround_tarball = output_dir / "v094-with-workaround.tar.gz"
    workaround_digest = build_deterministic_tarball(workaround_target, workaround_tarball)

    # Cleanup temp build dirs
    for tmp in (clean_target, workaround_target):
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)

    return clean_digest, workaround_digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo_root() / "tests" / "fixtures",
        help="Directory to write tarballs and .sha256 files (default: tests/fixtures)",
    )
    parser.add_argument("--keep-worktrees", action="store_true", help="Skip cleanup of scratch worktrees (debug)")
    parser.add_argument("--skip-determinism-check", action="store_true", help="Skip the double-build determinism check")
    args = parser.parse_args()

    output_dir: Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    worktree_path = Path(tempfile.gettempdir()) / "v094-worktree"

    try:
        # 1. Check out v0.9.4 source.
        print("\n=== Step 1: git worktree add v0.9.4 ===", flush=True)
        setup_worktree("v0.9.4", worktree_path)
        harness_py = worktree_path / "scripts" / "harness.py"

        # 2. First build pass.
        print("\n=== Step 2: first build pass ===", flush=True)
        build1_dir = output_dir / "_pass1"
        build1_dir.mkdir(exist_ok=True)
        clean_digest1, workaround_digest1 = _build_all_once(worktree_path, harness_py, build1_dir)
        print(f"  clean sha256: {clean_digest1}", flush=True)
        print(f"  workaround sha256: {workaround_digest1}", flush=True)

        # 3. Determinism self-check: build a second time.
        if not args.skip_determinism_check:
            print("\n=== Step 3: determinism self-check (second build pass) ===", flush=True)
            build2_dir = output_dir / "_pass2"
            build2_dir.mkdir(exist_ok=True)
            clean_digest2, workaround_digest2 = _build_all_once(worktree_path, harness_py, build2_dir)
            if clean_digest1 != clean_digest2 or workaround_digest1 != workaround_digest2:
                raise FixtureBuildError(
                    f"Determinism check FAILED:\n"
                    f"  clean:       {clean_digest1} vs {clean_digest2}\n"
                    f"  workaround:  {workaround_digest1} vs {workaround_digest2}"
                )
            print("  Determinism check PASSED", flush=True)
            # Cleanup second pass
            shutil.rmtree(build2_dir, ignore_errors=True)

        # 4. Copy final tarballs to output_dir and write .sha256 files.
        for fname, digest in [
            ("v094-clean.tar.gz", clean_digest1),
            ("v094-with-workaround.tar.gz", workaround_digest1),
        ]:
            src_tarball = build1_dir / fname
            dst_tarball = output_dir / fname
            if src_tarball != dst_tarball:
                shutil.copy2(src_tarball, dst_tarball)
            (output_dir / f"{fname}.sha256").write_text(
                f"{digest}  {fname}\n", encoding="utf-8"
            )
            print(f"  wrote {fname} ({dst_tarball.stat().st_size:,} bytes, sha256={digest[:16]}...)", flush=True)

        shutil.rmtree(build1_dir, ignore_errors=True)
        print("\n=== Done ===", flush=True)

    finally:
        if not args.keep_worktrees:
            print("\n=== Cleanup ===", flush=True)
            teardown_worktree(worktree_path)


if __name__ == "__main__":
    main()
