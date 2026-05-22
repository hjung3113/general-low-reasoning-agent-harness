#!/usr/bin/env bash
# v0.9.8 full smoke matrix.
# Runs every harness CLI surface + flag combo against tmp targets.
# Reports PASS/FAIL per case. Exit 0 only if ALL pass.

set +e  # don't abort on individual failures; capture each
REPO="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd || pwd)"
[ -d "$REPO/scripts" ] || REPO="/Users/hyojung/Desktop/2026/general-low-reasoning-agent-harness"
export PYTHONPATH="$REPO/scripts"
HARNESS="python3 $REPO/scripts/harness.py"
SMOKE_ROOT=/tmp/v098-smoke
rm -rf "$SMOKE_ROOT" && mkdir -p "$SMOKE_ROOT"

PASS=0
FAIL=0
declare -a FAILS=()

run() {
    # run NAME EXPECTED_RC CMD...
    local name="$1"; shift
    local exp="$1"; shift
    local outf="$SMOKE_ROOT/${name//\//_}.stdout"
    local errf="$SMOKE_ROOT/${name//\//_}.stderr"
    bash -c "$*" 1>"$outf" 2>"$errf"
    local rc=$?
    if [ "$rc" = "$exp" ]; then
        PASS=$((PASS+1))
        echo "PASS [$name] rc=$rc (expected $exp)"
    else
        FAIL=$((FAIL+1))
        FAILS+=("$name: rc=$rc expected=$exp")
        echo "FAIL [$name] rc=$rc (expected $exp)"
        echo "  stderr last 5:"
        tail -5 "$errf" | sed 's/^/    /'
    fi
}

assert_contains() {
    # assert_contains NAME FILE PATTERN
    local name="$1"; local file="$2"; local pat="$3"
    if grep -q "$pat" "$file" 2>/dev/null; then
        PASS=$((PASS+1))
        echo "PASS [$name] contains \"$pat\""
    else
        FAIL=$((FAIL+1))
        FAILS+=("$name: missing pattern \"$pat\" in $file")
        echo "FAIL [$name] missing \"$pat\""
    fi
}

assert_empty() {
    local name="$1"; local file="$2"
    if [ ! -s "$file" ]; then
        PASS=$((PASS+1))
        echo "PASS [$name] empty"
    else
        FAIL=$((FAIL+1))
        FAILS+=("$name: file not empty")
        echo "FAIL [$name] $file not empty:"
        head -3 "$file" | sed 's/^/    /'
    fi
}

echo "=============================================="
echo "Tier 1 — init (fresh install)"
echo "=============================================="

# 1a basic
T=$SMOKE_ROOT/t1a && mkdir -p $T
run "1a-init-basic" 0 "$HARNESS init --target $T --profile generic --adapter roo"
assert_contains "1a-stdout-summary" "$SMOKE_ROOT/1a-init-basic.stdout" "installed harness"
assert_contains "1a-stderr-progress" "$SMOKE_ROOT/1a-init-basic.stderr" "staging files"
assert_contains "1a-stderr-finalize" "$SMOKE_ROOT/1a-init-basic.stderr" "finalizing"

# 1b quiet
T=$SMOKE_ROOT/t1b && mkdir -p $T
run "1b-init-quiet" 0 "$HARNESS init --target $T --profile generic --adapter roo --quiet"
assert_contains "1b-stdout-summary" "$SMOKE_ROOT/1b-init-quiet.stdout" "installed harness"
assert_empty "1b-stderr-silent" "$SMOKE_ROOT/1b-init-quiet.stderr"

# 1c dry-run
T=$SMOKE_ROOT/t1c && mkdir -p $T
run "1c-init-dry-run" 0 "$HARNESS init --target $T --profile generic --adapter roo --dry-run"
assert_contains "1c-dry-run-marker" "$SMOKE_ROOT/1c-init-dry-run.stdout" "init dry-run"
assert_contains "1c-no-mutation" "$SMOKE_ROOT/1c-init-dry-run.stdout" "no mutation"
# verify target untouched
if [ -z "$(ls -A $T 2>/dev/null)" ]; then
    PASS=$((PASS+1)); echo "PASS [1c-dry-target-empty]"
else
    FAIL=$((FAIL+1)); echo "FAIL [1c-dry-target-empty] files appeared"
fi

