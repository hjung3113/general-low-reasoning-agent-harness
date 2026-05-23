#!/usr/bin/env python3
"""Skill-pack audit gate — Milestone 7.

Reads harness/manifest.json, scripts/lib/profiles.py constants, and
harness/skill-packs/ to produce a Markdown evidence report.

Exit codes:
  0  all checks pass
  1  one or more gate failures (see FAIL lines in output)

Usage:
  python3 scripts/audit_skill_packs.py [--root <repo-root>]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Profile / DB selection constants (mirrors scripts/lib/profiles.py)
# ---------------------------------------------------------------------------
_PROFILE_DEFAULT_PACKS: dict[str, tuple[str, ...]] = {
    "generic": ("workflow-core",),
    "dotnet-etl": ("workflow-core", "workflow-etl", "tech-csharp"),
    "python-etl": ("workflow-core", "workflow-etl", "tech-python"),
    "react-web": (
        "workflow-core",
        "workflow-web-development",
        "tech-react",
        "tech-typescript",
        "tech-tailwind",
    ),
}

_DB_PACKS: dict[str, tuple[str, ...]] = {
    "mssql": ("tech-mssql", "workflow-db-context"),
    "postgresql": ("tech-postgresql", "workflow-db-context"),
}

# Flatten to sets for quick membership test
_ALL_PROFILE_SELECTED: set[str] = {
    p for packs in _PROFILE_DEFAULT_PACKS.values() for p in packs
}
_ALL_DB_SELECTED: set[str] = {
    p for packs in _DB_PACKS.values() for p in packs
}


def _profile_selection_detail(pack: str) -> str:
    """Return which profiles select this pack, or empty string."""
    profiles = [
        name for name, packs in _PROFILE_DEFAULT_PACKS.items() if pack in packs
    ]
    if profiles:
        return ", ".join(sorted(profiles))
    return ""


def _db_selection_detail(pack: str) -> str:
    """Return which DB configs select this pack, or empty string."""
    dbs = [name for name, packs in _DB_PACKS.items() if pack in packs]
    if dbs:
        return ", ".join(sorted(dbs))
    return ""


# ---------------------------------------------------------------------------
# Manifest inspection helpers
# ---------------------------------------------------------------------------

def _load_manifest_raw(root: Path) -> dict:
    manifest_path = root / "harness" / "manifest.json"
    if not manifest_path.exists():
        print(f"FAIL: manifest not found at {manifest_path}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Accept any version string for the audit (no version-lock enforcement)
    return data


def _manifest_file_count(files: list[dict], pack_name: str) -> int:
    """Count manifest files[] entries whose pack field equals pack_name."""
    return sum(
        1
        for f in files
        if f.get("pack") == pack_name or f.get("owner") == f"pack:{pack_name}"
    )


# ---------------------------------------------------------------------------
# Test reference counting
# ---------------------------------------------------------------------------

def _test_reference_count(root: Path, pack_name: str) -> int:
    """Count occurrences of pack_name string in test files."""
    test_dir = root / "scripts" / "tests"
    if not test_dir.exists():
        test_dir = root / "tests"
    count = 0
    for test_file in test_dir.rglob("*.py"):
        try:
            text = test_file.read_text(encoding="utf-8")
            count += text.count(pack_name)
        except OSError:
            pass
    return count


# ---------------------------------------------------------------------------
# Skill-pack dir inspection
# ---------------------------------------------------------------------------

def _pack_dir_exists(root: Path, pack_name: str) -> bool:
    return (root / "harness" / "skill-packs" / pack_name).is_dir()


def _pack_has_skill_md(root: Path, pack_name: str) -> bool:
    pack_dir = root / "harness" / "skill-packs" / pack_name
    return bool(list(pack_dir.rglob("SKILL.md")))


def _pack_skill_md_count(root: Path, pack_name: str) -> int:
    pack_dir = root / "harness" / "skill-packs" / pack_name
    return len(list(pack_dir.rglob("SKILL.md")))


# ---------------------------------------------------------------------------
# Pack metadata inspection
# ---------------------------------------------------------------------------

def _has_usage_status(meta: dict) -> bool:
    return "usage_status" in meta


def _has_target_story(meta: dict) -> bool:
    return "target_story" in meta


def _has_activation_evidence(meta: dict) -> bool:
    return "activation_evidence" in meta


# ---------------------------------------------------------------------------
# Main audit logic
# ---------------------------------------------------------------------------

def audit(root: Path) -> int:
    """Run the audit and print a Markdown report. Returns exit code."""
    data = _load_manifest_raw(root)
    manifest_packs: dict = data.get("packs", {})
    manifest_files: list[dict] = data.get("files", [])

    # Collect all pack names from both manifest packs and skill-packs dirs
    sp_dir = root / "harness" / "skill-packs"
    dir_packs: set[str] = {d.name for d in sp_dir.iterdir() if d.is_dir()} if sp_dir.is_dir() else set()

    all_pack_names: set[str] = set(manifest_packs.keys()) | dir_packs

    failures: list[str] = []

    # Gate: 18 packs expected (M7 baseline)
    expected_count = 18
    if len(all_pack_names) != expected_count:
        failures.append(
            f"Pack count mismatch: expected {expected_count}, found {len(all_pack_names)} ({sorted(all_pack_names)})"
        )

    # Gate: every manifest pack has a skill-packs dir
    for pack in sorted(manifest_packs):
        if pack not in dir_packs:
            failures.append(f"Pack '{pack}' in manifest but has no skill-packs dir")

    # Gate: every skill-packs dir is in manifest
    for pack in sorted(dir_packs):
        if pack not in manifest_packs:
            failures.append(f"Pack dir '{pack}' exists but is absent from manifest packs section")

    # Gate: every manifest pack has at least one manifest file entry
    for pack in sorted(manifest_packs):
        if _manifest_file_count(manifest_files, pack) == 0:
            failures.append(f"Pack '{pack}' has no manifest files[] entries")

    # Gate: default-selected packs are present
    for pack in sorted(_ALL_PROFILE_SELECTED | _ALL_DB_SELECTED):
        if pack not in manifest_packs:
            failures.append(f"Default/DB pack '{pack}' is missing from manifest")

    # Gate: manual-only packs should have usage_status or target_story metadata
    # (warn, not hard-fail, since this is what M7 is building toward)
    manual_only_without_metadata: list[str] = []
    for pack in sorted(manifest_packs):
        meta = manifest_packs[pack]
        if not isinstance(meta, dict):
            continue
        is_default = pack in _ALL_PROFILE_SELECTED
        is_db = pack in _ALL_DB_SELECTED
        has_explicit_meta = (
            _has_usage_status(meta)
            or _has_target_story(meta)
            or _has_activation_evidence(meta)
        )
        if not is_default and not is_db and not has_explicit_meta:
            manual_only_without_metadata.append(pack)

    # ---------------------------------------------------------------------------
    # Build the Markdown report
    # ---------------------------------------------------------------------------
    lines: list[str] = []

    lines.append("# Skill-Pack Audit Report — Milestone 7")
    lines.append("")
    lines.append(f"Generated from: `harness/manifest.json`  ")
    lines.append(f"Total packs found: **{len(all_pack_names)}** (manifest) / **{len(dir_packs)}** (dirs)")
    lines.append(f"Total manifest files: **{len(manifest_files)}**")
    lines.append("")

    # ---------------------------------------------------------------------------
    # Evidence table
    # ---------------------------------------------------------------------------
    lines.append("## Per-Pack Evidence Table")
    lines.append("")
    lines.append("| Pack | Profile-selected | DB-selected | Manifest files | Test refs | Dir? | SKILL.md count | usage_status | target_story |")
    lines.append("|------|-----------------|-------------|---------------|-----------|------|----------------|--------------|--------------|")

    for pack in sorted(all_pack_names):
        profile_sel = _profile_selection_detail(pack)
        db_sel = _db_selection_detail(pack)
        file_count = _manifest_file_count(manifest_files, pack)
        test_refs = _test_reference_count(root, pack)
        dir_exists = "yes" if _pack_dir_exists(root, pack) else "NO"
        skill_md_count = _pack_skill_md_count(root, pack) if _pack_dir_exists(root, pack) else 0
        meta = manifest_packs.get(pack, {})
        has_us = "yes" if isinstance(meta, dict) and _has_usage_status(meta) else "-"
        has_ts = "yes" if isinstance(meta, dict) and _has_target_story(meta) else "-"

        lines.append(
            f"| `{pack}` | {profile_sel or '-'} | {db_sel or '-'} | {file_count} | {test_refs} | {dir_exists} | {skill_md_count} | {has_us} | {has_ts} |"
        )

    lines.append("")

    # ---------------------------------------------------------------------------
    # Manual-only candidates
    # ---------------------------------------------------------------------------
    lines.append("## Manual-Only Packs (no profile/DB selection)")
    lines.append("")
    lines.append("These packs require explicit justification (usage_status, target_story, or activation_evidence) or are delete candidates.")
    lines.append("")

    manual_only = sorted(
        p for p in all_pack_names
        if p not in _ALL_PROFILE_SELECTED and p not in _ALL_DB_SELECTED
    )
    for pack in manual_only:
        meta = manifest_packs.get(pack, {})
        has_explicit = isinstance(meta, dict) and (
            _has_usage_status(meta) or _has_target_story(meta) or _has_activation_evidence(meta)
        )
        test_refs = _test_reference_count(root, pack)
        skill_md = _pack_skill_md_count(root, pack) if _pack_dir_exists(root, pack) else 0
        status = "has metadata" if has_explicit else f"NO metadata — test_refs={test_refs}, SKILL.md={skill_md}"
        lines.append(f"- `{pack}`: {status}")

    lines.append("")

    # ---------------------------------------------------------------------------
    # Gate failures
    # ---------------------------------------------------------------------------
    lines.append("## Gate Checks")
    lines.append("")
    if failures:
        lines.append("**FAIL** — one or more gate checks failed:")
        lines.append("")
        for f in failures:
            lines.append(f"- FAIL: {f}")
    else:
        lines.append("**PASS** — all gate checks pass.")

    lines.append("")
    if manual_only_without_metadata:
        lines.append("**WARNING** — manual-only packs without any explicit metadata (candidates for cull or justification):")
        lines.append("")
        for p in manual_only_without_metadata:
            lines.append(f"- `{p}`")

    lines.append("")

    report = "\n".join(lines)
    print(report)

    return 1 if failures else 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Audit skill packs against manifest and profiles.")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repo root directory (default: parent of this script's directory)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write Markdown report to this file instead of stdout",
    )
    args = parser.parse_args()

    if args.root is None:
        # scripts/ lives one level below repo root
        args.root = Path(__file__).parent.parent.resolve()

    if args.out:
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

    code = audit(args.root)

    if args.out:
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
        print(f"Report written to {args.out}")

    sys.exit(code)


if __name__ == "__main__":
    main()
