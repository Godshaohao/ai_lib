# Prompt Snippets

## Requirement Grill Prompt

```text
Use Requirement Grill.
Interrogate this requirement only to decide whether it is clear enough to enter P0.
Do not propose architecture.
Do not propose implementation.
Do not expand scope.
Classify it as CLEAR_FOR_PONYTAIL / UNCLEAR_USER / UNCLEAR_JUDGEMENT / DATA_UNSUPPORTED / FUTURE_IDEA / ARCHITECTURE_DISGUISED_AS_REQUIREMENT.

Requirement:
<...>
```

## Requirement Ponytail Prompt

```text
Use Requirement Ponytail.
Decide whether this requirement is KEEP / CUT / DEFER for the current version.
Apply Future Test, Completeness Test, User Test, Judgement Test, Data Test, Delivery Test, Cost Test, Manual Alternative Test.
Return only: decision, reason, minimum alternative, forbidden expansion, allowed current-version scope.

Requirement:
<...>
```

## Architecture Grill Prompt

```text
Use Architecture Grill.
This proposal adds architecture. Decide KEEP / CUT / DEFER / SHRINK.
Do not make the system bigger.
Compare against the simplest substitute: input file -> summary -> static HTML.

Proposed architecture:
<...>
```

## Algorithm Grill Prompt

```text
Use Algorithm Grill.
This proposal adds algorithmic/intelligent logic. Decide KEEP / CUT / DEFER / SHRINK_TO_RULE.
Compare against table/sort/filter/rule/evidence-link baseline.

Proposed algorithm:
<...>
```

## Implementation Ponytail Prompt

```text
Use Implementation Ponytail.
Review this implementation plan/diff for code overengineering.
Find unused config, speculative abstraction, generic frameworks, unrelated refactor, schema/CLI boundary violations, new dependencies, defensive code, and one-use helper/class bloat.
Return Keep / Delete or avoid / Simplify / Boundary violations / Minimal implementation plan / Validation.

Plan or diff:
<...>
```

## PD Vibe Guard Prompt

```text
Use PD Vibe Guard.
Task header:
Target user: <...>
Main judgement: <...>
Allowed input: <...>
Allowed output: <...>
Forbidden expansions: <...>

Route this through the minimum necessary checks:
- Requirement Grill if unclear
- Requirement Ponytail if scope may be broad
- Architecture Grill if architecture is proposed
- Algorithm Grill if algorithmic logic is proposed
- Implementation Ponytail before coding

Return current allowed scope, explicitly forbidden scope, and the minimal next engineering action.
```
