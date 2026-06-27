Status: archived
Archive reason: moved out of current lib_guard documentation.

# lib_guard Product Scope

## 1. Problem Brief

Library/IP delivery review currently mixes directory discovery, manual scan notes, parser evidence, diff checks, and release handoff in scattered places. For many IP, RAM, standard-cell, or vendor library drops, this quickly becomes hard to audit.

`lib_guard` provides a lightweight control plane:

- Register what libraries and versions exist.
- Decide which versions need scan, diff, or release checks.
- Keep evidence traceable through JSON and HTML.
- Avoid forcing every library through full parser and deep diff work on day one.

## 2. Users And Decisions

| User | What they need to see | Decision / Action |
|---|---|---|
| Library owner | Version chain, required views, readiness, missing evidence | Fix package metadata or request re-delivery |
| PD / integration engineer | Usable views, release alias, linked file manifest | Decide whether a version can enter stage/current/approved |
| CAD maintainer | Parser quality, command line, generated JSON, failed files | Debug scanner/parser/release behavior |
| Reviewer / lead | Asset coverage, risk trend, next actions | Decide where to spend review effort |

## 3. MVP Scope

### In Scope

- Catalog discovery for library/version directories.
- Incremental catalog refresh using state where available.
- Scan selected versions with inventory, required views, doc/readiness, and parser quality.
- Default `signature` scan that avoids broad EDA parser work unless explicitly needed.
- Structural diff for stage-gate decisions.
- Recommended pairwise file-diff commands for detailed LEF/Liberty/Verilog/CDL/SDC/UPF/CPF/SPEF/DB/waiver/IBIS/PWL/SNP/CPM analysis.
- Release check and file-level link/verify manifest.
- HTML review pages for catalog, scan, diff timeline, selected diff, file-diff, and release.

### Out Of Scope

- Automatically proving all semantic compatibility across every EDA format.
- Rendering every low-level file diff inside the catalog page.
- Treating File Diff as a full completion scoreboard.
- Treating generated HTML as source.
- Forcing all libraries to complete full scan/diff before they can be registered.
- Reorganizing vendor RAW directory structures.

## 4. Success Criteria

1. A RAW tree can be cataloged without accidentally scanning every file deeply.
2. A single library version can be scanned, reviewed, diffed, and prepared for release.
3. The catalog can scale to hundreds of libraries by keeping heavy details collapsed or on per-library pages.
4. Every user-facing report links back to JSON evidence and runnable CLI commands.
5. Release operations are gated by readiness, diff evidence, and explicit apply/overwrite intent.
6. Catalog leads reviewers to Diff Timeline and Selected Diff before any File Diff command is run.

## 5. Product Open Questions

| ID | Question | Decision Needed |
|---|---|---|
| P001 | Which library classes need custom mapping beyond IP/RAM/stdcell? | Add policy examples and fixtures |
| P002 | Which pairwise file-diff formats should be promoted from helper command to release gate? | Define per-format L1/L2 gate policy |
| P003 | How should catalog UI group 200-500 libraries? | Finalize library workspace and per-library detail page pattern |
| P004 | Which release aliases are used by real projects? | Confirm stage/current/approved naming and target directory rules |

## 6. Current v6 File Diff Position

File Diff is a focused review lens. It is recommended from Selected Diff when structural comparison finds important changed files. Large or ambiguous comparisons first ask the reviewer to confirm the base/comparison context instead of generating a full command batch.

Current semantic upgrades include Liberty `is_macro`/`is_pad`, SDC clock/load/uncertainty fields, UPF power-domain/supply/isolation fields, and parser-backed waiver, IBIS, PWL, SNP, and CPM evidence. DB remains metadata-only.
