---
name: test-generator
description: Generate, improve, and validate unit tests for functions, modules, or code snippets. Use when the user asks to write missing tests, strengthen weak tests, add edge-case coverage, or verify test completeness for existing code in the project's language and framework.
---

# Test Generator

## Overview

Generate structured, readable, and self-contained unit tests for existing code. Preserve project conventions and focus only on test-related changes unless the user explicitly requests broader edits.

## Workflow

1. Analyze the provided function, module, or snippet to infer behavior, side effects, and dependencies.
2. Identify normal cases, edge cases, and boundary conditions before writing tests.
3. Detect the current test framework and style from the repository when possible.
4. Generate test cases with clear, consistent naming that communicates intent.
5. Keep tests self-contained and independently runnable.
6. Add setup/teardown and mocks only when they materially improve correctness.
7. Avoid modifying unrelated production code; restrict edits to test files unless explicitly requested.
8. Validate tests with the smallest relevant test command first, then expand if needed.

## Output Requirements

- Match the language and test framework used by the codebase.
- Cover typical behavior plus meaningful edge cases.
- Keep assertions specific and deterministic.
- Prefer table-driven or parameterized patterns when they improve readability.
- Include minimal but sufficient fixtures/mocks.
- Keep test files clean, idiomatic, and easy to maintain.

## Inputs To Gather

- Target function/module path or code snippet.
- Programming language and testing framework.
- Related modules or collaborators that affect behavior.
- Project style conventions (naming, formatting, organization).
- Coverage expectations from the user or project.

Use [test-generation-resources.md](references/test-generation-resources.md) for a compact checklist when requirements are incomplete.

## Validation Notes

- If tests cannot be run, state that clearly and explain why.
- Report what was validated and what remains unverified.
