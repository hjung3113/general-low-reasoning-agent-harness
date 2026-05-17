# `tests/fixtures/lock/` — pinned lock-protocol fixtures (design §9.1)

| Path | Shape | Used by |
|---|---|---|
| `stale_owner_alive/phase-state.json.lock` | Owner record whose `pid=1` and `hostname=fixture-host` will be classified by `phase_lock.classify()` with mocked seams. The fixture pins the record schema that S01-C tests + S01-D txn recovery rely on. | S01-C, S01-D |
| `recovery_mutex_held/phase-state.json.lock` + `.recovery` | Primary lock plus a recovery mutex present. `acquire_primary()` must back off (STEP A) and never issue an O_EXCL on the primary while `.recovery` exists (i1 invariant). | S01-C, S01-D |

Both fixtures are read-only inputs. Tests copy them into a `tmp_path`-scoped
`.scratch/` before exercising the lock paths so the on-disk shape is the
single source of truth for cross-slice regression.
