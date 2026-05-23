"""Multi-file codebase recon: populate .planning/codebase/*.md.

Auto-fills four files from grep + lockfile detection:
  - STACK.md         (codebase.stack.*)
  - STRUCTURE.md     (codebase.structure.*)
  - TESTING.md       (codebase.testing.frameworks, .commands)
  - INTEGRATIONS.md  (codebase.integrations.*) — only if signals detected

Preserves four agent-owned files (refresh_policy: preserve_sections):
  - SUMMARY.md, CONVENTIONS.md, ARCHITECTURE.md, CONCERNS.md
The CLI re-stamps only their `updated_at` frontmatter; section bodies untouched.

Anchor format: `## [codebase.<file>.<key>] Title` (ADR-0008).
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CODEBASE_DIR = PurePosixPath(".planning/codebase")
SKELETON_DIR_RELATIVE = Path("harness/skeleton/clean/.planning/codebase")

CORE_FILES = ("SUMMARY.md", "STACK.md", "STRUCTURE.md", "TESTING.md", "CONVENTIONS.md", "CONCERNS.md")
CONDITIONAL_FILES = ("ARCHITECTURE.md", "INTEGRATIONS.md")
ALL_FILES = CORE_FILES + CONDITIONAL_FILES

AUTO_FILES = {"STACK.md", "STRUCTURE.md", "TESTING.md", "INTEGRATIONS.md"}
AGENT_FILES = {"SUMMARY.md", "CONVENTIONS.md", "CONCERNS.md", "ARCHITECTURE.md"}

_EXCLUDED_DIRS = {
    ".git", "node_modules", ".venv", "venv", "dist", "build",
    "__pycache__", ".pytest_cache", ".harness", ".scratch",
}
_PLANNING_EXCLUDE_SUBDIR = "phases"

# Anchor header regex: `## [codebase.<file>.<key>] Title`
_ANCHOR_RE = re.compile(r"^## \[(codebase\.[a-z_]+\.[a-z_]+)\]\s*(.*)$", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


# ---------------------------------------------------------------------------
# Tech-stack detection
# ---------------------------------------------------------------------------

def detect_tech_stack(root: Path, scope: Optional[list[str]] = None) -> dict[str, list[str]]:
    """Return detected stacks split into anchor-aligned buckets."""
    def _glob_root(*patterns: str) -> bool:
        for pat in patterns:
            if list(root.glob(pat)):
                return True
        return False

    languages: list[str] = []
    package_managers: list[str] = []
    build: list[str] = []
    test_runners: list[str] = []
    lint: list[str] = []
    ci: list[str] = []
    entrypoints: list[str] = []
    runtime: list[str] = []

    # Languages + package managers
    if _glob_root("pyproject.toml"):
        languages.append("Python")
        package_managers.append("pyproject.toml")
        runtime.append("Python")
    elif _glob_root("requirements*.txt") or _glob_root("setup.py"):
        languages.append("Python")
        package_managers.append("pip")
        runtime.append("Python")
    if _glob_root("package.json"):
        languages.append("JavaScript/TypeScript")
        package_managers.append("npm (package.json)")
        runtime.append("Node.js")
    if _glob_root("Cargo.toml"):
        languages.append("Rust")
        package_managers.append("cargo")
        runtime.append("Rust toolchain")
    if _glob_root("go.mod"):
        languages.append("Go")
        package_managers.append("go modules")
        runtime.append("Go")
    if _glob_root("Gemfile"):
        languages.append("Ruby")
        package_managers.append("bundler")
        runtime.append("Ruby")
    if list(root.rglob("*.csproj")):
        languages.append("C#")
        runtime.append(".NET")
    if _glob_root("pom.xml"):
        languages.append("Java")
        package_managers.append("maven")
        runtime.append("JVM")
    if _glob_root("build.gradle") or _glob_root("build.gradle.kts"):
        languages.append("Java/Kotlin")
        package_managers.append("gradle")
        runtime.append("JVM")

    # Build tools (configs)
    for cfg, name in (
        ("vite.config.*", "Vite"),
        ("webpack.config.*", "Webpack"),
        ("rollup.config.*", "Rollup"),
        ("esbuild.config.*", "esbuild"),
        ("tsup.config.*", "tsup"),
    ):
        if _glob_root(cfg):
            build.append(name)
    if _glob_root("Makefile"):
        build.append("Makefile")
    if _glob_root("pyproject.toml"):
        build.append("setuptools/hatch (pyproject)")

    # Test runners
    if (root / "tests").is_dir() or (root / "test").is_dir():
        if _glob_root("pyproject.toml") or _glob_root("setup.py") or _glob_root("requirements*.txt"):
            test_runners.append("pytest")
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            combined = " ".join(scripts.values()).lower()
            if "jest" in combined:
                test_runners.append("jest")
            if "vitest" in combined:
                test_runners.append("vitest")
            if "playwright" in combined:
                test_runners.append("playwright")
            if "mocha" in combined:
                test_runners.append("mocha")
            # Entrypoints from package.json main
            if pkg.get("main"):
                entrypoints.append(str(pkg["main"]))
            if pkg.get("bin"):
                bin_field = pkg["bin"]
                if isinstance(bin_field, dict):
                    entrypoints.extend(str(v) for v in bin_field.values())
                elif isinstance(bin_field, str):
                    entrypoints.append(bin_field)
        except Exception:
            pass
    if _glob_root("Cargo.toml"):
        test_runners.append("cargo test")
    if _glob_root("go.mod"):
        test_runners.append("go test")

    # Lint
    if _glob_root(".eslintrc*") or _glob_root("eslint.config.*"):
        lint.append("eslint")
    if _glob_root(".prettierrc*") or _glob_root("prettier.config.*"):
        lint.append("prettier")
    if _glob_root("ruff.toml") or _glob_root(".ruff.toml"):
        lint.append("ruff")
    if _glob_root(".flake8") or _glob_root("setup.cfg"):
        lint.append("flake8 (possible)")
    if _glob_root("pyproject.toml"):
        try:
            tt = (root / "pyproject.toml").read_text(encoding="utf-8")
            if "[tool.ruff" in tt:
                if "ruff" not in lint:
                    lint.append("ruff")
            if "[tool.black" in tt:
                lint.append("black")
            if "[tool.mypy" in tt:
                lint.append("mypy")
        except Exception:
            pass

    # CI
    if (root / ".github" / "workflows").is_dir():
        ci.append("GitHub Actions")
    if (root / ".gitlab-ci.yml").exists():
        ci.append("GitLab CI")
    if (root / "circle.yml").exists() or (root / ".circleci").is_dir():
        ci.append("CircleCI")
    if (root / "Jenkinsfile").exists():
        ci.append("Jenkins")
    if (root / ".travis.yml").exists():
        ci.append("Travis CI")

    # Common script entry candidates
    for candidate in ("main.py", "app.py", "manage.py", "src/main.ts", "src/main.tsx", "src/index.ts", "cmd/main.go"):
        if (root / candidate).exists():
            entrypoints.append(candidate)

    return {
        "runtime": runtime,
        "languages": languages,
        "package_managers": package_managers,
        "build": build,
        "test_runners": test_runners,
        "lint": lint,
        "ci": ci,
        "entrypoints": entrypoints,
    }


# ---------------------------------------------------------------------------
# Directory tree
# ---------------------------------------------------------------------------

def _should_exclude(d: Path, root: Path) -> bool:
    if d.name in _EXCLUDED_DIRS:
        return True
    try:
        rel = d.relative_to(root)
        parts = rel.parts
        if len(parts) >= 2 and parts[0] == ".planning" and parts[1] == _PLANNING_EXCLUDE_SUBDIR:
            return True
    except ValueError:
        pass
    return False


def build_dir_tree(root: Path, scope: Optional[list[str]] = None) -> list[tuple[Path, int]]:
    """Return list of (relative_path, depth) for depth-1 and depth-2 dirs."""
    results: list[tuple[Path, int]] = []
    top_dirs: list[Path] = []
    if scope:
        for s in scope:
            d = root / s
            if d.is_dir() and not _should_exclude(d, root):
                top_dirs.append(d)
    else:
        for d in sorted(root.iterdir()):
            if d.is_dir() and not _should_exclude(d, root):
                top_dirs.append(d)

    for d in top_dirs:
        results.append((d, 1))
        for sub in sorted(d.iterdir()):
            if sub.is_dir() and not _should_exclude(sub, root):
                results.append((sub, 2))
    return results


# ---------------------------------------------------------------------------
# Integrations detection
# ---------------------------------------------------------------------------

def detect_integrations(root: Path) -> dict[str, list[str]]:
    """Return detected external integrations; empty dict = none detected."""
    out: dict[str, list[str]] = {
        "datastores": [],
        "external_apis": [],
        "cloud": [],
        "auth": [],
        "secrets": [],
        "local_dependencies": [],
    }

    # Datastores via package.json deps + lock + compose
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "pg" in deps:
                out["datastores"].append("PostgreSQL (pg)")
            if "mysql" in deps or "mysql2" in deps:
                out["datastores"].append("MySQL")
            if "mongodb" in deps or "mongoose" in deps:
                out["datastores"].append("MongoDB")
            if "redis" in deps or "ioredis" in deps:
                out["datastores"].append("Redis")
            if "@aws-sdk/client-s3" in deps or "aws-sdk" in deps:
                out["cloud"].append("AWS SDK")
            if "@google-cloud/storage" in deps or "@google-cloud/firestore" in deps:
                out["cloud"].append("Google Cloud")
            if "openid-client" in deps or "passport" in deps:
                out["auth"].append("OIDC / Passport")
        except Exception:
            pass

    if (root / "docker-compose.yml").exists() or (root / "compose.yml").exists():
        out["local_dependencies"].append("docker-compose")
    if (root / "Dockerfile").exists():
        out["local_dependencies"].append("Dockerfile")
    if (root / ".env.example").exists() or (root / ".env.sample").exists():
        out["secrets"].append(".env.example present")
    if (root / "terraform").is_dir() or list(root.glob("*.tf")):
        out["cloud"].append("Terraform")

    return out


def has_integrations(integrations: dict[str, list[str]]) -> bool:
    return any(integrations.values())


# ---------------------------------------------------------------------------
# Frontmatter + anchor parsing
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter_dict, body) from a markdown file."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw = m.group(1)
    fm: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.rstrip()
        if not line or ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip()
    body = text[m.end():]
    return fm, body


def render_frontmatter(fm: dict[str, str]) -> str:
    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def split_anchors(body: str) -> list[tuple[str, str, str]]:
    """Split body into list of (anchor_id, title, body) per `## [anchor] Title` section."""
    matches = list(_ANCHOR_RE.finditer(body))
    if not matches:
        return []
    sections: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        anchor = m.group(1)
        title = m.group(2).strip()
        section_body = body[start:end].lstrip("\n").rstrip()
        sections.append((anchor, title, section_body))
    return sections


def render_anchor_section(anchor: str, title: str, body_text: str) -> str:
    return f"## [{anchor}] {title}\n{body_text}".rstrip() + "\n"


# ---------------------------------------------------------------------------
# Section renderers (auto-content)
# ---------------------------------------------------------------------------

def _bullet_list(items: list[str], empty: str = "(none detected)") -> str:
    if not items:
        return empty
    return "\n".join(f"- {x}" for x in items)


def render_stack_sections(stack: dict[str, list[str]]) -> dict[str, str]:
    return {
        "codebase.stack.runtime": _bullet_list(stack["runtime"]),
        "codebase.stack.languages": _bullet_list(stack["languages"]),
        "codebase.stack.package_managers": _bullet_list(stack["package_managers"]),
        "codebase.stack.build": _bullet_list(stack["build"]),
        "codebase.stack.test": _bullet_list(stack["test_runners"]),
        "codebase.stack.lint": _bullet_list(stack["lint"]),
        "codebase.stack.ci": _bullet_list(stack["ci"]),
        "codebase.stack.entrypoints": _bullet_list(stack["entrypoints"]),
    }


def render_structure_sections(root: Path, tree: list[tuple[Path, int]]) -> dict[str, str]:
    tree_lines: list[str] = ["```"]
    for d, depth in tree:
        try:
            rel = d.relative_to(root)
        except ValueError:
            rel = d
        prefix = "  " * (depth - 1)
        tree_lines.append(f"{prefix}{rel}/")
    tree_lines.append("```")
    return {
        "codebase.structure.tree": "\n".join(tree_lines),
        "codebase.structure.key_paths": "<!-- TODO: agent to fill -->",
        "codebase.structure.generated_paths": "<!-- TODO: agent to fill -->",
        "codebase.structure.ignore_paths": "<!-- TODO: agent to fill -->",
        "codebase.structure.ownership": "<!-- TODO: agent to fill -->",
    }


def render_testing_sections(stack: dict[str, list[str]], root: Path) -> dict[str, str]:
    frameworks = _bullet_list(stack["test_runners"])
    cmds: list[str] = []
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            for key in ("test", "test:unit", "test:integration", "test:e2e", "typecheck", "lint"):
                if key in scripts:
                    cmds.append(f"`npm run {key}` — {scripts[key]}")
        except Exception:
            pass
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        if not cmds:
            cmds.append("`pytest` — assumed default")
    cmd_block = "\n".join(cmds) if cmds else "<!-- TODO: agent to fill exact commands -->"
    return {
        "codebase.testing.frameworks": frameworks,
        "codebase.testing.commands": cmd_block,
        "codebase.testing.scopes": "<!-- TODO: agent to fill -->",
        "codebase.testing.fixtures": "<!-- TODO: agent to fill -->",
        "codebase.testing.repro": "<!-- TODO: agent to fill -->",
        "codebase.testing.known_failures": "<!-- TODO: agent to fill -->",
    }


def render_integrations_sections(integrations: dict[str, list[str]]) -> dict[str, str]:
    return {
        "codebase.integrations.datastores": _bullet_list(integrations["datastores"]),
        "codebase.integrations.external_apis": _bullet_list(integrations["external_apis"]),
        "codebase.integrations.cloud": _bullet_list(integrations["cloud"]),
        "codebase.integrations.auth": _bullet_list(integrations["auth"]),
        "codebase.integrations.secrets": _bullet_list(integrations["secrets"]),
        "codebase.integrations.local_dependencies": _bullet_list(integrations["local_dependencies"]),
    }


# ---------------------------------------------------------------------------
# File-level merge
# ---------------------------------------------------------------------------

def merge_file(
    *,
    template_text: str,
    existing_text: Optional[str],
    auto_sections: dict[str, str],
    overwrite: bool,
    generated_by: str,
    today: str,
) -> str:
    """Merge auto-detected section bodies into a file, preserving non-auto sections.

    - If overwrite=True (auto file): auto sections fully replace the existing body for those anchors.
    - If overwrite=False (agent file): existing body preserved; only frontmatter updated_at is restamped.
    """
    base_text = existing_text if existing_text is not None else template_text
    fm, body = parse_frontmatter(base_text)

    # Update frontmatter
    fm["updated_at"] = today
    fm["generated_by"] = generated_by
    if not fm.get("schema_version"):
        fm["schema_version"] = "1"

    # Status: current if we ran successfully
    fm["status"] = "current"

    if not overwrite:
        # Agent file: keep body verbatim
        new_text = render_frontmatter(fm) + body.lstrip("\n")
        if not new_text.endswith("\n"):
            new_text += "\n"
        return new_text

    # Auto file: parse anchors from template (source of anchor order), substitute auto bodies
    tmpl_fm, tmpl_body = parse_frontmatter(template_text)
    tmpl_sections = split_anchors(tmpl_body)
    if not tmpl_sections:
        # No anchors in template — fall back to just frontmatter + auto bodies in dict order
        body_parts = [f"## [{a}] {a.split('.')[-1].title()}\n{b}" for a, b in auto_sections.items()]
        new_body = "\n\n".join(body_parts) + "\n"
    else:
        # Preserve existing non-auto sections, replace auto ones
        existing_fm, existing_body = parse_frontmatter(base_text)
        existing_sections_by_anchor = {a: (t, b) for a, t, b in split_anchors(existing_body)}

        # Extract preamble (title etc.) from template
        first_anchor = tmpl_sections[0]
        preamble_end = tmpl_body.find(f"## [{first_anchor[0]}]")
        preamble = tmpl_body[:preamble_end].rstrip() if preamble_end > 0 else ""

        out_parts: list[str] = []
        if preamble:
            out_parts.append(preamble)
        for anchor, title, _ in tmpl_sections:
            if anchor in auto_sections:
                body_text = auto_sections[anchor]
            elif anchor in existing_sections_by_anchor:
                _, prev_body = existing_sections_by_anchor[anchor]
                body_text = prev_body
            else:
                body_text = "<!-- TODO -->"
            out_parts.append(f"## [{anchor}] {title}\n{body_text}".rstrip())
        new_body = "\n\n".join(out_parts) + "\n"

    return render_frontmatter(fm) + new_body


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_codebase_docs(
    *,
    root: Path,
    scope: Optional[list[str]] = None,
    existing: Optional[dict[str, str]] = None,
    templates: Optional[dict[str, str]] = None,
    generated_by: str = "harness-recon",
    today: Optional[str] = None,
) -> dict[str, str]:
    """Build all `.planning/codebase/*.md` files as {filename: content}.

    Parameters
    ----------
    root:
        Target project root.
    scope:
        Optional subdir names to restrict scan.
    existing:
        Map of {filename: current_content} for files already present.
    templates:
        Map of {filename: template_content} (from harness skeleton).
    generated_by:
        Stamped into frontmatter.
    today:
        ISO date override (deterministic tests).
    """
    if today is None:
        today = str(date.today())
    existing = existing or {}
    templates = templates or {}

    stack = detect_tech_stack(root, scope=scope)
    tree = build_dir_tree(root, scope=scope)
    integrations = detect_integrations(root)

    files_out: dict[str, str] = {}

    # STACK.md (auto)
    files_out["STACK.md"] = merge_file(
        template_text=templates.get("STACK.md", _default_template("STACK.md")),
        existing_text=existing.get("STACK.md"),
        auto_sections=render_stack_sections(stack),
        overwrite=True,
        generated_by=generated_by,
        today=today,
    )

    # STRUCTURE.md (auto)
    files_out["STRUCTURE.md"] = merge_file(
        template_text=templates.get("STRUCTURE.md", _default_template("STRUCTURE.md")),
        existing_text=existing.get("STRUCTURE.md"),
        auto_sections=render_structure_sections(root, tree),
        overwrite=True,
        generated_by=generated_by,
        today=today,
    )

    # TESTING.md (auto)
    files_out["TESTING.md"] = merge_file(
        template_text=templates.get("TESTING.md", _default_template("TESTING.md")),
        existing_text=existing.get("TESTING.md"),
        auto_sections=render_testing_sections(stack, root),
        overwrite=True,
        generated_by=generated_by,
        today=today,
    )

    # INTEGRATIONS.md (auto, conditional)
    if has_integrations(integrations) or "INTEGRATIONS.md" in existing:
        files_out["INTEGRATIONS.md"] = merge_file(
            template_text=templates.get("INTEGRATIONS.md", _default_template("INTEGRATIONS.md")),
            existing_text=existing.get("INTEGRATIONS.md"),
            auto_sections=render_integrations_sections(integrations),
            overwrite=True,
            generated_by=generated_by,
            today=today,
        )

    # Agent-owned files: restamp frontmatter only
    for fname in ("SUMMARY.md", "CONVENTIONS.md", "CONCERNS.md", "ARCHITECTURE.md"):
        if fname in existing or fname in templates:
            files_out[fname] = merge_file(
                template_text=templates.get(fname, _default_template(fname)),
                existing_text=existing.get(fname),
                auto_sections={},
                overwrite=False,
                generated_by=existing.get(fname) and _read_generated_by(existing[fname]) or "skeleton",
                today=today,
            )

    return files_out


def _read_generated_by(text: str) -> Optional[str]:
    fm, _ = parse_frontmatter(text)
    return fm.get("generated_by")


def _default_template(filename: str) -> str:
    """Minimal in-memory fallback if skeleton template is missing."""
    artifact_type = "codebase." + filename.replace(".md", "").lower()
    return (
        f"---\nschema_version: 1\nartifact_type: {artifact_type}\n"
        "generated_by: skeleton\nupdated_at: 1970-01-01\n"
        "ownership: auto\nsource: detected\n"
        "refresh_policy: overwrite\nstatus: partial\n---\n\n"
        f"# {filename.replace('.md', '').title()}\n"
    )


def load_skeleton_templates(harness_root: Path) -> dict[str, str]:
    """Load template content for each codebase file from the harness skeleton tree."""
    out: dict[str, str] = {}
    sk_dir = harness_root / SKELETON_DIR_RELATIVE
    if not sk_dir.is_dir():
        return out
    for fname in ALL_FILES:
        p = sk_dir / fname
        if p.exists():
            out[fname] = p.read_text(encoding="utf-8")
    return out


def load_existing_codebase(target: Path) -> dict[str, str]:
    """Load any existing `.planning/codebase/*.md` files in the target."""
    out: dict[str, str] = {}
    cb_dir = target / ".planning" / "codebase"
    if not cb_dir.is_dir():
        return out
    for fname in ALL_FILES:
        p = cb_dir / fname
        if p.exists():
            out[fname] = p.read_text(encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------

def compute_files_diff(
    *,
    old: dict[str, str],
    new: dict[str, str],
    dir_prefix: str = ".planning/codebase",
) -> str:
    """Return unified diff across all changed files."""
    import difflib
    out_chunks: list[str] = []
    all_names = sorted(set(old) | set(new))
    for name in all_names:
        old_text = old.get(name, "")
        new_text = new.get(name, "")
        if old_text == new_text:
            continue
        diff = difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{dir_prefix}/{name}",
            tofile=f"b/{dir_prefix}/{name}",
        )
        out_chunks.append("".join(diff))
    return "\n".join(out_chunks)
