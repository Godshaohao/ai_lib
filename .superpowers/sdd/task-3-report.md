# Task 3 Report: Make Diff Identity Deterministic and Traceable

## Requirement Mapping

| Requirement | Implementation boundary | Verification |
| --- | --- | --- |
| Stable identity and short diff ID for identical scan evidence | `diff_scan_outputs()` and `build_diff_identity()` | Existing diff fixture runs the same old/new scans twice |
| Snapshot digest changes affect diff identity | `scan_meta.snapshot_identity.digest` selection | Existing fixture changes new and old digest independently |
| Historical scan compatibility | `input_fingerprint.hash` fallback | Existing fixture removes both snapshot identity objects |
| Catalog traceability | `update_catalog_diff_status()` | Catalog runtime persists generated diff metadata without recomputing it |

## RED

Command:

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline.ScanPipelineTest.test_diff_scan_reports_inventory_and_summary_changes -q
```

Observed result: failed as expected because the timestamp-based `diff_id` changed between two diffs of the same evidence.

```text
AssertionError: '3d4210ae17e00147' != 'cc976d4a60585c50'
Ran 1 test in 0.088s
FAILED (failures=1)
```

## GREEN

The same focused command passed after binding identity to old/new snapshot digest and deriving `diff_id` from the identity digest.

```text
Ran 1 test in 0.104s
OK
```

Related module regression:

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline src.lib_guard.test.test_catalog_timeline src.lib_guard.test.test_artifact_identity -q
```

Result: `Ran 122 tests` and `OK`.

Full verification:

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m compileall -q src
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q
```

Result: compileall completed successfully; full suite ran `367 tests` and `OK`.

## Changed Files

- `src/lib_guard/diff/scan_diff.py`
- `src/lib_guard/catalog/index.py`
- `src/lib_guard/test/test_scan_pipeline.py`

`diff_meta.identity` now comes from `build_diff_identity()`. `scan_meta.snapshot_identity.digest` is preferred, followed by `file_inventory.snapshot_identity.digest`; historical evidence falls back to `input_fingerprint.hash` and records `identity_source: input_fingerprint_fallback`. `diff_created_at` remains audit-only.

Catalog persists the generated diff identity, short ID, and identity source from `diff_meta.json`; it does not recompute the identity.

## Commit

Implementation: `90c6cee feat: make scan diff identity deterministic`.

## Unchanged Boundaries

- File-difference algorithms, UI, and CLI commands are unchanged.
- No dependencies or new CLI options were added.
- `fix.md` was preserved and not staged.

## Review Remediation

The initial implementation treated absent evidence as empty deterministic inputs and did not preserve per-side provenance. The remediation keeps the diff algorithm unchanged while making identity availability explicit.

- A side with neither `snapshot_identity.digest` nor `input_fingerprint.hash` now yields `identity_status: UNAVAILABLE`, `identity_source: missing_evidence`, `identity: null`, and `diff_id: null`.
- `identity_sources` records independent `old` and `new` source/trust pairs. Snapshot evidence is `TRUSTED`; legacy fingerprint evidence is `LEGACY_FALLBACK`.
- Mixed snapshot/fallback pairs yield `identity_status: MIXED_EVIDENCE`, `identity_source: mixed_evidence`, and `identity_trust: NON_HOMOGENEOUS`. The ordered side sources are included in `build_diff_identity()` policy input, so identical raw digests with opposite provenance directions cannot collide.
- Catalog now passes through `identity_status`, `identity_source`, `identity_trust`, and `identity_sources` from a real `diff_meta.json`. When a newer diff has no identity or ID, it writes explicit `null` values so rebuild-time legacy merging cannot retain a stale trusted value.

## Remediation TDD Evidence

RED coverage was added before the remediation:

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline.ScanPipelineTest.test_diff_scan_reports_inventory_and_summary_changes -q
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_catalog_timeline.CatalogTimelineTest.test_catalog_diff_status_passes_through_identity_provenance_and_clears_missing_identity -q
```

The first command failed because `identity_status` was absent. The second failed because catalog did not pass through the provenance fields; after the initial fix, it exposed stale `identity` and `diff_id` being reintroduced during catalog rebuild.

GREEN focused checks passed after the remediation. The scan fixture covers trusted snapshot evidence, both mixed directions with identical raw digests, legacy fallback mutation, and changed inventories with missing evidence. The catalog fixture writes actual `diff_meta.json` files, verifies full provenance pass-through, then verifies that unavailable identity/ID replace cached trusted values with `null`.

Final verification:

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_compile_pycache PYTHONPATH=src python3 -m compileall -q src
PYTHONPYCACHEPREFIX=/tmp/ai_lib_full_pycache PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q
```

`compileall` completed successfully. The complete suite ran 368 tests and passed. `git diff --check` also completed successfully.
