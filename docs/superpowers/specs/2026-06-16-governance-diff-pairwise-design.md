# Governance Diff and Pairwise File Diff Design

Date: 2026-06-16

Status update: 2026-06-23

The current implementation follows the v6 recommendation model:

```text
Catalog -> Diff Timeline -> Selected Diff -> recommended File Diff
```

Catalog no longer directly exposes full File Diff command lists. Selected Diff owns the key File Diff recommendation queue, and large or ambiguous comparisons require base/comparison confirmation before broad command generation.

Implemented pairwise types now include:

```text
lef, liberty, verilog, cdl, sdc, upf, cpf, spef, db, waiver, ibis, pwl, snp, cpm
```

## Purpose

`lib_guard compare` should be a governance gate, not a full EDA file diff viewer. It should decide whether a library version can move to the next stage and provide enough evidence for manual review. Detailed LEF, Liberty, Verilog, SDC, and related file comparisons should be handled by pairwise file diff commands that compare one old file with one new file.

## Scope

In scope:

- Keep catalog-driven `compare` as the main governance diff entry.
- Remove or demote global merged object diff behavior from the gate decision.
- Compare file structure, required view completeness, parser/readiness regression, summary hash changes, signature changes, and release readiness changes.
- Generate pairwise file diff task recommendations with copyable commands.
- Add a `file-diff` CLI surface for explicit two-file comparisons.
- Show pairwise task recommendations in diff HTML without embedding large detailed reports.

Out of scope for the governance diff:

- Expanding all LEF macro/pin differences in the main diff HTML.
- Expanding all Verilog module/port differences in the main diff HTML.
- Expanding all Liberty cell/corner/pin differences in the main diff HTML.
- Treating merged objects from multiple files as release-blocking evidence.

## Design Principles

- The governance diff answers: can this version move forward?
- Pairwise file diff answers: what changed inside these two specific files?
- HTML starts with conclusion, blockers, and next actions.
- Details remain traceable through JSON files and task commands.
- Automatic file pairing must be conservative. Ambiguous pairings become manual review tasks.

## Current Problem

The current object diff merges parser results by file type before comparison:

- all LEF macros are compared as one merged set;
- all Verilog modules are compared as one merged set;
- all Liberty libraries and cells are compared as one merged set.

This can produce false blockers for real library packages where multiple files, views, corners, or wrappers legitimately contain repeated object names. The governance diff should not use this merged object model as authoritative release evidence.

## Governance Diff Outputs

`compare` should continue producing the existing core outputs:

- `diff_meta.json`
- `diff_summary.json`
- `file_diff.json`
- `component_diff.json`
- `summary_diff.json`
- `signature_diff.json`
- `release_readiness_diff.json`
- `diff_issues.json`
- `diff_report.md`

It should add:

- `pairwise_diff_tasks.json`

The existing `parser_result_diff/` directory should either be removed from the governance path or marked as non-gating experimental evidence until it is redesigned as per-file/per-view evidence.

## Governance Signals

The gate status should be based on:

- Missing required scan inputs.
- File additions, removals, and changed files.
- Required view presence changes.
- Required view parser status regression.
- Parser quality regression.
- Summary hash changes.
- Signature hash changes.
- Release readiness status changes.
- New blocking or manual review items.
- Explicit manual review tasks created by ambiguous pairing.

Recommended statuses:

- `SAME`: no meaningful governance change.
- `DIFF`: changes exist, no blocker.
- `BLOCK`: blocker or unresolved required evidence.
- `FAILED`: tool failure or unreadable required input.

## Pairwise Diff Task Model

`pairwise_diff_tasks.json` should be a list of task objects:

```json
{
  "task_id": "pair_lef_0001",
  "file_type": "lef",
  "priority": "P1",
  "reason": "changed_required_view",
  "old_file": "C:/path/old/foo.lef",
  "new_file": "C:/path/new/foo.lef",
  "pairing_confidence": "path_exact",
  "command": "python -m lib_guard.cli file-diff lef --old C:/path/old/foo.lef --new C:/path/new/foo.lef --out work/file_diff/pair_lef_0001",
  "expected_output": "work/file_diff/pair_lef_0001",
  "status": "PENDING"
}
```

Task priorities:

- `P0`: required view removed, required parser regressed, release readiness blocker, or current/approved promotion needs evidence.
- `P1`: changed required view file, changed summary/signature, manual review recommended.
- `P2`: changed optional view or metadata-only review.

## File Pairing Rules

