---
name: content-diff-orchestration
description: Use when comparing two library versions, scan outputs, or library files where raw text diff is insufficient and structural diff routing is needed for Liberty, LEF, Verilog, CDL, SDC, UPF, CPF, binary metadata, documents, release notes, or waivers.
---

# Content Diff Orchestration

## Core Principle

Route differences to the right structural comparison path. Do not use plain file diff as the main answer for library management. The output should explain what changed at the content-structure level and which manual pairwise checks are still required.

## Inputs

Accept any of:

- `old_scan_dir`
- `new_scan_dir`
- Two explicit files
- `file_type`
- `library_name`
- `diff_mode`: `adjacent`, `explicit`, `pairwise`
- `depth`: `summary`, `structural`, `deep`

## Diff Routing

Use file type to choose the comparison strategy:

| File Type | Primary Question | Default Action |
| --- | --- | --- |
| Liberty | Did cells, pins, corners, timing arcs, power arcs, or capacitance data change? | Structural parser diff |
| LEF | Did macros, pins, directions, layers, sizes, obstructions, or blockages change? | Structural parser diff |
| Verilog | Did modules, ports, directions, widths, parameters, or instances change? | Structural parser diff |
| CDL/SPICE | Did subckts, pins, instances, or models change? | Structural parser diff |
| SDC | Did clocks, constraints, exceptions, IO delays, or groups change? | Structural diff when available |
| UPF/CPF | Did power domains, supplies, isolation, retention, or level shifters change? | Structural diff when available |
| Waiver | Did waiver rules, IDs, scopes, or review obligations change? | Evidence/structural diff |
| IBIS | Did components, pins, models, model types, or version metadata change? | Structural parser diff |
| PWL | Did waveform points, time/value pairs, or directives change? | Structural parser diff |
| SNP/Touchstone | Did option line, port count, frequency rows, or data rows change? | Structural parser diff |
| CPM | Did component, pin, direction, or record counts change? | Structural parser diff |
| DB/GDS/OAS | Did metadata, hash, size, timestamp, or layer summary change? | Metadata-only review |
| Doc/Release Note/Waiver | Did release evidence or review obligations change? | Evidence diff |
| Unknown | Is the file relevant to release evidence or view coverage? | Manual review |

## Required Output

Always return five sections:

1. Conclusion
2. Evidence
3. Risks
4. Recommended Commands
5. Manual Confirmation

Also provide a structured plan:

```json
{
  "diff_plan": [
    {
      "file_type": "liberty",
      "old_file": ".../old.lib",
      "new_file": ".../new.lib",
      "parser": "liberty_parser",
      "diff_tool": "liberty_structural_diff",
      "command": "python -m lib_guard.cli file-diff liberty ...",
      "reason": "same logical view, changed checksum, needs structural diff"
    }
  ],
  "skipped": [
    {
      "file_type": "gds",
      "reason": "binary layout file, use metadata/hash/layer summary only"
    }
  ],
  "manual_review": [
    {
      "file_type": "gds",
      "review_mode": "metadata-only",
      "reason": "binary file cannot be meaningfully text-diffed"
    }
  ]
}
```

## Execution Policy

May execute automatically:

- Parser extraction.
- Summary diff.
- Structural diff for small and normal-size files.
- Metadata diff.

Ask before executing:

- Large-file deep diff.
- Large pairwise batches.
- Long runtime analysis.
- Full File Diff command generation for large or uncertain comparisons before base/comparison is confirmed.

Never execute automatically:

- Source file modification.
- Deleting source or result files.
- Deciding that a difference is acceptable.
- `release link --apply`.

## Interpretation Rules

Treat parser results as evidence for review, not as the final expert judgment.

For structural files, focus on domain objects:

- Verilog: module, port, direction, width, instance.
- LEF: macro, pin, direction, layer, size.
- Liberty: cell, pin, corner, timing arc, `is_macro`, `is_pad`.
- CDL: subckt, pin, instance.
- SDC: clock, generated clock, uncertainty, load, driving cell, IO delay, group, exception.
- UPF/CPF: power domain, supply, isolation, level shifter, retention, power state.
- Waiver/IBIS/PWL/SNP/CPM: use the dedicated parser evidence when available.

## v6 Recommendation Model

The product flow is:

```text
Catalog -> Diff Timeline -> Selected Diff -> recommended File Diff
```

Do not present File Diff as `done/total`. Selected Diff should recommend the key files to review and suppress full command batches when the comparison is too large or the base/comparison is uncertain.

For binary layout/database files, report metadata-only limits clearly.

## Boundaries

This skill does not replace expert review. It does not modify source files. It does not accept or reject a release. It does not collapse all file changes into a single changed-file count.

## Common Mistakes

- Reporting `changed_files` as the main conclusion.
- Text-diffing binary or generated database files.
- Mixing release gate judgment into diff evidence.
- Treating documentation changes as ordinary text noise instead of release evidence changes.
