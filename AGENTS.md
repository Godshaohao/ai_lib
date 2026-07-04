# AGENTS.md - PD Vibe Guard Negative Constraints

This file provides stable project constraints for AI coding agents.

## Core Principle

This project optimizes for review usefulness and decision/action cost reduction, not system completeness.

A valid change must help a specific user in a specific review scenario make a specific judgement or take a specific action faster.

## Global Negative Constraints

- Do not add workflow/state machine unless explicitly requested.
- Do not add a database unless explicitly requested.
- Do not add a multi-role platform unless explicitly requested.
- Do not add agent workflow unless explicitly requested.
- Do not add historical archive unless explicitly requested.
- Do not add generic plugin systems unless explicitly requested.
- Do not add future-proof abstractions.
- Do not add unused configuration options.
- Do not add new dependencies unless there is no simple standard-library or existing-dependency solution.
- Do not refactor unrelated modules.
- Do not rewrite existing working code for style reasons only.
- Do not change CLI parameters unless the task explicitly requires it.
- Do not change input/output schema unless explicitly required.
- Do not change parser/schema during UI/report tasks.
- Do not change UI/template/CSS during parser/extraction tasks.
- Do not modify generated reports as the source of truth. Change the generator/template instead.
- Do not implement backlog, future ideas, or parking-lot ideas.

## P0 Rules

For P0 tasks:

- Produce the smallest useful result page or script.
- Prefer one input, one output, one main view.
- Prefer static HTML over services.
- Prefer CSV/JSON over database.
- Prefer explicit rules over intelligent inference.
- Prefer tables/sorting/filtering over automatic root-cause claims.
- Prefer visible evidence links over hidden magic logic.

## Required Before Coding

Before coding, restate:

```text
Target user:
Main judgement:
Allowed input:
Allowed output:
Forbidden expansions:
```

If these are missing, ask for them or infer the smallest reasonable version and state assumptions.

## Required After Coding

After coding, list:

```text
Changed files:
Changed functions/modules:
Unchanged boundaries:
Validation command:
Known limitations:
```

## PD Tool Bias

For PD review tools:

- Main page should answer the review question first.
- Evidence/debug details should be secondary.
- Long command examples should not dominate the main page.
- Leadership/group-owner views should not be mixed with raw parser/debug views.
- Raw parser results are evidence, not the primary product view.
- Release actions should not be mixed into daily scan/diff review unless explicitly requested.
