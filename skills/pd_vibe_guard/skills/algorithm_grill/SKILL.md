# Algorithm Grill Skill

## Purpose

Interrogate proposed algorithms before implementation.

This skill prevents premature “intelligence”: root-cause attribution, clustering, scoring, prediction, fuzzy matching, ranking, anomaly detection, or recommendation logic that cannot yet be validated.

## First Principle

An algorithm is justified only if it improves a real judgement more reliably than simple rules, sorting, filtering, or evidence links.

## When To Use

Use when the proposal includes or implies:

- automatic root-cause analysis
- issue clustering
- risk scoring
- anomaly detection
- fuzzy matching
- ranking/recommendation
- prediction/forecasting
- AI classification
- heuristic inference that affects user trust
- data extraction from ambiguous semi-structured reports

## Algorithm Adversarial Questions

1. What judgement does this algorithm improve?
2. What is the simplest rule-based baseline?
3. Can sorting/filtering/table grouping solve 80% of the problem?
4. Is the algorithm output explainable to PD users?
5. Do we have labeled examples or expert-validated truth?
6. What happens if the algorithm is wrong?
7. Can the user verify the result from evidence links?
8. Is the current data stable enough for this algorithm?
9. Is the algorithm needed for P0, or only for future efficiency?
10. Can the algorithm be replaced by explicit columns and manual review for now?

## Decisions

- KEEP: algorithm is necessary and verifiable now
- CUT: algorithm should not exist
- DEFER: algorithm may be useful later but not current version
- SHRINK_TO_RULE: replace with simple explicit rule/table/sort/filter

## Output Format

```markdown
## Algorithm Grill Result

Proposed algorithm:
Decision: KEEP / CUT / DEFER / SHRINK_TO_RULE

Main judgement affected:
Baseline rule/table alternative:
Validation evidence:
Failure risk:
Explainability:
Allowed current logic:
Forbidden algorithmic expansion:
```

## Preferred Baselines

Before adding algorithmic logic, prefer:

- explicit keyword rules
- deterministic regex extraction
- group-by summaries
- sortable tables
- thresholds configured in plain text
- evidence links
- manual owner selection
- “unknown” category instead of forced inference

## Examples

### Tile Timing Issue Cluster

```markdown
Proposed algorithm: Use smart clustering for timing issues.
Decision: SHRINK_TO_RULE
Main judgement affected: identify dominant timing risk per tile
Baseline rule/table alternative: group by scenario + path_type + endpoint pattern + issue keyword
Validation evidence: no labeled clusters yet
Failure risk: wrong clusters reduce trust
Explainability: deterministic grouping is easier to inspect
Allowed current logic: rule-based issue cluster with evidence table
Forbidden algorithmic expansion: ML/embedding clustering in P0
```

### FCT Root Cause Auto Attribution

```markdown
Proposed algorithm: Automatically classify QoR regression root cause.
Decision: DEFER
Main judgement affected: decide which owner to chase
Baseline rule/table alternative: show group/corner/run delta, top worsening paths, report links
Validation evidence: no trusted root-cause labels
Failure risk: false attribution can mislead review
Explainability: current data insufficient
Allowed current logic: delta sorting and hotspot table
Forbidden algorithmic expansion: automatic root-cause claims
```
