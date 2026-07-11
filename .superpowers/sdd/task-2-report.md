# Task 2 Report: Bind Scan Evidence to Snapshot Identity

## Requirement Mapping

| Requirement | Implementation boundary | Verification |
| --- | --- | --- |
| Stable scan identity and evidence strength | `ScanPolicy.identity_payload()`, `ScanRunner._input_fingerprint()` and scan artifacts | `test_scan_snapshot_identity_is_stable_and_reports_hash_strength` |
| Persist the exact scan identity in Catalog runtime state | `run_catalog_workflow()` and `update_catalog_scan_status()` | `test_catalog_scan_status_persists_scan_snapshot_identity` |
| Preserve existing input fingerprint contract | `input_fingerprint.hash` remains present | focused scan and timeline suites |

## RED

Command:

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline.ScanPipelineTest.test_scan_snapshot_identity_is_stable_and_reports_hash_strength src.lib_guard.test.test_catalog_timeline.CatalogTimelineTest.test_catalog_scan_status_persists_scan_snapshot_identity -q
```

Result: failed as expected. The scan test raised `KeyError: 'snapshot_identity'`; the Catalog test raised `TypeError` because `update_catalog_scan_status()` did not accept `snapshot_identity`.

## GREEN

Focused RED tests after implementation:

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline.ScanPipelineTest.test_scan_snapshot_identity_is_stable_and_reports_hash_strength src.lib_guard.test.test_catalog_timeline.CatalogTimelineTest.test_catalog_scan_status_persists_scan_snapshot_identity -q
```

Result: `Ran 2 tests` and `OK`.

Task 2 focused regression:

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline src.lib_guard.test.test_catalog_timeline -q
```

Result: `Ran 107 tests` and `OK`.

## Full Suite

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m compileall -q src
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q
```

Result: compile completed successfully; `Ran 362 tests in 3.963s` and `OK`.

## Changed Files

- `src/lib_guard/scan/policy.py`
- `src/lib_guard/scan/scanner.py`
- `src/lib_guard/cli_commands/catalog.py`
- `src/lib_guard/catalog/index.py`
- `src/lib_guard/test/test_scan_pipeline.py`
- `src/lib_guard/test/test_catalog_timeline.py`
- `.superpowers/sdd/task-2-report.md`

## Commit

Implementation: `d482136 feat: bind scan evidence to snapshot identity`.

## Residual Risks

- `metadata` evidence intentionally does not establish full content equivalence; consumers must retain the reported strength when making release decisions.
- Catalog runtime separation into a sidecar is intentionally deferred to Task 5; this task preserves the current runtime-state storage and only persists the scan-provided identity.
