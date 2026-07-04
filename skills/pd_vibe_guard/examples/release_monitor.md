# Example: Release Monitor

## Task Header

```text
Target user: project owner / group leader
Main judgement: who is overdue, who is near due, which owner/stage needs action
Allowed input: tile list, owner list, milestone/rule CSV/TOML, filesystem status
Allowed output: reports/index.html, latest.html, daily_release_YYYYMMDD.html
Forbidden expansions: approval workflow, prediction model, automatic scheduling platform, multi-layer permission system
```

## Requirement Grill

```markdown
Target user: project owner / group leader
Review scenario: periodic release status check
Main judgement: identify overdue/near-due/todo tiles and owners
Next action: chase owner, update milestone, or inspect path
Current data: release rules, tile list, owner list, milestone table, filesystem status
Minimum output: matrix + timeline + owner summary
Classification: CLEAR_FOR_PONYTAIL
```

## Requirement Ponytail

### KEEP

- overdue
- near due within configured window
- owner/stage/tile status
- daily archive
- latest.html pointer
- summary reminders

### CUT / DEFER

- approval workflow
- predictive delay model
- auto rescheduling platform
- permissions system
- complex task management

## Architecture Grill

Decision: KEEP for daily static archive + latest.html; CUT for service/database.

Allowed architecture:

```text
rules + status scan -> daily static HTML -> latest.html
```

Forbidden architecture:

```text
web service, database scheduler, approval system
```

## Implementation Ponytail Contract

```markdown
Goal: Generate static release status page and latest pointer.
Allowed input: configured rule/status files
Allowed output: reports/index.html or daily_release_*.html + latest.html
Forbidden expansions: service, database, prediction, approval flow
Validation command: run release monitor render command and inspect generated HTML
```
