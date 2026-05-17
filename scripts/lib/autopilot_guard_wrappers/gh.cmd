@echo off
REM gh.cmd — Windows deny shim wrapper for gh (GitHub CLI) (§5.2). PATH-prepended by autopilot.
REM network_guard_posture: windows_audit_guard_degraded
REM Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §5.2

if "%HARNESS_AUTOPILOT_NETWORK%"=="deny" (
    echo refused: gh (autopilot deny-list; windows degraded posture) 1>&2
    exit /b 4
)
REM Pass-through: find real gh in PATH, skipping this wrapper
for /f "delims=" %%i in ('where gh ^| findstr /v /i "autopilot_guard_wrappers"') do (
    "%%i" %*
    exit /b %ERRORLEVEL%
)
echo error: real gh not found in PATH 1>&2
exit /b 127
