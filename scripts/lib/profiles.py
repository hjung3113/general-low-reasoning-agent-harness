"""Profile, database, and pack-resolution helpers for the harness."""
from __future__ import annotations

import sys
from typing import Iterable

KNOWN_PROFILES = {"generic", "dotnet-etl", "python-etl", "react-web"}
LEGACY_PROFILE_ALIASES = {"dotnet-etl-mssql": "dotnet-etl"}

_PROFILE_DEFAULT_PACKS = {
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

_DB_PACKS = {
    "mssql": ("tech-mssql", "workflow-db-context"),
    "postgresql": ("tech-postgresql", "workflow-db-context"),
    "none": (),
}


def default_packs_for_profile(profile: str) -> list[str]:
    return list(_PROFILE_DEFAULT_PACKS.get(profile, ("workflow-core",)))


def db_packs(db: str) -> list[str]:
    if db not in _DB_PACKS:
        raise ValueError(f"unknown db: {db!r}; expected one of mssql, postgresql, none")
    return list(_DB_PACKS[db])


def normalize_profiles(values: Iterable[str]) -> list[str]:
    """Validate and remap ``--profiles`` input.

    - Legacy aliases (e.g. ``dotnet-etl-mssql``) are remapped with a stderr
      deprecation warning.
    - Unknown profile names raise SystemExit.
    - Known names pass through unchanged.
    """
    out: list[str] = []
    for raw in values:
        if raw in LEGACY_PROFILE_ALIASES:
            target = LEGACY_PROFILE_ALIASES[raw]
            print(
                f"WARN: profile name {raw!r} is deprecated; using {target!r}. "
                f"This alias will be removed in v0.8.",
                file=sys.stderr,
            )
            out.append(target)
        elif raw in KNOWN_PROFILES:
            out.append(raw)
        else:
            raise SystemExit(f"unknown harness scope requested: profile: {raw}")
    return out


PROFILE_MODE_OWNERS: dict[str, str] = {"ui-engineer": "react-web"}
