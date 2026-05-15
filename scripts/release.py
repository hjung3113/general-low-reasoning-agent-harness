#!/usr/bin/env python3
"""Create a harness release from develop through main and a version tag."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


VERSION_PATTERN = re.compile(r"^v(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def validate_release_version(value: str) -> str:
    if not VERSION_PATTERN.fullmatch(value):
        raise ValueError("Release version must use vMAJOR.MINOR.PATCH.")
    return value


def parse_version(value: str) -> tuple[int, int, int] | None:
    match = VERSION_PATTERN.fullmatch(value)
    if not match:
        return None
    return (int(match.group("major")), int(match.group("minor")), int(match.group("patch")))


def next_release_version(tags: list[str], *, bump: str) -> str:
    versions = [parsed for tag in tags if (parsed := parse_version(tag)) is not None]
    if not versions:
        return "v0.1.0"
    major, minor, patch = max(versions)
    if bump == "major":
        return f"v{major + 1}.0.0"
    if bump == "minor":
        return f"v{major}.{minor + 1}.0"
    if bump == "patch":
        return f"v{major}.{minor}.{patch + 1}"
    raise ValueError(f"Unknown bump type: {bump}")


def read_existing_tags(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "tag", "--list", "v*"],
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


@dataclass
class CommandRunner:
    root: Path
    dry_run: bool = False
    commands: list[list[str]] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=lambda: {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})

    def run(self, command: list[str], *, capture: bool = False) -> str:
        self.commands.append(command)
        print("+ " + " ".join(command))
        if self.dry_run:
            return ""
        completed = subprocess.run(
            command,
            cwd=self.root,
            env=self.env,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
        )
        return completed.stdout.strip() if capture and completed.stdout is not None else ""


def tag_exists(version: str, *, root: Path) -> bool:
    completed = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{version}"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def confirm_release(version: str, *, assume_yes: bool) -> None:
    if assume_yes:
        return
    answer = input(f"Create release {version}? Type {version} to continue: ").strip()
    if answer != version:
        raise SystemExit("Release aborted.")


def wait_for_release_workflow(runner: CommandRunner, version: str) -> None:
    run_id = ""
    for _ in range(12):
        run_id = runner.run(
            [
                "gh",
                "run",
                "list",
                "--workflow",
                "Release",
                "--branch",
                version,
                "--limit",
                "1",
                "--json",
                "databaseId",
                "--jq",
                ".[0].databaseId",
            ],
            capture=True,
        )
        if run_id:
            break
        if runner.dry_run:
            break
        time.sleep(5)
    if not run_id and not runner.dry_run:
        raise SystemExit(f"Release workflow run for {version} was not found.")
    runner.run(["gh", "run", "watch", run_id or "<run-id>", "--exit-status"])


def run_release(
    *,
    version: str | None,
    bump: str,
    runner: CommandRunner,
    assume_yes: bool,
) -> str:
    runner.run(["git", "fetch", "--tags", "origin"])
    selected_version = validate_release_version(version) if version else next_release_version(read_existing_tags(runner.root), bump=bump)
    if tag_exists(selected_version, root=runner.root):
        raise SystemExit(f"Tag already exists: {selected_version}")
    confirm_release(selected_version, assume_yes=assume_yes or runner.dry_run)

    runner.run(["git", "switch", "develop"])
    runner.run(["git", "pull", "--ff-only", "origin", "develop"])
    runner.run(["git", "switch", "main"])
    runner.run(["git", "pull", "--ff-only", "origin", "main"])
    runner.run(["git", "merge", "--no-ff", "develop", "-m", f"merge: release {selected_version}"])
    runner.run(["python3", "-m", "unittest", "scripts/test_harness.py", "scripts/test_release.py"])
    runner.run(["python3", "scripts/harness.py", "check"])
    runner.run(["python3", "scripts/release_smoke_test.py"])
    runner.run(["git", "push", "origin", "main"])
    runner.run(["git", "tag", "-a", selected_version, "-m", selected_version])
    runner.run(["python3", "scripts/release_smoke_test.py", "--release", "--expected-version", selected_version])
    runner.run(["git", "push", "origin", selected_version])
    wait_for_release_workflow(runner, selected_version)
    runner.run(["gh", "release", "create", selected_version, "--verify-tag", "--title", selected_version, "--notes", selected_version])
    runner.run(["gh", "release", "view", selected_version])
    return selected_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?", help="Release version. Defaults to next patch tag, for example v0.4.3.")
    parser.add_argument("--bump", choices=("patch", "minor", "major"), default="patch", help="Auto-bump type when version is omitted.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    parser.add_argument("--yes", action="store_true", help="Skip interactive version confirmation.")
    args = parser.parse_args(argv)

    runner = CommandRunner(root=repo_root(), dry_run=args.dry_run)
    version = run_release(version=args.version, bump=args.bump, runner=runner, assume_yes=args.yes)
    print(f"Release complete: {version}" if not args.dry_run else f"Release dry run complete: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
