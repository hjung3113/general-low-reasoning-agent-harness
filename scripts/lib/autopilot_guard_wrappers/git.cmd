@echo off
REM git.cmd — Windows deny shim wrapper for git network subcommands (§5.2). PATH-prepended by autopilot.
REM network_guard_posture: windows_audit_guard_degraded
REM Denied subcommands: push, pull, fetch, clone, remote update, submodule update --remote
REM Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §5.2
REM
REM NOTE: setlocal enabledelayedexpansion is REQUIRED because inside a parenthesized
REM if-block cmd.exe expands %ERRORLEVEL% at parse time (before findstr runs), so
REM %ERRORLEVEL% always reads the outer scope value regardless of what findstr returned.
REM Using !ERRORLEVEL! with delayed expansion reads it at execution time. This is the
REM classic cmd.exe parenthesized-block pitfall — do NOT revert to %ERRORLEVEL% here.
setlocal enabledelayedexpansion

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
            REM Check for --remote anywhere in remaining args.
            REM P4-P2-3 fix: use /c:"--remote" for literal-string match.
            REM The prior form used backslash escapes interpreted as character-class
            REM regex by findstr and never matched "--remote". /c: forces literal match.
            REM !ERRORLEVEL! (not %ERRORLEVEL%) is required here because we are
            REM inside a parenthesized block — see banner comment above.
            echo %* | findstr /i /c:"--remote" >nul 2>&1
            if !ERRORLEVEL!==0 goto :denied_sub
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
