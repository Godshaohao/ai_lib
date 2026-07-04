# Requirement Ponytail Skill

## Purpose

Reject over-designed requirements before coding.

This is the most important skill in the pack. It decides whether a requirement enters the current version.

## First Principle

A requirement is valid for the current version only if it directly lowers the judgement/action cost of the target user in the current scenario.

## When To Use

Use after Requirement Grill, or directly when a proposed requirement is already clear.

Use especially when a requirement sounds like:

- future completeness
- platformization
- generalized configuration
- multi-role expansion
- automatic intelligence
- state machine / lifecycle / workflow
- history/archive/refresh without proven use
- “顺手加一下”

## Decision Types

Return exactly one decision:

- KEEP: implement in current version
- CUT: remove from current version entirely
- DEFER: keep as idea, not current code

## Adversarial Tests

### 1. Future Test
Is this required only because it may be useful later?

If yes -> DEFER.

### 2. Completeness Test
Is this required only to make the system feel complete?

If yes -> CUT.

### 3. User Test
Can we name the user who benefits today?

If no -> CUT.

### 4. Judgement Test
Does it directly improve the main judgement?

If no -> CUT or DEFER.

### 5. Data Test
Can current input data support it reliably?

If no -> DEFER.

### 6. Delivery Test
Can P0 still ship without it?

If yes -> DEFER.

### 7. Cost Test
Will it delay the first useful result page?

If yes -> DEFER.

### 8. Manual Alternative Test
Can a simple table, sort, filter, link, or command example solve it for now?

If yes -> DEFER the complex requirement and use the manual alternative.

## Output Format

```markdown
## Requirement Ponytail Decision

Requirement:
Decision: KEEP / CUT / DEFER

Reason:
- ...

Minimum alternative:
- ...

Forbidden expansion:
- ...

Allowed current-version scope:
- ...
```

## Bias

Default to CUT or DEFER unless the requirement is directly tied to current user/judgement/data/action.

## Examples

### FCT QoR Root Cause

```markdown
Requirement: Add automatic root-cause classification.
Decision: DEFER
Reason:
- Current P0 judgement is which group/corner got worse.
- Current data has no validated root-cause labels.
- A sortable latest table plus evidence links is enough for first review.
Minimum alternative:
- Add delta columns and links to detailed evidence.
Forbidden expansion:
- Do not add ML/heuristic root-cause engine in P0.
Allowed current-version scope:
- Trend chart, delta table, all-corner latest table.
```

### Release Monitor Prediction

```markdown
Requirement: Predict future release delay using historical runtime model.
Decision: DEFER
Reason:
- Current judgement is who is late or near due.
- Prediction is not required to send reminders today.
Minimum alternative:
- Show due time, current status, owner, and overdue/near-due tag.
Forbidden expansion:
- Do not add predictive model or scheduler platform.
Allowed current-version scope:
- Static matrix and timeline.
```
