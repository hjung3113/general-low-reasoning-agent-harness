#!/usr/bin/env python3
"""Run the release install/check smoke matrix for the harness source tree."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path


CASES = [
    ("core", ["--adapters", "none"]),
    ("opencode", ["--adapters", "opencode"]),
    ("roo", ["--adapters", "roo"]),
    ("both", ["--adapters", "both"]),
    ("python-analysis", ["--adapters", "opencode", "--packs", "workflow-core,tech-python,workflow-data-analysis"]),
    (
        "dotnet-etl",
        [
            "--adapters",
            "both",
            "--profiles",
            "generic,dotnet-etl-mssql",
            "--packs",
            "workflow-core,tech-csharp,tech-mssql,workflow-etl,workflow-db-context",
        ],
    ),
    (
        "web",
        ["--packs", "workflow-core,tech-react,tech-typescript,tech-tailwind,workflow-web-development"],
    ),
    (
        "workflow-quality",
        [
            "--packs",
            "workflow-core,workflow-tdd,workflow-debugging,workflow-code-review,workflow-skill-authoring,workflow-security-review",
        ],
    ),
    (
        "all-packs",
        [
            "--adapters",
            "both",
            "--profiles",
            "generic,dotnet-etl-mssql",
            "--packs",
            ",".join(
                [
                    "workflow-core",
                    "tech-python",
                    "tech-react",
                    "tech-typescript",
                    "tech-tailwind",
                    "tech-csharp",
                    "tech-mssql",
                    "tech-postgresql",
                    "workflow-data-analysis",
                    "workflow-data-processing",
                    "workflow-etl",
                    "workflow-db-context",
                    "workflow-web-development",
                    "workflow-tdd",
                    "workflow-debugging",
                    "workflow-code-review",
                    "workflow-skill-authoring",
                    "workflow-security-review",
                ]
            ),
        ],
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-temp", action="store_true", help="Keep the temporary matrix directory.")
    parser.add_argument("--release", action="store_true", help="Require exact clean release tag before running the smoke matrix.")
    parser.add_argument("--expected-version", default=None, help="Expected vMAJOR.MINOR.PATCH release tag for --release.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    command_env = os.environ.copy()
    version_args: list[str] = []
    if args.release:
        command_env.pop("HARNESS_VERSION", None)
        if not args.expected_version:
            raise SystemExit("--release requires --expected-version vMAJOR.MINOR.PATCH")
        version_args = ["--version", args.expected_version]
    if args.keep_temp:
        matrix_root = Path(tempfile.mkdtemp(prefix="harness-release-smoke."))
    else:
        matrix_root = Path(tempfile.mkdtemp(prefix="harness-release-smoke."))
    try:
        if args.release:
            command = [sys.executable, "scripts/harness.py", "release-check"]
            if args.expected_version:
                command.extend(["--expected-version", args.expected_version])
            command.append("--require-origin-main")
            run(command, cwd=root, env=command_env)
        for name, options in CASES:
            target = matrix_root / name
            run([sys.executable, "scripts/harness.py", *version_args, "init", "--target", str(target), *options], cwd=root, env=command_env)
            run([sys.executable, "scripts/harness.py", *version_args, "check", "--target", str(target)], cwd=root, env=command_env)
            run([sys.executable, "scripts/harness.py", "check"], cwd=target, env=command_env)
            run([sys.executable, "scripts/test_harness.py"], cwd=target, env=command_env)
            print(f"PASS {name} {target}")
        print(f"TMP {matrix_root}")
    finally:
        if not args.keep_temp:
            shutil.rmtree(matrix_root)
    return 0


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
