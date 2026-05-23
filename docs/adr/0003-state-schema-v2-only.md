# State schema v2 is the only supported schema

`.scratch/phase-state.json` is read and written only at schema v2. Earlier schemas (v0, v1) are not migrated at runtime — the migration code (`state_migrate.py`, `state_migrate_t04.py`, `migrate_state.py`, ~104 LOC + tests) was deleted in Milestone 2 Item 1.

This trades adopter compatibility for code clarity. The harness had been live long enough that all known installs were on v2, and the migration path carried real complexity (legacy value coercion, ordering rules, txn interaction). Any target still on v0/v1 must reinitialize state before upgrading; the harness will refuse to read older schemas rather than silently upgrade them. Reversing means re-adding a migration layer with its full surface — fixture coverage, crash-safety, and the timestamp-stamping rules that motivated v2 in the first place.
