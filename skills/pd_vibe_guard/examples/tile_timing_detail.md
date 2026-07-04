# Example: Tile Timing Detail

## Task Header

```text
Target user: tile owner / group leader / timing review participant
Main judgement: what is the dominant timing risk for this tile and what evidence should be inspected next
Allowed input: current timing summary CSV/JSON and issue-cluster data
Allowed output: tile detail HTML
Forbidden expansions: 100+ corner full expansion as primary UI, automatic root-cause claims, all debug data on main page, ML clustering
```

## Requirement Grill

```markdown
Target user: tile owner / group leader
Review scenario: tile timing review / daily ECO follow-up
Main judgement: dominant issue cluster, responsible owner/group, critical evidence
Next action: inspect path report, assign owner, or prioritize ECO
Current data: timing metrics, path/corner summary, owner/group mapping, issue clusters
Minimum output: issue-cluster summary + risk/evidence table
Classification: CLEAR_FOR_PONYTAIL
```

## Requirement Ponytail

### KEEP

- issue cluster centered detail
- group/owner responsibility
- key corner/path summary
- evidence path links
- secondary detailed table

### CUT / DEFER

- 100+ corner full expansion as main page
- automatic root-cause claims without evidence
- all raw debug info on main page
- platform-level workflow

## Architecture Grill

Decision: SHRINK

Allowed architecture:

```text
summary data -> one tile detail HTML -> secondary evidence sections
```

Forbidden architecture:

```text
multi-role platform, state machine, interactive service
```

## Algorithm Grill

Decision: SHRINK_TO_RULE

Allowed logic:

- deterministic issue cluster using group + scenario + path type + endpoint pattern
- explicit unknown category
- evidence-first display

Forbidden logic:

- ML/embedding clustering in P0
- automatic root-cause judgement without expert validation

## Implementation Ponytail Contract

```markdown
Goal: Render tile detail around issue clusters, with secondary detail table.
Allowed input: current tile timing summary and issue cluster data
Allowed output: one tile HTML file
Forbidden expansions: full corner expansion as main UI, ML clustering, state machine, service
Validation command: run tile detail render command and inspect generated HTML
```
