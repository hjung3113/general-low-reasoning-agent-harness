#!/usr/bin/env python3
"""Target-local harness upgrade bootstrapper."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_HARNESS_REPO = "https://github.com/hjung3113/general-low-reasoning-agent-harness.git"
INSTALL_STATE = Path(".harness/installed-manifest.json")
MANIFEST_PATH = Path("harness/manifest.json")


def normalize_version(value: str) -> str:
    match = re.fullmatch(r"v?(\d+\.\d+\.\d+)", value.strip())
    if not match:
        raise SystemExit("Release version must use vMAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH.")
    return match.group(1)


def safe_ref_name(ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", ref).strip("-") or "source"


def repo_cache_key(repo: str, ref: str) -> str:
    digest = hashlib.sha256(f"{repo}\n{ref}".encode("utf-8")).hexdigest()[:12]
    return f"{safe_ref_name(ref)}-{digest}"


def cache_metadata_path(cache: Path) -> Path:
    return cache / ".harness-source.json"


def write_cache_metadata(cache: Path, *, repo: str, ref: str) -> None:
    cache_metadata_path(cache).write_text(
        json.dumps({"repo": repo, "ref": ref}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def cache_matches(cache: Path, *, repo: str, ref: str) -> bool:
    path = cache_metadata_path(cache)
    if not path.exists():
        return False
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return metadata.get("repo") == repo and metadata.get("ref") == ref


def read_installed_source(target: Path) -> Path | None:
    path = target / INSTALL_STATE
    if not path.exists():
        return None
    try:
        installed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    source = installed.get("source")
    if not isinstance(source, str) or not source:
        return None
    candidate = Path(source).expanduser().resolve()
    if (candidate / MANIFEST_PATH).exists():
        return candidate
    return None


def read_installed_source_repo(target: Path) -> str | None:
    path = target / INSTALL_STATE
    if not path.exists():
        return None
    try:
        installed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    provenance = installed.get("source_provenance")
    if not isinstance(provenance, dict):
        return None
    repo = provenance.get("repo")
    if not isinstance(repo, str) or not repo:
        return None
    return repo


def ensure_git_source(target: Path, repo: str, ref: str, *, dry_run: bool) -> Path | None:
    cache = target / ".harness/sources" / repo_cache_key(repo, ref)
    if (cache / MANIFEST_PATH).exists():
        if not cache_matches(cache, repo=repo, ref=ref):
            raise SystemExit(f"Cached source metadata does not match requested repo/ref: {cache}")
        return cache.resolve()
    if dry_run:
        return None
    if cache.exists():
        raise SystemExit(f"Cached source is invalid; remove it and retry: {cache}")
    cache.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "clone", "--depth", "1", "--branch", ref, repo, str(cache)], cwd=target)
    if not (cache / MANIFEST_PATH).exists():
        raise SystemExit(f"Downloaded source is missing {MANIFEST_PATH}: {cache}")
    write_cache_metadata(cache, repo=repo, ref=ref)
    return cache.resolve()


def resolve_source(args: argparse.Namespace, target: Path) -> tuple[Path | None, str, str, str | None]:
    if args.source:
        source = args.source.expanduser().resolve()
        if not (source / MANIFEST_PATH).exists():
            raise SystemExit(f"--source is missing {MANIFEST_PATH}: {source}")
        version = normalize_version(args.release_version) if args.release_version else None
        return source, "path", str(source), version
    if args.release_version:
        version = normalize_version(args.release_version)
        ref = f"v{version}"
        return ensure_git_source(target, args.repo, ref, dry_run=args.dry_run), "release", ref, version
    if args.ref:
        return ensure_git_source(target, args.repo, args.ref, dry_run=args.dry_run), "ref", args.ref, None
    recorded = read_installed_source(target)
    if recorded:
        return recorded, "recorded-source", str(recorded), None
    raise SystemExit("Cannot resolve upgrade source. Use --source PATH, --version vX.Y.Z, or --repo URL --ref REF.")


def build_delegate(args: argparse.Namespace, source: Path, target: Path, version: str | None) -> list[str]:
    command = [sys.executable, str(source / "scripts/harness.py")]
    if version:
        command.extend(["--version", version])
    command.extend(["upgrade", "--target", str(target)])
    for flag in ("dry_run", "force", "adopt_existing"):
        if getattr(args, flag):
            command.append("--" + flag.replace("_", "-"))
    for option in ("adapters", "profiles", "packs"):
        value = getattr(args, option)
        if value is not None:
            command.extend(["--" + option, value])
    return command


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=None)
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--version", dest="release_version", default=None)
    parser.add_argument("--repo", default=None)
    parser.add_argument("--ref", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--adopt-existing", action="store_true")
    parser.add_argument("--adapters", default=None)
    parser.add_argument("--profiles", default=None)
    parser.add_argument("--packs", default=None)
    args = parser.parse_args(argv)

    target = (args.target.expanduser() if args.target else Path(__file__).resolve().parents[1]).resolve()
    selected_repo = args.repo or read_installed_source_repo(target) or DEFAULT_HARNESS_REPO
    args.repo = selected_repo
    source, kind, ref, version = resolve_source(args, target)
    print(f"selected source={source}")
    print(f"selected source_kind={kind}")
    print(f"selected ref={ref}")
    if args.release_version:
        print(f"selected version=v{normalize_version(args.release_version)}")
    if source is None:
        print(f"would download source={args.repo}@{ref}")
        print("no mutation performed")
        return 0
    command = build_delegate(args, source, target, version)
    print("delegating: " + " ".join(command))
    env = os.environ.copy()
    env["HARNESS_DELEGATED_SOURCE_KIND"] = kind
    if kind == "path" and "HARNESS_ALLOW_UNSIGNED_DEV" not in env:
        env["HARNESS_ALLOW_UNSIGNED_DEV"] = "1"
        env["HARNESS_ALLOW_UNSIGNED_DEV_SOURCE"] = "path_source"
        env["HARNESS_BYPASS_TTY_CONFIRM"] = "1"
    if kind in {"release", "ref"}:
        env["HARNESS_DELEGATED_SOURCE_REPO"] = args.repo
    env["HARNESS_DELEGATED_SOURCE_REF"] = ref
    if version:
        env["HARNESS_DELEGATED_SOURCE_VERSION"] = version
    result = subprocess.run(command, cwd=source, env=env)
    if args.dry_run:
        print("no mutation performed")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
