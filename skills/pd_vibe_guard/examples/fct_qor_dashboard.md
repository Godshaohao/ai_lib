# Example: FCT QoR Dashboard

## Task Header

```text
Target user: group leader / timing review participant
Main judgement: current run which group/corner setup/hold got worse
Allowed input: data/fct_qor_input.csv
Allowed output: reports/index.html
Forbidden expansions: state machine, multi-role platform, database, agent review, root-cause auto attribution, all-corner trend explosion
```

## Requirement Grill

```markdown
Target user: group leader / timing review participant
Review scenario: daily or per-run FCT QoR review
Main judgement: identify worsening group/corner/run
Next action: chase owner, inspect detailed report, or compare latest run
Current data: multi-run WNS/TNS/NVP, setup/hold selected corner, latest all-corner data
Minimum output: trend chart + latest sortable table + delta summary
Risk if not done now: review continues manually with Excel screenshots
Classification: CLEAR_FOR_PONYTAIL
```

## Requirement Ponytail

### KEEP

- setup default corner trend
- hold default corner trend
- WNS/TNS/NVP trend by run
- latest run all-corner sortable table
- current vs previous delta
- group filter/search if cheap

### CUT / DEFER

- automatic root-cause attribution
- all-corner trend explosion
- stage state machine
- agent review
- database
- multi-role platform
- predictive analysis

## Architecture Grill

Decision: SHRINK

Allowed architecture:

```text
CSV -> normalize -> summary -> static HTML
```

Forbidden architecture:

```text
service/API/database/state machine/plugin chart engine
```

## Algorithm Grill

Decision: SHRINK_TO_RULE

Allowed logic:

- deterministic corner matching
- group by run/group/corner
- delta calculation
- simple thresholds if explicitly configured

Forbidden logic:

- root-cause classifier
- ML clustering
- prediction
- AI judgement claims

## Implementation Ponytail Contract

```markdown
Goal: Generate one FCT QoR HTML report showing setup/hold trends and latest all-corner table.
Allowed input: data/fct_qor_input.csv
Allowed output: reports/index.html
Files allowed to edit: scripts/render_fct_qor.py, templates/fct_qor.html if already exists
Files forbidden: parser modules not directly related, unrelated config, generated HTML as source of truth
Forbidden expansions: state machine, database, agent workflow, all-corner trend explosion, root-cause automation
Validation command: python scripts/render_fct_qor.py --input data/fct_qor_input.csv --out reports/index.html
```
