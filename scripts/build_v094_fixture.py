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

CI always rebuilds; tarballs are gitignored; only .sha256 files are checked-in.

Usage:
    python3 scripts/build_v094_fixture.py [--output-dir tests/fixtures]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
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
EXCLUDE_NAMES = {"__pycache__", ".git", ".pytest_cache", ".DS_Store", ".harness"}

# The 35 lib/*.py modules missing from v0.9.4 manifest.json (BUG-1).
MISSING_LIB_MODULES: list[str] = [
    "approval_nonce.py",
    "approve_nonce_cli.py",
    "audit.py",
    "audit_chain.py",
    "audit_rotation.py",
    "audit_verify_cli.py",
    "autopilot_guard.py",
    "ci_provenance.py",
    "cli_budgets.py",
    "cli_deprecated.py",
    "durable_fs.py",
    "fs_fence.py",
    "fsd_wrappers.py",
    "halt_diary.py",
    "halt_diary_cli.py",
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
    "secret_key.py",
    "session.py",
    "smoke_lifecycle.py",
    "state_migrate.py",
    "state_migrate_t04.py",
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


def run_v094_init(harness_py: Path, target_dir: Path) -> None:
    """Run v0.9.4 harness.py init --target <target> --adapters none."""
    target_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(harness_py), "init", "--target", str(target_dir), "--adapters", "none"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(result.stdout[-2000:] if result.stdout else "", flush=True)
    if result.returncode != 0:
        # Init exits non-zero on some environments (missing git config etc) but may still
        # have installed the files we need. Warn but continue.
        print(
            f"  WARNING: harness init exited {result.returncode}; stderr:\n{result.stderr[-1000:]}",
            file=sys.stderr,
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo_root() / "tests" / "fixtures",
        help="Directory to write tarballs and .sha256 files (default: tests/fixtures)",
    )
    parser.add_argument("--keep-worktrees", action="store_true", help="Skip cleanup of scratch worktrees (debug)")
    args = parser.parse_args()

    output_dir: Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    worktree_path = Path(tempfile.gettempdir()) / "v094-worktree"
    clean_target = Path(tempfile.gettempdir()) / "v094-clean"
    workaround_target = Path(tempfile.gettempdir()) / "v094-workaround"

    try:
        # 1. Check out v0.9.4 source.
        print("\n=== Step 1: git worktree add v0.9.4 ===", flush=True)
        setup_worktree("v0.9.4", worktree_path)
        harness_py = worktree_path / "scripts" / "harness.py"

        # 2. Run init to produce a clean v0.9.4 install.
        print("\n=== Step 2: harness init (clean) ===", flush=True)
        if clean_target.exists():
            shutil.rmtree(clean_target)
        run_v094_init(harness_py, clean_target)

        # 3. Build v094-clean tarball.
        print("\n=== Step 3: build v094-clean.tar.gz ===", flush=True)
        clean_tarball = output_dir / "v094-clean.tar.gz"
        clean_digest = build_deterministic_tarball(clean_target, clean_tarball)
        print(f"  sha256: {clean_digest}", flush=True)
        (output_dir / "v094-clean.tar.gz.sha256").write_text(f"{clean_digest}  v094-clean.tar.gz\n", encoding="utf-8")

        # 4. Build workaround variant: copy the 35 missing lib modules into the target.
        print("\n=== Step 4: build v094-with-workaround target ===", flush=True)
        if workaround_target.exists():
            shutil.rmtree(workaround_target)
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

        # 5. Build v094-with-workaround tarball.
        print("\n=== Step 5: build v094-with-workaround.tar.gz ===", flush=True)
        workaround_tarball = output_dir / "v094-with-workaround.tar.gz"
        workaround_digest = build_deterministic_tarball(workaround_target, workaround_tarball)
        print(f"  sha256: {workaround_digest}", flush=True)
        (output_dir / "v094-with-workaround.tar.gz.sha256").write_text(
            f"{workaround_digest}  v094-with-workaround.tar.gz\n", encoding="utf-8"
        )

        # 6. Print summary.
        clean_size = clean_tarball.stat().st_size
        workaround_size = workaround_tarball.stat().st_size
        print(
            f"\n=== Done ===\n"
            f"  v094-clean.tar.gz          {clean_size:>10,} bytes  sha256={clean_digest[:16]}...\n"
            f"  v094-with-workaround.tar.gz {workaround_size:>10,} bytes  sha256={workaround_digest[:16]}...",
            flush=True,
        )

    finally:
        if not args.keep_worktrees:
            print("\n=== Cleanup ===", flush=True)
            teardown_worktree(worktree_path)
            for tmp in (clean_target, workaround_target):
                if tmp.exists():
                    shutil.rmtree(tmp, ignore_errors=True)
                    print(f"  Removed {tmp}", flush=True)


if __name__ == "__main__":
    main()
