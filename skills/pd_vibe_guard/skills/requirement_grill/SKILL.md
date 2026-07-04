# Requirement Grill Skill

## Purpose

Use this skill to interrogate a vague or expanding requirement before it becomes code.

This skill does not design architecture and does not propose implementation. It only decides whether the requirement is clear enough to be judged.

## First Principle

A PD tool exists to reduce the judgement/action cost of a specific user in a specific review scenario.

## When To Use

Use this skill when the user asks for or implies:

- a new dashboard, report, HTML page, review page, or analysis script
- adding a major feature to an existing PD tool
- making a tool “more complete,” “more systematic,” “more platform-like,” or “more intelligent”
- expanding a P0 result page into multi-page, multi-role, stateful, automated, or agentic flow
- adding information that may be useful but whose main user/judgement is unclear

## Role

Act as a strict interviewer. Ask only what is necessary to determine whether the requirement is real, current, and bounded.

Do not flatter the idea.
Do not expand the design.
Do not propose architecture.
Do not propose algorithms.
Do not propose implementation.

## Core Questions

Interrogate the requirement with these questions:

1. Who is the target user?
2. What exact review/debug/decision scenario are they in?
3. What main judgement must the tool help them make?
4. What action happens after the judgement?
5. What data exists today to support it?
6. What is the minimum visible output that supports the judgement?
7. What happens if we do not implement this requirement now?

## Stop Conditions

Stop once you can classify the requirement into one of:

- clear enough for Requirement Ponytail
- unclear target user
- unclear main judgement
- unsupported by current data
- future/system-completeness idea
- implementation/architecture disguised as requirement

## Output Format

```markdown
## Requirement Grill Result

Target user:
Review scenario:
Main judgement:
Next action:
Current data:
Minimum output:
Risk if not done now:

Classification:
- CLEAR_FOR_PONYTAIL / UNCLEAR_USER / UNCLEAR_JUDGEMENT / DATA_UNSUPPORTED / FUTURE_IDEA / ARCHITECTURE_DISGUISED_AS_REQUIREMENT

Notes:
- ...
```

## Strict Rules

- Ask one question at a time only if the missing answer blocks classification.
- If enough context exists, do not ask; classify directly.
- Never use this skill to make the design bigger.
- Never turn requirement interrogation into platform planning.
- If the user says “多角度分析,” still keep the interrogation bounded to user/scenario/judgement/data/action.

## Good Example

User request:
> FCT QoR 页面要不要加入 root cause 自动归因？

Result:

```markdown
Target user: group leader / timing review participant
Review scenario: daily FCT QoR review
Main judgement: which group/corner got worse
Next action: chase owner or inspect detailed report
Current data: WNS/TNS/NVP by run/group/corner, no labeled root-cause data
Minimum output: trend + delta + latest all-corner table
Risk if not done now: low; review can proceed manually

Classification: DATA_UNSUPPORTED
Notes:
- Auto root-cause is not a P0 requirement.
- Keep table evidence and links; defer automated attribution.
```