# 1d opencode adapter
T=$SMOKE_ROOT/t1d && mkdir -p $T
run "1d-init-opencode" 0 "$HARNESS init --target $T --profile generic --adapter opencode"
assert_contains "1d-stdout-summary" "$SMOKE_ROOT/1d-init-opencode.stdout" "installed harness"

# 1e both adapters
T=$SMOKE_ROOT/t1e && mkdir -p $T
run "1e-init-both" 0 "$HARNESS init --target $T --profile generic --adapter both"

# 1f double-init refusal (must fail)
T=$SMOKE_ROOT/t1f && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
run "1f-double-init-refused" 1 "$HARNESS init --target $T --profile generic --adapter roo"
assert_contains "1f-refusal-message" "$SMOKE_ROOT/1f-double-init-refused.stderr" "Refusing to overwrite"

# 1g approver-email flag
T=$SMOKE_ROOT/t1g && mkdir -p $T
run "1g-init-approver-flag" 0 "$HARNESS init --target $T --profile generic --adapter roo --approver-email test@example.com"

echo ""
echo "=============================================="
echo "Tier 2 — upgrade matrix"
echo "=============================================="

# 2a fresh dev → dev no-op upgrade
T=$SMOKE_ROOT/t2a && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
run "2a-upgrade-noop" 0 "$HARNESS upgrade --target $T"
assert_contains "2a-stdout-summary" "$SMOKE_ROOT/2a-upgrade-noop.stdout" "upgraded harness"
assert_contains "2a-stderr-staged" "$SMOKE_ROOT/2a-upgrade-noop.stderr" "staging files"

# 2b upgrade --quiet
T=$SMOKE_ROOT/t2b && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
run "2b-upgrade-quiet" 0 "$HARNESS upgrade --target $T --quiet"
assert_contains "2b-stdout-summary" "$SMOKE_ROOT/2b-upgrade-quiet.stdout" "upgraded harness"
assert_empty "2b-stderr-silent" "$SMOKE_ROOT/2b-upgrade-quiet.stderr"

# 2c upgrade --dry-run
T=$SMOKE_ROOT/t2c && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
run "2c-upgrade-dry-run" 0 "$HARNESS upgrade --target $T --dry-run"
assert_contains "2c-dry-run-marker" "$SMOKE_ROOT/2c-upgrade-dry-run.stdout" "upgrade dry-run"

# 2d signed → dev upgrade refusal (trust-downgrade): exercise via an
# UNTAGGED commit in develop history so version.development_version() runs.
WT=/tmp/v098-smoke-v096wt
git worktree remove "$WT" 2>/dev/null
git -C "$REPO" worktree add "$WT" v0.9.6 2>/dev/null
T=$SMOKE_ROOT/t2d && mkdir -p $T
PYTHONPATH=$WT/scripts python3 $WT/scripts/harness.py init --target $T --profile generic --adapter roo >/dev/null 2>&1
DEV_WT=/tmp/v098-smoke-devwt
git worktree remove "$DEV_WT" 2>/dev/null
# Pick the most recent commit on develop NOT pointed at by any release tag.
DEV_REF=$(git -C "$REPO" rev-list HEAD --not $(git -C "$REPO" for-each-ref --format='%(refname)' refs/tags) 2>/dev/null | head -1)
if [ -z "$DEV_REF" ]; then
    PASS=$((PASS+1)); echo "SKIP [2d-signed-to-dev-no-refusal] no untagged commit available"
else
    git -C "$REPO" worktree add "$DEV_WT" "$DEV_REF" 2>/dev/null
    # v0.9.13: trust-downgrade refusal removed; upgrade just succeeds.
    run "2d-signed-to-dev-no-refusal" 0 "PYTHONPATH=$DEV_WT/scripts python3 $DEV_WT/scripts/harness.py upgrade --target $T"
fi

# 2e v0.9.6 → v0.9.7 (signed→signed) real upgrade
WT7=/tmp/v098-smoke-v097wt
git worktree remove "$WT7" 2>/dev/null
git -C "$REPO" worktree add "$WT7" v0.9.7 2>/dev/null
T=$SMOKE_ROOT/t2e && mkdir -p $T
PYTHONPATH=$WT/scripts python3 $WT/scripts/harness.py init --target $T --profile generic --adapter roo >/dev/null 2>&1
run "2e-signed-upgrade" 0 "PYTHONPATH=$WT7/scripts python3 $WT7/scripts/harness.py upgrade --target $T"

echo ""
echo "=============================================="
echo "Tier 3 — check / doctor / status / next"
echo "=============================================="

