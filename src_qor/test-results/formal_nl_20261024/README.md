# Formal NL / RAW Workbook Smoke Results

This directory contains the generated Catalog-style HTML and the latest per-IP Excel workbooks from the four-library, five-RAW-version workbench simulation on 2026-10-24.

## Open the results

Open [IP check overview](ip_checks/index.html). Each registered IP links to its workbook under `libraries/<library-id>/latest.xlsx`.

## Scope and interpretation

- The registry used for this run is marked `SIMULATION`; these artifacts validate workbench navigation, report generation and workbook linking, not EDA acceptance or release readiness.
- One workbook is retained per IP. Each workbook is the latest successfully completed result represented by its adjacent `latest_workbook.json` pointer.
- The HTML and workbook contain source-root paths from the generating machine. Those paths are provenance references and may not exist on another machine.
- The output is a checked-in test snapshot. Running the workbench later does not update this snapshot automatically.

## Artifact validation

All four `.xlsx` files passed ZIP container integrity checks and contain 11 worksheet XML files each. The overview contains four per-IP workbook links.
