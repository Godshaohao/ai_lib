# Formal NL / RAW Workbook Smoke Results

This directory contains the generated single-table HTML overview and per-IP Excel workbooks from the four-library, five-RAW-version workbench simulation on 2026-10-24. The four selected checks were rerun against the current RAW and formal-NL paths with the updated code. Each IP has a new immutable run snapshot and a refreshed `latest.xlsx`.

## Open the results

Open [IP check overview](ip_checks/index.html). Each registered IP links to its workbook under `libraries/<library-id>/latest.xlsx`. For each IP, `runs/<review-id>/review_result.json` identifies the selected checks; the workbook's `evidence/<check>.json` references are relative to that run directory. The run folder contains the evidence snapshots used to produce that workbook. The overview lists all five RAW versions per IP and the latest version first when expanded.

## Scope and interpretation

- The registry used for this run is marked `SIMULATION`; these artifacts validate workbench navigation, report generation and workbook linking, not EDA acceptance or release readiness.
- One stable workbook is maintained per IP. `latest_workbook.json` identifies the newest completed run; previous run workbooks and evidence remain under their immutable `runs/<review-id>/` directories.
- The evidence JSON contains source-root paths from the generating machine. Those paths are provenance references and may not exist on another machine. The Excel's report references are relative to the included run directory.
- The output is a checked-in test snapshot. Running the workbench later does not update this snapshot automatically.

## Artifact validation

| IP | Checks rerun | Quality result | Confirmed findings |
| --- | --- | --- | --- |
| `IHP.sg13g2_stdcell` | Formal NL, Macro Index, LEF Review, LEF–Liberty | `ISSUES_FOUND` | 504 file-by-Cell mismatch instances across six Liberty files; 12 also have extra signal Pins. The sampled mismatch is missing `VDD`/`VSS` PG declarations in Liberty. These are affected instances, not 504 independent root causes. |
| `SRAM22.sram22_1024x32m8w8` | Same four checks | `CHANGES_FOUND` | 2 LEF field-change findings; 0 Liberty interface mismatches. |
| `SRAM22.sram22_256x16m8w8` | Same four checks | `CHANGES_FOUND` | 2 LEF field-change findings; 0 Liberty interface mismatches. |
| `SRAM22.sram22_512x32m4w8` | Same four checks | `CHANGES_FOUND` | 2 LEF field-change findings; 0 Liberty interface mismatches. |

The bus-overlap conflict path is covered by deterministic synthetic regression tests; these four samples did not contain overlapping bus/scalar definitions, so their mismatch totals did not change due to that fix. The quality summary now prioritizes confirmed mismatches over unverified findings; IHP therefore reports `ISSUES_FOUND` while retaining its separate 5 unverified findings. All four stable `.xlsx` files passed ZIP container integrity checks and contain the expected workbook sheets. The overview contains four per-IP workbook links and lists five RAW versions for each IP.
