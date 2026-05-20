# Smoke Test Return-Code Contract

Date: 2026-05-21
Status: active
Enforced by: `scripts/test_smoke_contract.py`

## Rationale

False-green smoke runs mask real failures.  The most common cause is a shell
pipeline or Python subprocess call that discards the command's exit code before
the test reads it.  This contract enumerates the forbidden patterns and the
required alternatives.

## Rules

### Rule 1 — pipe-tail rc clobber

**Forbidden**

```bash
output=$(cmd 2>&1 | tail -n 20); echo $?
```

`echo $?` captures `tail`'s exit code (always 0), not `cmd`'s.

**Required**

```bash
output=$(cmd 2>&1); rc=$?; echo "$output" | tail -n 20; exit "$rc"
# or: set -o pipefail at the top of the script
```

### Rule 2 — pipe-head rc clobber

Same class as Rule 1, with `head` instead of `tail`.

### Rule 3 — pipeline without pipefail

**Forbidden**

```bash
cmd 2>&1 | grep pattern; echo $?
```

Without `set -o pipefail` the `echo $?` reflects `grep`'s exit, not `cmd`'s.

**Required**

Either add `set -o pipefail` before the pipeline, or capture output first:

```bash
set -o pipefail
cmd 2>&1 | grep pattern
```

or

```bash
out=$(cmd 2>&1); rc=$?; echo "$out" | grep pattern; (exit "$rc")
```

### Rule 4 — `|| true` silencing

**Forbidden**

```bash
risky_cmd || true
```

Swallows a non-zero exit silently; the test will appear green even when
`risky_cmd` fails.

**Required**

Either let the failure propagate, or document why suppression is intentional:

```bash
risky_cmd || true  # smoke-contract: allow cleanup; non-fatal if already absent
```

Any line with `|| true` that lacks a `# smoke-contract: allow <reason>` comment
is flagged as a violation.

### Rule 5 — `subprocess.run(check=False)` without returncode assertion

**Forbidden (Python)**

```python
subprocess.run(["cmd"], check=False)
# ... no result.returncode check ...
```

`check=False` suppresses the automatic exception; if the caller never reads
`.returncode` the exit code is silently discarded.

**Required**

```python
result = subprocess.run(["cmd"], check=False)
assert result.returncode == 0, result.stderr
```

The lint searches within 10 lines after the `check=False` line for any
reference to `returncode`.  If the `subprocess.run` is in a helper that
*returns* the result to callers who check it, add an allowlist comment:

```python
return subprocess.run(["cmd"], check=False)  # smoke-contract: allow caller checks returncode
```

### Rule 6 — `eval $(...)` rc loss

**Forbidden**

```bash
eval $(some-cmd)
echo $?    # reflects eval's parse result, not some-cmd's
```

**Required**

```bash
output=$(some-cmd); rc=$?
eval "$output"
(exit "$rc")
```

## Allowlist mechanism

Any forbidden line may be opted out by appending:

```
# smoke-contract: allow <reason>
```

The reason must be non-empty.  The lint accepts any non-whitespace text after
`allow`.

## Examples

### Good

```python
result = subprocess.run(["harness", "check"], check=False, capture_output=True)
assert result.returncode == 0, result.stderr
```

```bash
out=$(python3 harness.py init 2>&1)
rc=$?
echo "$out" | tail -20
exit "$rc"
```

### Bad (caught by lint)

```python
subprocess.run(["harness", "check"], check=False, capture_output=True)
# no returncode assertion -- lint flags this
```

```bash
python3 harness.py init 2>&1 | tail -20
echo $?   # <-- tail's rc, not harness.py's
```

## Scope

The lint scans:

- `scripts/test_*.py`
- `tests/**/*.py`
- `.github/workflows/*.yml`
- `scripts/*.sh`

Production code (`scripts/lib/*.py`, `scripts/harness.py`) is out of scope for
this lint.