# 3a check on fresh target
T=$SMOKE_ROOT/t3a && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
run "3a-check-fresh" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py check"

# 3b check --verify-hashes
run "3b-check-verify-hashes" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py check --verify-hashes"

# 3c doctor markdown
run "3c-doctor-md" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py doctor --format markdown"

# 3d doctor json
run "3d-doctor-json" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py doctor --format json"

# 3e status
run "3e-status" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py status"

# 3f next
run "3f-next" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py next"

# 3g state show
run "3g-state-show" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py state show"

# 3h state show json
run "3h-state-show-json" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py state show --format json"

# 3i state repair (no-op on healthy install)
run "3i-state-repair-noop" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py state repair"


echo ""
echo "=============================================="
echo "Tier 4 — uninstall + release-check + error paths"
echo "=============================================="

# 4a uninstall dry-run (must pick a select scope)
T=$SMOKE_ROOT/t4a && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
run "4a-uninstall-dry-run" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py uninstall --target $T --select 1 --dry-run"

# 4b release-check on dev source (expected fail — not on a tag)
run "4b-release-check-dev-fails" 1 "$HARNESS release-check"

# 4c bad target path
run "4c-bad-target" 1 "$HARNESS check --target /nonexistent/path"

# 4d missing required arg
run "4d-init-missing-target" 2 "$HARNESS init"

# 4e --version with bad value (normalize_release_version → ValueError → rc=1)
run "4e-bad-version" 1 "$HARNESS --version not-a-version init --target /tmp/dontcare"

# 4f stale staging detection
T=$SMOKE_ROOT/t4f && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
mkdir -p "$T/.harness/.staging-99999-stale"
touch "$T/.harness/.staging-99999-stale.journal.jsonl"
# backdate
touch -t $(date -v-2H +%Y%m%d%H%M 2>/dev/null || date -d "2 hours ago" +%Y%m%d%H%M) "$T/.harness/.staging-99999-stale"
run "4f-check-warns-stale" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py check"
assert_contains "4f-stale-warning" "$SMOKE_ROOT/4f-check-warns-stale.stdout" "중단된 설치 감지"

# 4g multiple stale (summary path)
mkdir -p "$T/.harness/.staging-88888-stale2"
touch "$T/.harness/.staging-88888-stale2.journal.jsonl"
touch -t $(date -v-3H +%Y%m%d%H%M 2>/dev/null || date -d "3 hours ago" +%Y%m%d%H%M) "$T/.harness/.staging-88888-stale2"
run "4g-check-summary" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py check"
assert_contains "4g-summary-count" "$SMOKE_ROOT/4g-check-summary.stdout" "2개 중단된 설치 감지"
assert_contains "4g-all-runids" "$SMOKE_ROOT/4g-check-summary.stdout" "all runids"

echo ""
echo "=============================================="
echo "Tier 5 — phase verbs"
echo "=============================================="

# 5a phase set/list (skip if requires elaborate setup)
T=$SMOKE_ROOT/t5a && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
run "5a-phase-help" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py phase --help"

# 5b session help
run "5b-session-help" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py session --help"

# 5f install help (advanced)
run "5f-install-help" 0 "HARNESS_ADVANCED=1 $HARNESS install --help"

# v0.9.13: fsd-run-* removed (autopilot gone)

# 5i normal user surface (next/run/check) hidden by default
run "5i-normal-help" 0 "$HARNESS"

echo ""
echo "=============================================="
echo "Tier 6 — recovery + edge cases"
echo "=============================================="

# 6a state repair after orphan pending sidecar
T=$SMOKE_ROOT/t6a && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
# Simulate orphan pending: create pending-<runid> with no staging dir or sentinel
cp "$T/.harness/installed-manifest.json" "$T/.harness/installed-manifest.json.pending-99999-orphan"
run "6a-state-repair-orphan" 1 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py state repair"

# 6b reinstall after uninstall
T=$SMOKE_ROOT/t6b && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py uninstall --target $T --select 1,2,3,4,5 --remove-install-state >/dev/null 2>&1
cd - >/dev/null
run "6b-reinstall-after-uninstall" 0 "$HARNESS init --target $T --profile generic --adapter roo"

# 6c invalid profile name
T=$SMOKE_ROOT/t6c && mkdir -p $T
run "6c-bad-profile" 1 "$HARNESS init --target $T --profile no-such-profile --adapter roo"

