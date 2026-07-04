---
name: pd_vibe_guard
description: Use for PD dashboard, timing/FCT/QoR analysis, release monitor, library guard, tile detail, or AI-assisted coding tasks that risk vague requirements, overengineering, premature architecture, unsupported algorithms, or bloated implementation. Routes to internal requirement_grill, requirement_ponytail, architecture_grill, algorithm_grill, and implementation_ponytail checks without exposing them as top-level global skills.
---

# PD Vibe Guard Orchestrator Skill

## Purpose

Coordinate lightweight anti-overengineering checks for PD vibe coding tasks.

This skill does not create a heavy workflow. It routes the task to the minimum necessary grill/ponytail check.

## First Principle

The goal is not to build a complete system. The goal is to reduce judgement/action cost for a specific PD user in a specific scenario.

## Trigger

Use this skill for:

- PD dashboard / HTML report / review page
- timing/FCT/QoR analysis script
- release monitor
- library catalog/scan/diff/release tool
- tile detail page
- AI-assisted code modification
- any request that risks overengineering

## Mandatory 5-Line Task Header

Every coding task must start with:

```text
Target user:
Main judgement:
Allowed input:
Allowed output:
Forbidden expansions:
```

If the user did not provide these, infer the smallest reasonable version from context and state it.

## Routing Logic

The child checks are bundled inside this skill, not installed as global top-level skills.
When a route below says to use a child check, read and apply the matching local file:

- `skills/requirement_grill/SKILL.md`
- `skills/requirement_ponytail/SKILL.md`
- `skills/architecture_grill/SKILL.md`
- `skills/algorithm_grill/SKILL.md`
- `skills/implementation_ponytail/SKILL.md`

### Step 1: Requirement Clarity
If target user, scenario, judgement, data, or next action is unclear:

Use `requirement_grill`.

### Step 2: Requirement Scope
If the requirement is clear but may be too broad:

Use `requirement_ponytail`.

### Step 3: Architecture Risk
If the proposal adds state machine, database, service, workflow, cache, plugin system, multi-role architecture, auto-refresh, or agent flow:

Use `architecture_grill`.

### Step 4: Algorithm Risk
If the proposal adds attribution, clustering, scoring, prediction, fuzzy matching, ranking, recommendation, anomaly detection, or AI inference:

Use `algorithm_grill`.

### Step 5: Implementation Risk
Before coding or reviewing AI code:

Use `implementation_ponytail`.

## Default Decisions

- If it does not serve the main judgement: CUT.
- If it may be useful later: DEFER.
- If current data cannot support it: DEFER.
- If a table/filter/sort/link can solve it: SHRINK.
- If P0 can ship without it: DEFER.
- If it requires new architecture before first useful page: DEFER.

## Output Format

```markdown
## PD Vibe Guard Result

Task header:
- Target user:
- Main judgement:
- Allowed input:
- Allowed output:
- Forbidden expansions:

Checks applied:
- Requirement Grill: YES/NO
- Requirement Ponytail: YES/NO
- Architecture Grill: YES/NO
- Algorithm Grill: YES/NO
- Implementation Ponytail: YES/NO

Decision:
- KEEP / CUT / DEFER / SHRINK

Current allowed scope:
- ...

Explicitly forbidden now:
- ...

Minimal next engineering action:
- ...
```

## Anti-Pattern Alerts

Flag these immediately:

- “顺手做完整一点”
- “未来可能需要”
- “先把架构搭好”
- “不如做成平台”
- “加个状态机更正规”
- “加个 agent 自动分析”
- “加个通用配置中心”
- “全部 corner/全部 parser result/全部文件都展示”
- “这个任务顺便重构一下”

## PD Project Defaults

### FCT QoR P0
Allowed:
- setup/hold default corner trend
- latest all-corner table
- group/run/corner delta
- evidence/report links

Forbidden:
- root-cause auto attribution
- all-corner trend explosion
- state machine
- agent review
- database

### Library Guard P0
Allowed:
- catalog
- scan summary
- diff summary
- file-diff entry
- release postcheck as separate flow
- effective source list if explicitly requested

Forbidden:
- full governance platform
- all parser result expansion as primary UI
- automatic deep diff for every file
- release lifecycle mixed into daily review

### Release Monitor P0
Allowed:
- overdue/near-due/current status
- owner/stage/tile matrix
- timeline
- latest.html + daily archive

Forbidden:
- approval workflow
- predictive model
- automatic scheduling platform

### Tile Timing Detail P0
Allowed:
- issue cluster summary
- group/owner/risk
- key corner/path evidence
- secondary detail table

Forbidden:
- 100+ corner full expansion as primary page
- automatic root cause without evidence
- all debug data on main page