Automatic pairing order:

1. Same relative path and same file type.
2. Same file name and same file type, only if the match is unique.
3. Required view type where old and new each have exactly one file of that type.

No automatic pairing when:

- multiple old files and multiple new files share the same file type;
- Liberty has multiple corners and names are ambiguous;
- LEF has multiple technology/macro views and names are ambiguous;
- files moved or split and no unique candidate exists.

Ambiguous cases should create a manual review item with suggested candidate files but no command that pretends to be authoritative.

## Pairwise File Diff CLI

Add a command group:

```powershell
python -m lib_guard.cli file-diff lef --old old.lef --new new.lef --out work/file_diff/lef_0001
python -m lib_guard.cli file-diff liberty --old old.lib --new new.lib --out work/file_diff/lib_0001
python -m lib_guard.cli file-diff verilog --old old.v --new new.v --out work/file_diff/verilog_0001
python -m lib_guard.cli file-diff sdc --old old.sdc --new new.sdc --out work/file_diff/sdc_0001
```

Initial supported types:

- `lef`
- `liberty`
- `verilog`
- `sdc`

Planned extensions:

- `upf`
- `cpf`
- `cdl`
- `spef`
- `package`
- `waiver`

Each pairwise diff writes:

- `file_diff_meta.json`
- `file_diff_summary.json`
- `file_diff_issues.json`
- `file_diff_detail.json`
- optional `index.html`

The pairwise command should use the existing parser modules where practical. It may start with parser-level JSON output and grow richer over time.

## HTML Behavior

Diff HTML should show:

- gate conclusion;
- blocker and warning counts;
- version relation;
- changed file counts;
- required view regression;
- parser/readiness regression;
- pairwise diff task table;
- evidence links.

The pairwise task table should include:

- priority;
- file type;
- reason;
- old/new file path;
- copy command button;
- expected output link when available;
- status.

The HTML should not embed large file-level diff details. It should link to pairwise outputs.

## Release Gate Interaction

For `stage`:

- governance diff is optional;
- inventory/readiness evidence is enough for L0.

For `current`:

- governance diff should exist for promoted versions;
- required P0 pairwise tasks must either be completed or explicitly acknowledged.

For `approved`:

- governance diff must pass;
- required pairwise evidence must exist for changed required views;
- unresolved manual review items block promotion.

## Implementation Plan Outline

1. Add `pairwise_diff_tasks` builder.
2. Modify `diff_scan_outputs` to stop using merged object diff as gate evidence.
3. Write `pairwise_diff_tasks.json` in diff output.
4. Update diff HTML to show pairwise task table and command copy actions.
5. Add `file-diff` CLI group.
6. Implement first pairwise commands for `lef`, `liberty`, `verilog`, and `sdc`.
7. Add tests for conservative pairing, ambiguous pairing, HTML links, and command generation.
8. Update user docs with governance diff vs pairwise diff workflow.

## Testing Strategy

Unit tests:

- exact path pairing;
- unique file name pairing;
- one-old-one-new required view pairing;
- ambiguous multi-file view creates manual review only;
- pairwise task command is stable and copyable;
- governance diff no longer blocks because of merged object names alone.

Integration tests:

- catalog `compare` writes `pairwise_diff_tasks.json`;
- diff HTML contains pairwise commands;
- `file-diff lef` writes expected JSON;
- `file-diff verilog` writes expected JSON;
- release check can consume governance diff and pairwise task status.

Regression tests:

- multi-corner Liberty packages do not get globally merged into false blocker evidence;
- multiple LEF files with repeated macro names do not overwrite each other in governance diff;
- unchanged inventory produces `SAME` when readiness and signatures do not change.

## Decisions

- Pairwise task completion should be tracked by `pairwise_diff_task_status.json`. The implementation may also detect expected output files as a convenience, but the status JSON is the authoritative task state.
- `approved` should require pairwise JSON evidence for changed required views. Pairwise HTML is recommended but not required for the first implementation.
- SDC first implementation should compare parsed command categories and command counts, then report changed command sets. It should not attempt full timing semantic equivalence in the first version.

## Acceptance Criteria

- `compare` remains fast and readable.
- Main diff HTML shows conclusion first and detailed evidence second.
- `pairwise_diff_tasks.json` gives concrete commands for manual analysis.
- No release blocker is created from globally merged LEF/Verilog/Liberty object sets.
- Pairwise file diff tools support explicit two-file analysis.
- Ambiguous file matching never creates a misleading automatic comparison.
