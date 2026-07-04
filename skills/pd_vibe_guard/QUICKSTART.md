# Quickstart

## 1. Put AGENTS.md in your project root

Copy `AGENTS.md` into the root of your AI coding project.

It tells the coding agent what not to do:

- no unrelated refactor
- no future-proof abstractions
- no parser/schema changes during UI tasks
- no UI/template changes during parser tasks
- no state machine/database/agent workflow unless explicitly requested

## 2. Add the skills to your AI tool

Copy the folders under `skills/` into your tool's skill/command directory.

Minimum useful set:

```text
requirement_grill
requirement_ponytail
implementation_ponytail
```

Full set:

```text
requirement_grill
requirement_ponytail
architecture_grill
algorithm_grill
implementation_ponytail
pd_vibe_guard
```

## 3. Start every coding request with 5 lines

```text
Target user:
Main judgement:
Allowed input:
Allowed output:
Forbidden expansions:
```

## 4. Recommended prompt

```text
Use PD Vibe Guard.
First check whether this task is requirement overdesign, architecture overdesign, algorithm overdesign, or implementation overdesign.
Only allow the smallest current-version scope.
Do not propose future platform features.
Then provide a minimal coding contract.
```

## 5. For AI-generated code review

```text
Use Implementation Ponytail to review this diff.
Find unnecessary abstractions, unused config, unrelated refactors, defensive branches, new dependencies, schema changes, and boundary violations.
Return Keep/Delete/Simplify/Boundary violations/Validation.
```

## 6. For requirement review

```text
Use Requirement Grill and Requirement Ponytail.
Only decide whether this requirement enters P0.
Do not propose architecture or implementation.
Return KEEP/CUT/DEFER.
```
