@echo off
REM curl.cmd — Windows deny shim wrapper for curl (§5.2). PATH-prepended by autopilot.
REM network_guard_posture: windows_audit_guard_degraded
REM Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §5.2

if "%HARNESS_AUTOPILOT_NETWORK%"=="deny" (
    echo refused: curl (autopilot deny-list; windows degraded posture) 1>&2
    exit /b 4
)
REM Pass-through: find real curl in PATH, skipping this wrapper
for /f "delims=" %%i in ('where curl ^| findstr /v /i "autopilot_guard_wrappers"') do (
    "%%i" %*
    exit /b %ERRORLEVEL%
)
echo error: real curl not found in PATH 1>&2
exit /b 127
