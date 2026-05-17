# autopilot_guard.ps1 — Windows degraded network deny-list (§5.2)
# Sourced via $PROFILE when HARNESS_AUTOPILOT_NETWORK=deny.
# Best-effort: bypassable by absolute paths or language runtimes.
# For hard isolation use Linux container or WSL.
#
# Supported: PowerShell 5.1+ (Windows 10/11 default) and PowerShell 7+
#
# network_guard_posture: windows_audit_guard_degraded
# Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §5.2

if ($env:HARNESS_AUTOPILOT_NETWORK -eq "deny") {
    function _Harness_Deny([string]$cmd, [string[]]$args) {
        $cmdLine = "$cmd " + ($args -join ' ')
        if ($cmdLine.Length -gt 512) { $cmdLine = $cmdLine.Substring(0, 512) }
        $auditPath = Join-Path (Get-Location) ".harness/audit.log"
        # Best-effort audit append — PS 5.1 compatible.
        # [System.Text.UTF8Encoding]($false) = UTF-8 without BOM, works on PS 5.1+.
        # [DateTime]::UtcNow = UTC timestamp, works on PS 5.1+ (no PS 7.1-only flags).
        $entry = @{
            verb = "autopilot.network.deny"
            command_label = $cmd
            command = $cmdLine
            cwd = (Get-Location).Path
            at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
            network_guard_posture = "windows_audit_guard_degraded"
        } | ConvertTo-Json -Compress
        try {
            [System.IO.File]::AppendAllText($auditPath, $entry + "`n", (New-Object System.Text.UTF8Encoding($false)))
        } catch {}
        Write-Error "refused: $cmd (autopilot deny-list; windows degraded posture)"
        exit 4
    }

    function curl  { _Harness_Deny "curl"  $args }
    function wget  { _Harness_Deny "wget"  $args }
    function nc    { _Harness_Deny "nc"    $args }
    function ssh   { _Harness_Deny "ssh"   $args }
    function scp   { _Harness_Deny "scp"   $args }
    function rsync { _Harness_Deny "rsync" $args }
    function gh    { _Harness_Deny "gh"    $args }
    function glab  { _Harness_Deny "glab"  $args }

    # git subcommand filter
    $_origGit = Get-Command git -CommandType Application -ErrorAction SilentlyContinue
    if ($_origGit) {
        function git {
            $sub = if ($args.Count -ge 1) { $args[0] } else { "" }
            $deniedSubs = @("push", "pull", "fetch", "clone")
            if ($sub -in $deniedSubs) {
                _Harness_Deny ("git " + $sub) $args[1..($args.Count-1)]
            } elseif ($sub -eq "remote" -and $args.Count -ge 2 -and $args[1] -eq "update") {
                _Harness_Deny "git remote update" $args[2..($args.Count-1)]
            } elseif ($sub -eq "submodule" -and $args.Count -ge 4 -and $args[1] -eq "update" -and $args -contains "--remote") {
                _Harness_Deny "git submodule update --remote" $args[2..($args.Count-1)]
            } else {
                & $_origGit.Path @args
            }
        }
    }
}
