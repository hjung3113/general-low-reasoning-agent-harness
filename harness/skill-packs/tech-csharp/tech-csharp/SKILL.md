---
name: tech-csharp
description: Use when C#/.NET is confirmed. Keeps solution, project, build, test, and version assumptions explicit.
---

# Tech CSharp

Use only after C# or .NET is confirmed.

## Evidence

Look for `.sln`, `.csproj`, `global.json`, C# source files, test projects, CI commands, or user confirmation.

## Rules

- Do not assume .NET version, test framework, architecture, ORM, or database.
- Read `global.json` and project files before choosing commands.
- Keep public contracts and nullable annotations consistent with the repository.
- Run the repository's build and test commands before done.

## Verification

Use existing commands such as `dotnet test`, `dotnet build`, or solution-specific scripts.

