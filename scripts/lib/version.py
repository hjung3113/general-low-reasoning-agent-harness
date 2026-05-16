"""Version, release-tag, and git-provenance helpers for the harness source tree."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


README_RELEASE_VERSION = re.compile(r"\bv\d+\.\d+\.\d+\b")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def upgrade_source_root(default_root: Path, target: Path) -> Path:
    import harness as _harness
    default_root = default_root.resolve()
    target = target.resolve()
    if default_root != target:
        return default_root

    installed = _harness.read_install_state(target)
    source = installed.get("source")
    if not isinstance(source, str) or not source:
        return default_root

    candidate = Path(source).expanduser().resolve()
    if candidate == default_root:
        return default_root
    if not (candidate / _harness.MANIFEST_PATH).exists():
        return default_root
    return candidate


def normalize_release_version(value: str) -> str:
    match = re.fullmatch(r"v?(\d+\.\d+\.\d+)", value.strip())
    if not match:
        raise ValueError("Release version must use vMAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH.")
    return match.group(1)


def git_output(root: Path, command: list[str]) -> str:
    return subprocess.check_output(command, cwd=root, text=True, stderr=subprocess.DEVNULL).strip()


def is_git_worktree_dirty(root: Path) -> bool:
    import harness as _harness
    try:
        return bool(_harness.git_output(root, ["git", "status", "--porcelain"]))
    except (subprocess.CalledProcessError, FileNotFoundError):
        return True


def exact_release_tag_version(root: Path) -> str | None:
    import harness as _harness
    try:
        tag = _harness.git_output(root, ["git", "describe", "--tags", "--exact-match"])
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        return None
    return tag[1:]


def development_version(root: Path) -> str:
    import harness as _harness
    try:
        sha = _harness.git_output(root, ["git", "rev-parse", "--short=12", "HEAD"])
    except (subprocess.CalledProcessError, FileNotFoundError):
        sha = "unknown"
    suffix = ".dirty" if _harness.is_git_worktree_dirty(root) else ""
    return f"0.0.0-dev+{sha}{suffix}"


def git_source_provenance(root: Path) -> dict[str, str] | None:
    import harness as _harness
    try:
        repo = _harness.git_output(root, ["git", "config", "--get", "remote.origin.url"])
        commit = _harness.git_output(root, ["git", "rev-parse", "HEAD"])
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if not repo:
        return None
    tag = _harness.exact_release_tag_version(root)
    if tag:
        ref = f"v{tag}"
    else:
        try:
            ref = _harness.git_output(root, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
        except (subprocess.CalledProcessError, FileNotFoundError):
            ref = "HEAD"
        if ref == "HEAD":
            ref = commit
    return {"kind": "git", "repo": repo, "ref": ref, "commit": commit}


def source_provenance(root: Path) -> dict[str, str] | None:
    import harness as _harness
    provenance = _harness.delegated_source_provenance()
    if provenance is None:
        provenance = _harness.git_source_provenance(root)
    if provenance is None:
        return None
    if "version" not in provenance:
        provenance = dict(provenance)
        provenance["version"] = _harness.HARNESS_VERSION
    return provenance


def resolve_harness_version(
    root: Path,
    *,
    explicit: str | None = None,
    env: dict[str, str] | None = None,
) -> str:
    import harness as _harness
    env = os.environ if env is None else env
    if explicit:
        return _harness.normalize_release_version(explicit)
    env_version = env.get("HARNESS_VERSION")
    if env_version:
        return _harness.normalize_release_version(env_version)
    tag_version = _harness.exact_release_tag_version(root)
    if tag_version and not _harness.is_git_worktree_dirty(root):
        return tag_version
    return _harness.development_version(root)


def release_check(*, root: Path, expected_version: str | None = None, require_origin_main: bool = False) -> str:
    import harness as _harness
    tag_version = _harness.exact_release_tag_version(root)
    if tag_version is None:
        raise SystemExit("Release check requires HEAD to be on an exact vMAJOR.MINOR.PATCH tag.")
    if expected_version is not None and _harness.normalize_release_version(expected_version) != tag_version:
        raise SystemExit(f"Release version mismatch: expected {_harness.normalize_release_version(expected_version)}, tag is {tag_version}.")
    if _harness.is_git_worktree_dirty(root):
        raise SystemExit("Release check requires a clean worktree; dirty worktree detected.")
    if require_origin_main:
        try:
            head = _harness.git_output(root, ["git", "rev-parse", "HEAD"])
            origin_main = _harness.git_output(root, ["git", "rev-parse", "origin/main"])
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise SystemExit("Release check requires origin/main to verify release provenance.") from None
        if head != origin_main:
            raise SystemExit("Release check requires the release tag commit to equal origin/main.")
    manifest = _harness.load_manifest_data(root, version=tag_version)
    if manifest.get("version") != tag_version:
        raise SystemExit(f"Manifest version mismatch: expected {tag_version}.")
    _harness.check_readme_release_versions(root=root, expected_version=f"v{tag_version}")
    return tag_version


def readme_release_versions(root: Path) -> set[str]:
    readme = root / "README.md"
    if not readme.exists():
        return set()
    return set(README_RELEASE_VERSION.findall(readme.read_text(encoding="utf-8")))


def check_readme_release_versions(*, root: Path, expected_version: str) -> None:
    import harness as _harness
    expected = f"v{_harness.normalize_release_version(expected_version)}"
    mismatched = sorted(version for version in _harness.readme_release_versions(root) if version != expected)
    if mismatched:
        raise SystemExit(
            "README release version mismatch: "
            f"expected only {expected}, found {', '.join(mismatched)}. "
            "Update README release/install examples before releasing."
        )
