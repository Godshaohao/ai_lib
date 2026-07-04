# AI Coding Contract Template

Give this to a coding agent after the requirement has passed the grills.

## Contract

```markdown
# Coding Contract

## Goal
<one sentence only>

## Target User
<who uses the output>

## Main Judgement
<what judgement this output supports>

## Allowed Input
- <file/path/source>

## Allowed Output
- <file/path/report>

## Files Allowed To Edit
- <file 1>
- <file 2>

## Files/Modules Forbidden To Edit
- <parser/schema/template/etc>

## Required Behavior
- <behavior 1>
- <behavior 2>

## Forbidden Expansions
- no state machine
- no database
- no multi-role platform
- no agent workflow
- no unrelated refactor
- no schema change unless listed above
- no parser change unless listed above
- no unused config

## Validation Command
<command>

## Response Required After Change
List:
- changed files
- changed functions/modules
- unchanged boundaries
- validation command
- known limitations
```
