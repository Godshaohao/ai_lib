---
name: implementation-ponytail
description: Use before implementing or reviewing AI-generated changes to a PD dashboard, timing/FCT/QoR tool, release monitor, library guard, or tile detail page.
---

# Implementation Ponytail Skill

## Purpose

Reject code overengineering and defensive implementation bloat.

Use only after the requirement has passed Requirement Ponytail, and any architecture/algorithm has passed its grill.

## First Principle

Implement the smallest code that satisfies the current coding contract without introducing future expansion cost.

## Lazy Implementation Ladder

Before writing new code, check in order:

1. Can we avoid implementing this at all?
2. Is the behavior already present in the codebase?
3. Can an existing function/module be reused?
4. Can the standard library solve it?
5. Can an already-installed dependency solve it?
6. Can a simple explicit rule solve it?
7. Can a small function solve it?
8. Only then add a minimal new module/class.

## What To Reject

Reject or remove:

- unused config fields
- speculative abstractions
- generic plugin systems
- broad exception swallowing
- defensive branches for impossible states
- new dependencies for small tasks
- class hierarchies for one implementation
- helper functions used once without clarity benefit
- refactors unrelated to the task
- schema changes not required by the task
- new CLI parameters not required by the task
- automatic compatibility layers without a real caller
- comments documenting future plans instead of current behavior

## Required Coding Contract

Before implementation, require:

```text
Goal:
Allowed input:
Allowed output:
Allowed files to edit:
Forbidden files/modules:
Forbidden expansions:
Validation command:
```

## Review Output Format

```markdown
## Implementation Ponytail Review

Task:
Contract satisfied: YES / NO

Keep:
- ...

Delete / avoid:
- ...

Simplify:
- ...

Boundary violations:
- ...

Minimal implementation plan:
1. ...
2. ...
3. ...

Validation:
- ...
```

## Coding Bias

- Prefer functions over classes unless state is real.
- Prefer explicit mappings over plugin registries.
- Prefer static HTML over servers.
- Prefer CSV/JSON over databases.
- Prefer deterministic rules over AI/ML logic.
- Prefer visible error messages over broad defensive recovery.
- Prefer one clear code path over generic branching.

## Examples

### Bad

```text
Create ReportEngine, ChartPlugin, DataSourceRegistry, WorkflowState, and ConfigManager for one FCT HTML page.
```

### Good

```text
read_csv() -> build_summary() -> render_html()
```

### Bad

```text
Add parser compatibility layer for future xlsx, csv, json, yaml, database, and API sources.
```

### Good

```text
Read current CSV input. Add xlsx only when actually requested and tested.
```
