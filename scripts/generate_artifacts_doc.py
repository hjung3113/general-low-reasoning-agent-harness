#!/usr/bin/env python3
"""Generate docs/ARTIFACTS.md from harness/manifest.json.

Usage:
    python3 scripts/generate_artifacts_doc.py          # regenerate in place
    python3 scripts/generate_artifacts_doc.py --check  # exit 1 if stale

No wall-clock timestamps are emitted — output is fully deterministic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root resolution — script may be run from any cwd.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_MANIFEST_PATH = _REPO_ROOT / "harness" / "manifest.json"
_OUTPUT_PATH = _REPO_ROOT / "docs" / "ARTIFACTS.md"


# ---------------------------------------------------------------------------
# Markdown escaping
# ---------------------------------------------------------------------------

def _md(text: str) -> str:
    """Escape pipe and backtick characters for Markdown table cells."""
    return text.replace("|", "\\|").replace("`", "'")


def _code(text: str) -> str:
    """Wrap in backticks, escaping any embedded backticks."""
    return "`" + text.replace("`", "'") + "`"


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------

def _table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a GFM Markdown table with auto-padded columns."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))

    def _fmt_row(cells: list[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            w = widths[i] if i < len(widths) else len(cell)
            parts.append(cell.ljust(w))
        return "| " + " | ".join(parts) + " |"

    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    lines = [_fmt_row(headers), sep] + [_fmt_row(row) for row in rows]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def _load_manifest() -> dict:
    raw = _MANIFEST_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    # Replace __release__ sentinel for display only.
    version = data.get("version", "__release__")
    if version == "__release__":
        version = "(release placeholder — replaced at build time)"
    data["_display_version"] = version
    return data


def _generate(data: dict) -> str:
    """Return the full generated ARTIFACTS.md content."""
    lines: list[str] = []

    version = data["_display_version"]
    files: list[dict] = data.get("files", [])
    packs: dict = data.get("packs", {})
    removed: list[dict] = data.get("removed_in_version", [])

    # Sort files by path for stable output.
    files_sorted = sorted(files, key=lambda f: f.get("path", ""))

    # Count by policy.
    policy_counts: dict[str, int] = {}
    for f in files_sorted:
        p = f.get("policy", "unknown")
        policy_counts[p] = policy_counts.get(p, 0) + 1

    # ---------------------------------------------------------------------------
    # Header
    # ---------------------------------------------------------------------------
    lines.append("# Artifact Contract — `docs/ARTIFACTS.md`")
    lines.append("")
    lines.append("> **Generated file** — do not hand-edit.")
    lines.append("> Regenerate with: `python3 scripts/generate_artifacts_doc.py`")
    lines.append("> Enforce with: `python3 scripts/generate_artifacts_doc.py --check`")
    lines.append("")
    lines.append(f"Manifest version: `{version}`  ")
    lines.append(f"Total files: **{len(files_sorted)}**  ")
    for policy in sorted(policy_counts):
        lines.append(f"- `{policy}`: {policy_counts[policy]}")
    lines.append("")

    # ---------------------------------------------------------------------------
    # 1. Installed files table
    # ---------------------------------------------------------------------------
    lines.append("## 1. Installed Files")
    lines.append("")

    headers = ["path", "policy", "source", "owner", "profile", "pack", "adapter"]
    rows: list[list[str]] = []
    for f in files_sorted:
        rows.append([
            _code(f.get("path", "")),
            _code(f.get("policy", "")),
            _code(f.get("source", "")),
            _md(f.get("owner", "")),
            _md(f.get("profile", "") or ""),
            _md(f.get("pack", "") or ""),
            _md(f.get("adapter", "") or ""),
        ])
    lines.append(_table(headers, rows))

    # ---------------------------------------------------------------------------
    # 2. Packs table
    # ---------------------------------------------------------------------------
    lines.append("## 2. Packs")
    lines.append("")
    lines.append("Pack metadata from `harness/manifest.json` `packs` section.")
    lines.append("")

    pack_headers = ["pack", "category", "suggests", "capabilities"]
    pack_rows: list[list[str]] = []
    for pack_name in sorted(packs.keys()):
        pack_data = packs[pack_name]
        category = pack_data.get("category", "")
        suggests = ", ".join(pack_data.get("suggests", []))
        capabilities = "; ".join(pack_data.get("capabilities", []))
        pack_rows.append([
            _code(pack_name),
            _md(category),
            _md(suggests),
            _md(capabilities),
        ])
    lines.append(_table(pack_headers, pack_rows))

    # ---------------------------------------------------------------------------
    # 3. Graveyard / Removed Artifacts
    # ---------------------------------------------------------------------------
    lines.append("## 3. Graveyard — Removed Artifacts")
    lines.append("")

    if not removed:
        lines.append("No entries in `removed_in_version`.")
        lines.append("")
    else:
        lines.append(
            "Artifacts removed from the harness in prior versions. "
            "Upgrade behavior is governed by the `upgrade_action` field."
        )
        lines.append("")
        grave_headers = ["path", "removed_in", "upgrade_action", "reason / replaced_by"]
        grave_rows: list[list[str]] = []
        for entry in sorted(removed, key=lambda e: (e.get("removed_in", ""), e.get("path", ""))):
            path = entry.get("path", "")
            removed_in = entry.get("removed_in", "")
            upgrade_action = entry.get("upgrade_action", "warn")
            reason = entry.get("reason", "") or entry.get("replaced_by", "")
            grave_rows.append([
                _code(path),
                _md(removed_in),
                _code(upgrade_action),
                _md(reason),
            ])
        lines.append(_table(grave_headers, grave_rows))

    # ---------------------------------------------------------------------------
    # Footer (no wall-clock timestamp)
    # ---------------------------------------------------------------------------
    lines.append("---")
    lines.append("")
    lines.append(
        "_This file is generated from `harness/manifest.json` by "
        "`scripts/generate_artifacts_doc.py`. "
        "Source of truth: manifest. Do not hand-edit._"
    )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate docs/ARTIFACTS.md from harness/manifest.json.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if docs/ARTIFACTS.md is stale (does not regenerate).",
    )
    args = parser.parse_args(argv)

    if not _MANIFEST_PATH.exists():
        print(f"ERROR: manifest not found at {_MANIFEST_PATH}", file=sys.stderr)
        return 1

    data = _load_manifest()
    generated = _generate(data)

    if args.check:
        if not _OUTPUT_PATH.exists():
            print(f"FAIL: {_OUTPUT_PATH} does not exist. Run: python3 scripts/generate_artifacts_doc.py", file=sys.stderr)
            return 1
        current = _OUTPUT_PATH.read_text(encoding="utf-8")
        if current != generated:
            print(f"FAIL: {_OUTPUT_PATH} is stale. Run: python3 scripts/generate_artifacts_doc.py", file=sys.stderr)
            # Show a brief summary of what changed (first 20 diff lines).
            import difflib
            diff = list(difflib.unified_diff(
                current.splitlines(keepends=True),
                generated.splitlines(keepends=True),
                fromfile="current docs/ARTIFACTS.md",
                tofile="generated docs/ARTIFACTS.md",
                n=3,
            ))
            sys.stderr.writelines(diff[:20])
            if len(diff) > 20:
                print(f"... ({len(diff) - 20} more diff lines)", file=sys.stderr)
            return 1
        print(f"OK: {_OUTPUT_PATH} is current.")
        return 0

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_PATH.write_text(generated, encoding="utf-8")
    print(f"Generated {_OUTPUT_PATH} ({len(generated)} bytes, {len(data['files'])} files, {len(data['packs'])} packs).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
