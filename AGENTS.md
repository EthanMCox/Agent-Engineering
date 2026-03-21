# AGENTS.md

This file defines default operating rules for any coding/research agent working in this repository.

## Core Principles
- Prioritize correctness, safety, and user intent over speed.
- Make the smallest effective change that solves the requested problem.
- Prefer deterministic, reproducible workflows.
- Be explicit about assumptions, constraints, and uncertainty.
- Never fabricate results, logs, test outcomes, or file changes.

## Collaboration Defaults
- Confirm task understanding before major work when requirements are ambiguous.
- Share short progress updates during longer tasks.
- Surface tradeoffs early when multiple valid approaches exist.
- Preserve existing project conventions unless asked to refactor.
- Keep explanations concise and actionable.

## Planning and Execution
- Inspect relevant files before editing.
- For non-trivial tasks, create a brief plan and execute step by step.
- Validate changes with targeted checks/tests whenever possible.
- If blocked, report the blocker and the next best options.
- Finish with a summary of what changed, why, and how it was verified.

## Directory Scope
- Default working root is the CS 301R Agent Engineering base directory.
- Perform work in only one subdirectory at a time unless the user explicitly requests cross-directory work.
- Do not switch subdirectories mid-task without clear user direction.
- If the intended working subdirectory is unclear, pause and ask the user to confirm before proceeding.

## Editing Rules
- Do not perform unrelated refactors.
- Do not rename/move files unless necessary for the requested task.
- Maintain backward compatibility unless a breaking change is explicitly requested.
- Add comments only when they materially improve maintainability.
- Keep diffs focused and easy to review.

## Safety and Git Hygiene
- Agents must not create commits, amend commits, rebase, merge, push, pull, stash, checkout, cherry-pick, reset, or otherwise perform Git operations.
- Only the user may run Git commands or change repository history/state.
- Never use destructive commands (for example `git reset --hard`, `git clean -fd`) unless explicitly requested.
- Do not revert or overwrite user-authored local changes that are outside the task scope.
- If unexpected repository changes appear, pause and ask for direction.
- Prefer non-interactive commands and scripts.
- Run tests/lint only within the intended project scope.

## Validation and Quality
- Run the smallest meaningful validation first, then expand as needed.
- If full validation cannot be run, state exactly what was and was not validated.
- Treat warnings as potential issues; do not ignore them silently.
- Verify user-visible behavior, not just type/check success.

## Communication Requirements
- State assumptions when proceeding without clarification.
- Provide file references for significant changes.
- When something cannot be completed, explain why and provide concrete next steps.
- Keep output structured: outcome first, then key details.

## Security and Privacy
- Never expose secrets, API keys, tokens, or credentials in outputs.
- Avoid logging sensitive data.
- Prefer least-privilege operations.
- Flag security-sensitive changes explicitly (auth, encryption, permissions, data access).

## Windows-Specific Guidance
- Use PowerShell-compatible commands by default.
- Use Windows path conventions (for example `C:\path\to\file`) and quote paths with spaces.
- Prefer `Get-ChildItem`, `Get-Content`, `Select-String`, and `Set-Content` over Unix-only equivalents when portability matters.
- Use `rg` when available for fast search; fall back to PowerShell alternatives when not.
- Be aware of file locking behavior on Windows; stop processes before editing locked files.
- Preserve line endings expected by the repo (`LF`/`CRLF`) and avoid accidental mass EOL changes.
- Use commands that work in non-interactive PowerShell sessions.
- When invoking scripts, prefer explicit forms like `python .\script.py` or `.\script.ps1`.
- Document any step that requires Administrator privileges.

## Definition of Done
- Requested change is implemented.
- Relevant validations/checks were run (or limitations clearly stated).
- Diff is scoped to the task.
- Handoff summary is clear enough for another contributor to continue immediately.
