# Task Header Template

Use this at the beginning of every PD vibe coding task.

```text
Target user:
Main judgement:
Allowed input:
Allowed output:
Forbidden expansions:
```

## Example: FCT QoR

```text
Target user: group leader / timing review participant
Main judgement: current run which group/corner setup/hold got worse
Allowed input: data/fct_qor_input.csv
Allowed output: reports/index.html
Forbidden expansions: state machine, multi-role platform, database, agent review, root-cause auto attribution, all-corner trend explosion
```

## Example: lib_guard Scan

```text
Target user: library manager / IP user
Main judgement: whether this library version is structurally complete enough to enter diff/review
Allowed input: catalog + scan manifest/digest
Allowed output: scan HTML summary
Forbidden expansions: release lifecycle, full parser result dump as primary UI, automatic deep diff of every file, governance platform
```
