---
name: lecture-infra-selector
description: Select the best-fit agent infrastructure pattern from lecture 1a-3g memory, and always return lecture references (IDs + key files) for implementation follow-up.
---

# Lecture Infrastructure Selector

## Purpose

Map a requested capability to one or more proven infrastructure patterns from course lectures, then return implementation guidance with explicit lecture references.

## Source of Truth

- Machine-readable index: `final_project/docs/lecture_infrastructure_index.json`
- Human reference notes: `final_project/docs/lecture_infrastructure_memory.md`

Always prefer the JSON index for lookup and ranking.

## Input

Natural-language request describing desired agent behavior/capability (examples: "tool-calling scaffold", "MCP over sidecar", "memory-enabled interview coach", "jailbreak defenses").

## Output Contract (Required)

Return:

1. `Selected Pattern(s)`:
   - `pattern_id`
   - `name`
   - why this matches the request
2. `Implementation Guidance`:
   - concise wiring steps from `implementation_outline`
   - important anti-patterns to avoid
3. `Reference Lectures` (always required):
   - for each selected pattern, include every `lecture_ref` with:
     - `lecture_id`
     - `why_relevant`
     - `key_files`

If no exact pattern exists, return closest match(es), explicitly say it is approximate, and still include lecture references.

## Selection Heuristics

- Match user intent against: `intent`, `when_to_use`, and anti-pattern compatibility.
- Prefer smallest viable pattern set:
  - one pattern when sufficient,
  - multiple only when clearly compositional (for example RAG + tool calling + evaluation) or when requested by the user
- If two patterns are tied, prefer:
  - more recent lecture implementations,
  - patterns with concrete executable files over notes-only references.

## Maintenance Rules

When updating `lecture_infrastructure_index.json`:

- Every pattern entry must include non-empty `lecture_refs`.
- Every `lecture_ref` must include non-empty `lecture_id` and `key_files`.
- `key_files` must point to real repository-relative paths.
- Keep `pattern_id` stable once published; add new patterns instead of renaming existing IDs.

