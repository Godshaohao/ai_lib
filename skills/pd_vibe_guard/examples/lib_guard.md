# Example: lib_guard

## Task Header: Scan Page

```text
Target user: IP user / library manager
Main judgement: whether this library version is structurally complete enough to enter diff/review
Allowed input: catalog + scan digest/manifest
Allowed output: scan HTML summary
Forbidden expansions: release lifecycle, governance platform, full parser result dump as primary UI, automatic deep diff of every file
```

## Requirement Grill

```markdown
Target user: IP user / library manager
Review scenario: after a new raw/effective library version is scanned
Main judgement: is the version structurally complete, and what should be checked next?
Next action: run diff, run file-diff, ask vendor, or block release
Current data: catalog, scan digest, manifest, parser status, file type summary
Minimum output: delivery brief, view coverage, evidence, manual check/next command
Classification: CLEAR_FOR_PONYTAIL
```

## Requirement Ponytail

### KEEP

- library/version identity
- delivery brief
- file/view coverage
- found/missing summary
- parser status summary
- evidence links
- next recommended command

### CUT / DEFER

- full parser result as primary UI
- all files auto deep diff
- release lifecycle mixed into scan page
- governance state machine
- database
- multi-role platform

## Architecture Grill

Decision: SHRINK

Allowed architecture:

```text
catalog -> scan digest -> static HTML
```

Keep scan/diff/release separate:

- scan answers completeness
- diff answers change risk
- file-diff answers evidence-level file change
- release answers publish correctness

## Algorithm Grill

Decision: SHRINK_TO_RULE

Allowed logic:

- deterministic file type classification
- explicit required/missing view rules
- parser status grouping

Forbidden logic:

- automatic semantic risk scoring without evidence
- vendor intent inference
- automatic release decision

## Implementation Ponytail Contract

```markdown
Goal: Improve scan HTML summary without changing parser/schema.
Allowed input: existing scan digest/manifest JSON
Allowed output: scan HTML
Files allowed to edit: html_report.py, product_theme.py or relevant template only
Files forbidden: parsers, CLI, catalog discovery, release code
Forbidden expansions: release workflow, state machine, database, deep diff automation
Validation command: run existing scan render command and open generated scan HTML
```
