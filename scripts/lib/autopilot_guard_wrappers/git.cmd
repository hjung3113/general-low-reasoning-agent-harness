@echo off
REM git.cmd — Windows deny shim wrapper for git network subcommands (§5.2). PATH-prepended by autopilot.
REM network_guard_posture: windows_audit_guard_degraded
REM Denied subcommands: push, pull, fetch, clone, remote update, submodule update --remote
REM Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §5.2

if "%HARNESS_AUTOPILOT_NETWORK%"=="deny" (
    REM Check first argument (subcommand)
    if "%1"=="push"  goto :denied_sub
    if "%1"=="pull"  goto :denied_sub
    if "%1"=="fetch" goto :denied_sub
    if "%1"=="clone" goto :denied_sub
    if "%1"=="remote" (
        if "%2"=="update" goto :denied_sub
    )
    if "%1"=="submodule" (
        if "%2"=="update" (
            REM Check for --remote anywhere in remaining args
            echo %* | findstr /i "\-\-remote" >nul 2>&1
            if %ERRORLEVEL%==0 goto :denied_sub
        )
    )
)
REM Pass-through: find real git in PATH, skipping this wrapper
for /f "delims=" %%i in ('where git ^| findstr /v /i "autopilot_guard_wrappers"') do (
    "%%i" %*
    exit /b %ERRORLEVEL%
)
echo error: real git not found in PATH 1>&2
exit /b 127

:denied_sub
echo refused: git %1 (autopilot deny-list; windows degraded posture) 1>&2
exit /b 4
