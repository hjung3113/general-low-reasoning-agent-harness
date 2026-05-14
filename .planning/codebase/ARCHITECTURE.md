# ARCHITECTURE - General Harness

The repository has four layers:

1. Core protocol and skeleton files.
2. Client adapters.
3. Profiles and skill packs.
4. Distribution tooling.

`scripts/harness.py` reads `harness/manifest.json`, selects entries by adapter/profile/pack, installs files into a target, records `.harness/installed-manifest.json`, and validates installed targets.

