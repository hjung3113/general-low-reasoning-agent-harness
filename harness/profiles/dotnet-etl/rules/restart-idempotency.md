---
roo_mode: ops-observability
opencode: true
title: ETL restart and idempotency
---

For any ETL pipeline change, treat the pipeline as restartable from any prior
checkpoint state.

- Every staging table or intermediate artifact must have a documented "what
  happens on restart" answer in the plan: cleared, upserted, appended with a
  watermark, or treated as immutable.
- Loads into target tables must be expressible as "merge by natural key" or
  "append with deduplication"; raw appends without a dedup story require an
  explicit decision note.
- Add structured log fields `job_id`, `run_id`, `step`, `rows_in`, `rows_out`,
  `outcome` (`ok|skipped|partial|failed`) at every step boundary.
- Failures should write enough state that a rerun can resume; never leave a
  partially-written target table without a recovery path.
