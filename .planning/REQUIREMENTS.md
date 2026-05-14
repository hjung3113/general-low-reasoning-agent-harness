# REQUIREMENTS - General Harness

## REQ-core-protocol

The harness must preserve `discuss -> plan -> execute -> done`, durable planning memory, active checkpoints, approval-gated execute, and verification evidence.

## REQ-adapter-compatibility

The harness must support core-only, Roo-only, OpenCode-only, and Roo+OpenCode target installs.

## REQ-skill-plugins

The harness must install reusable workflow skills as composable plugins. Skills must be selected according to the request and repository evidence, not by hard-coded technology presets.

## REQ-portability

Core files must not assume a programming language, database, test framework, deployment target, or project domain.

## REQ-release-verification

Before push, run unit tests, source check, and target install/check smoke tests for the supported adapter matrix.

