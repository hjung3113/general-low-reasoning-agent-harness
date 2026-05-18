# test_autopilot_guard_deny.ps1 — deny-shim fuzz for autopilot_guard.ps1
#
# Exercises the deny path for both simple commands (curl) and git subcommands
# (git push). Asserts:
#   1. The shim exits with code 4.
#   2. An audit JSON-line row is written with verb = "autopilot.network.deny".
#
# Designed to run under PowerShell 5.1 (powershell.exe) and PowerShell 7+
# (pwsh). Works by dot-sourcing the guard script in a child process so that
# the define-and-exit flow matches production use.
#
# Usage:
#   powershell.exe -NoProfile -File scripts/tests/test_autopilot_guard_deny.ps1
#   pwsh          -NoProfile -File scripts/tests/test_autopilot_guard_deny.ps1
#
# Exit codes:
#   0 — all assertions passed
#   1 — at least one assertion failed

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Locate repo root (script is in scripts/tests/ — two levels up)
# ---------------------------------------------------------------------------
$RepoRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$GuardScript = Join-Path $RepoRoot "scripts\lib\autopilot_guard.ps1"

if (-not (Test-Path $GuardScript)) {
    Write-Error "Guard script not found: $GuardScript"
    exit 1
}

# ---------------------------------------------------------------------------
# Temp workspace — each test case gets its own .harness/ audit dir
# ---------------------------------------------------------------------------
$TmpBase = Join-Path ([System.IO.Path]::GetTempPath()) ("harness_ps_" + (Get-Random))
New-Item -ItemType Directory -Force -Path $TmpBase | Out-Null

function Remove-TmpBase {
    if (Test-Path $TmpBase) {
        Remove-Item -Recurse -Force $TmpBase -ErrorAction SilentlyContinue
    }
}

# Clean up on normal exit and on termination
Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Remove-TmpBase } | Out-Null

# ---------------------------------------------------------------------------
# Helper: run a single deny-case in an isolated child process
#
# Strategy: spin a child PowerShell process that:
#   1. Sets HARNESS_AUTOPILOT_NETWORK=deny.
#   2. Dot-sources the guard script (defines the shim functions).
#   3. Calls the shim (e.g. curl, or the git wrapper).
#   4. Exits — the guard shim itself calls exit 4 on deny.
#
# The child runs from a temp CWD that already has a .harness/ dir so the
# audit path is predictable (guard writes to (Get-Location)/.harness/audit.log).
# ---------------------------------------------------------------------------
function Invoke-DenyCase {
    param(
        [string]$Label,        # human-readable test name
        [string]$ShimCall,     # PS expression to invoke the shim, e.g. "curl http://x"
        [int]   $ExpectedExit = 4
    )

    # Each case uses a fresh CWD under TmpBase.
    $CaseDir    = Join-Path $TmpBase $Label
    $HarnessDir = Join-Path $CaseDir ".harness"
    $AuditFile  = Join-Path $HarnessDir "audit.log"
    New-Item -ItemType Directory -Force -Path $HarnessDir | Out-Null

    # Build the inline script block for the child process.
    # We use single-quoted heredoc to avoid escaping issues.
    # B3-Fix-4: set HARNESS_PROJECT_ROOT so _Harness_ResolveAuditPath finds the
    # correct audit.log even when $PSScriptRoot is the guard script's parent dir
    # (scripts/lib/) which has no .harness/ ancestor in this test temp tree.
    $inlineScript = @"
Set-Location '$CaseDir'
`$env:HARNESS_AUTOPILOT_NETWORK = 'deny'
`$env:HARNESS_PROJECT_ROOT = '$CaseDir'
. '$GuardScript'
$ShimCall
"@

    # Determine the PowerShell executable for child (same as host).
    # PS 5.1 host: $PSVersionTable.PSEdition = 'Desktop' → use powershell.exe
    # PS 7+  host: $PSVersionTable.PSEdition = 'Core'    → use pwsh
    if ($PSVersionTable.PSEdition -eq 'Core') {
        $psExe = 'pwsh'
    } else {
        $psExe = 'powershell.exe'
    }

    # Run the child. Capture stderr (Write-Error from _Harness_Deny) — we only
    # care about exit code and the audit file, so redirect stderr to stdout.
    & $psExe -NoProfile -Command $inlineScript 2>&1 | Out-Null
    $exitCode = $LASTEXITCODE

    $pass = $true

    # --- Assertion 1: exit code ---
    if ($exitCode -ne $ExpectedExit) {
        Write-Error "[$Label] FAIL: expected exit $ExpectedExit, got $exitCode"
        $pass = $false
    }

    # --- Assertion 2: audit row exists ---
    if (-not (Test-Path $AuditFile)) {
        Write-Error "[$Label] FAIL: audit file not found at $AuditFile"
        $pass = $false
    } else {
        $lines = Get-Content $AuditFile -Encoding UTF8 -ErrorAction SilentlyContinue
        if (-not $lines) {
            Write-Error "[$Label] FAIL: audit file is empty"
            $pass = $false
        } else {
            # Parse last non-empty JSON line.
            $row = $null
            foreach ($line in ($lines | Where-Object { $_.Trim() -ne '' })) {
                try {
                    $row = $line | ConvertFrom-Json
                } catch {
                    # skip non-JSON lines
                }
            }

            if ($null -eq $row) {
                Write-Error "[$Label] FAIL: no parseable JSON row in $AuditFile"
                $pass = $false
            } elseif ($row.verb -ne 'autopilot.network.deny') {
                Write-Error "[$Label] FAIL: expected verb 'autopilot.network.deny', got '$($row.verb)'"
                $pass = $false
            } else {
                Write-Host "[$Label] PASS: exit=$exitCode verb=$($row.verb)"
            }
        }
    }

    return $pass
}

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------
$allPass = $true

# Case 1: curl shim
$allPass = (Invoke-DenyCase -Label "curl_deny" -ShimCall "curl http://example.com") -and $allPass

# Case 2: wget shim
$allPass = (Invoke-DenyCase -Label "wget_deny" -ShimCall "wget http://example.com") -and $allPass

# Case 3: git push shim (git subcommand network deny)
# The git wrapper is only registered when git.exe is found on PATH; on Windows
# CI runners git is always present. If git is absent the function is not defined
# and the child will call the real git (which fails for other reasons, not exit 4).
# We therefore make this a best-effort case: skip assertion if git is absent.
$gitPresent = $null -ne (Get-Command git -CommandType Application -ErrorAction SilentlyContinue)
if ($gitPresent) {
    $allPass = (Invoke-DenyCase -Label "git_push_deny" -ShimCall "git push origin main") -and $allPass
} else {
    Write-Host "[git_push_deny] SKIP: git not found on PATH"
}

# Case 4: ssh shim
$allPass = (Invoke-DenyCase -Label "ssh_deny" -ShimCall "ssh user@host") -and $allPass

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
Remove-TmpBase

# ---------------------------------------------------------------------------
# Final verdict
# ---------------------------------------------------------------------------
if ($allPass) {
    Write-Host "All deny-shim assertions passed."
    exit 0
} else {
    Write-Error "One or more deny-shim assertions FAILED."
    exit 1
}
