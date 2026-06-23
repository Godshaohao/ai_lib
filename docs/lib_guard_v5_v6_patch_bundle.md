# lib_guard v5/v6 Patch Bundle

This document tracks the code and documentation package for the v5 review-navigation patch and the v6 File Diff recommendation/parser patch.

## Commit Scope

| Patch | Commit | Summary |
| --- | --- | --- |
| v5 | `ec3fdb2797376d7ed2282a4668502263fc504ca7` | Review navigation patch for catalog/diff report/product theme. |
| v6 | `ea3cbf641350ba6b6274c18a8d66638b9f8d4502` | File Diff recommendation model, Selected Diff UI updates, parser and semantic diff expansion. |

## Behavior Summary

- Catalog is a map and navigation hub. It does not directly expose full File Diff command lists.
- Diff Timeline groups comparison choices before a reviewer enters Selected Diff.
- Selected Diff owns the key File Diff recommendation queue.
- File Diff is a focused review recommendation model, not a `done/total` completion model.
- Large or ambiguous comparison changes first require base/comparison confirmation.
- File Diff HTML now exposes structured field changes, source-location hints, and raw text diff fallback.

## Supported Pairwise File Diff Types

```text
lef
liberty
verilog
cdl
sdc
upf
cpf
spef
db
waiver
ibis
pwl
snp
cpm
```

## Parser And Diff Upgrades

| Area | Current support |
| --- | --- |
| Liberty | `is_macro`, `is_pad`, `cell_footprint`, cell attributes, pin and pg_pin structure. |
| SDC | Commands/counts plus semantic clocks, generated clocks, uncertainty, loads, driving cells, IO delays, groups, and exceptions where parsed. |
| UPF | Commands/counts plus semantic power domains, supply nets/ports, domain supplies, isolation, level shifters, retention, and power states where parsed. |
| Waiver | Lightweight waiver entry extraction for release evidence and pairwise diff. |
| IBIS | Component, pin, model, model type, and IBIS version evidence. |
| PWL | Point/directive extraction and count-level structural comparison. |
| SNP | Touchstone option line, frequency/data rows, and inferred port count evidence. |
| CPM | Component/pin/record evidence for package/model review. |
| DB | Metadata-only evidence. |

## Patch File List

```text
src/lib_guard/cli.py
src/lib_guard/diff/file_diff.py
src/lib_guard/render/catalog_report.py
src/lib_guard/render/diff_report.py
src/lib_guard/render/html_report.py
src/lib_guard/render/product_theme.py
src/lib_guard/render/release_report.py
src/lib_guard/review/diff_index.py
src/lib_guard/scan/inventory.py
src/lib_guard/scan/parser_engine.py
src/lib_guard/scan/parsers/__init__.py
src/lib_guard/scan/parsers/cpm.py
src/lib_guard/scan/parsers/ibis.py
src/lib_guard/scan/parsers/liberty.py
src/lib_guard/scan/parsers/package.py
src/lib_guard/scan/parsers/pwl.py
src/lib_guard/scan/parsers/sdc.py
src/lib_guard/scan/parsers/snp.py
src/lib_guard/scan/parsers/upf.py
src/lib_guard/test/test_release_manifest_flow.py
src/lib_guard/test/test_v5_catalog.py
src/lib_guard/test/test_v5_scan_pipeline.py
```

## Bundle Generation

The bundle is generated with `project-bundle-restore` from the repository root. The current bundle should include the patch files above and the updated docs that describe the new behavior.

Expected local output:

```text
work/project_bundles/lib_guard_v5_v6_patch/
```

Restore checks should be run after packing so checksum validation proves the JSON parts are usable.

## Verification

Run this after applying or restoring the patch:

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -b -s src\lib_guard\test -p "test_*.py"
```

Expected current result:

```text
Ran 60 tests
OK
```