# 6d invalid adapter
T=$SMOKE_ROOT/t6d && mkdir -p $T
run "6d-bad-adapter" 1 "$HARNESS init --target $T --profile generic --adapter no-such-adapter"

# 6e check on uninstalled target
T=$SMOKE_ROOT/t6e && mkdir -p $T
run "6e-check-no-install" 1 "$HARNESS check --target $T"

# 6f progress quartile boundary check (mid-stage tick)
T=$SMOKE_ROOT/t6f && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo 2>/tmp/v098-smoke/6f-stderr.txt 1>/dev/null
run "6f-init-progress-throttle" 0 "true"  # no-op runner; we assert lines below
assert_contains "6f-quartile-25" "/tmp/v098-smoke/6f-stderr.txt" "applying atomic batch"
assert_contains "6f-final-tick" "/tmp/v098-smoke/6f-stderr.txt" "finalizing"

# 6g release-check with --expected-version (should fail on dev source)
run "6g-release-check-expected" 1 "$HARNESS release-check --expected-version v0.9.8"

# 6j phase verb subcommand discovery
T=$SMOKE_ROOT/t6j && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
run "6j-phase-set-help" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py phase set --help"
run "6k-phase-approve-help" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py phase approve --help"

# 6l simulated stale staging (single — N==1 path)
T=$SMOKE_ROOT/t6l && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
mkdir -p "$T/.harness/.staging-77777-single"
touch "$T/.harness/.staging-77777-single.journal.jsonl"
touch -t $(date -v-2H +%Y%m%d%H%M 2>/dev/null || date -d "2 hours ago" +%Y%m%d%H%M) "$T/.harness/.staging-77777-single"
run "6l-check-single-stale" 0 "cd $T && PYTHONPATH=$T/scripts python3 $T/scripts/harness.py check"
assert_contains "6l-single-format" "$SMOKE_ROOT/6l-check-single-stale.stdout" "중단된 설치 감지 (runid=77777-single"
# Must NOT use the N>=2 summary format
if ! grep -q "all runids" "$SMOKE_ROOT/6l-check-single-stale.stdout"; then
    PASS=$((PASS+1)); echo "PASS [6l-no-summary-prefix]"
else
    FAIL=$((FAIL+1)); echo "FAIL [6l-no-summary-prefix]"
fi

# 6m upgrade with explicit version flag
T=$SMOKE_ROOT/t6m && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
run "6m-upgrade-version-flag" 0 "$HARNESS --version v0.9.8 upgrade --target $T"

# 6n upgrade --force on locally-modified file
T=$SMOKE_ROOT/t6n && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
# Tamper with one harness-owned file
echo "// local mod" >> "$T/scripts/harness.py"
run "6n-upgrade-force" 0 "$HARNESS upgrade --target $T --force"

# 6o upgrade WITHOUT --force on locally-modified file (must produce conflicts)
T=$SMOKE_ROOT/t6o && mkdir -p $T
$HARNESS init --target $T --profile generic --adapter roo >/dev/null 2>&1
echo "// local mod" >> "$T/scripts/harness.py"
# v0.9.12: harness-owned local-mod no longer blocks upgrade with conflict;
# user bytes are backed up to .harness/conflicts/<path>.user-backup-<runid>
# and the upgrade proceeds.
run "6o-upgrade-overwrites-local-mod" 0 "$HARNESS upgrade --target $T"
assert_contains "6o-stdout-summary" "$SMOKE_ROOT/6o-upgrade-overwrites-local-mod.stdout" "upgraded harness"
# User backup should exist under .harness/conflicts/
find $T/.harness/conflicts -name "*.user-backup-*" 2>/dev/null | head -1 | grep -q user-backup && {
    PASS=$((PASS+1)); echo "PASS [6o-user-backup-created]"
} || {
    FAIL=$((FAIL+1)); echo "FAIL [6o-user-backup-created]"
}

# cleanup worktrees
git -C "$REPO" worktree remove "$WT" 2>/dev/null
git -C "$REPO" worktree remove "$WT7" 2>/dev/null
git -C "$REPO" worktree remove "$DEV_WT" 2>/dev/null

echo ""
echo "=============================================="
echo "RESULT"
echo "=============================================="
echo "PASS=$PASS"
echo "FAIL=$FAIL"
if [ $FAIL -gt 0 ]; then
    echo ""
    echo "Failures:"
    for f in "${FAILS[@]}"; do echo "  - $f"; done
    exit 1
fi
exit 0
