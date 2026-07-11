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

## Independent Review Remediation

### Fixed Boundaries

- Restored the original `version_input_fingerprint.v1` payload on both ScanRunner and Catalog discovery. Hash coverage and strength are not catalog fingerprint fields.
- Derive identity strength from scan records only, with exact `full`, `mixed`, and `metadata` outcomes. An empty inventory is `metadata`.
- Bind policy identity to the actual scan context, including the legacy `config.hash` fallback and quick/inventory/full mode overrides.
- Catalog continues to store the ScanRunner-provided snapshot identity without recomputing it.

### RED

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline.ScanPipelineTest.test_scan_snapshot_identity_reports_exact_evidence_strengths src.lib_guard.test.test_scan_pipeline.ScanPipelineTest.test_scan_policy_identity_uses_legacy_hash_and_mode_overrides src.lib_guard.test.test_catalog_timeline.CatalogTimelineTest.test_catalog_sampled_refresh_keeps_real_scan_identity_current -q
```

Result: failed as expected. Policy identity rejected the scan context, a full-mode identity reported `smart`, and unchanged RAW became `STALE_SCAN` after a sampled Catalog refresh.

### GREEN

The same focused command ran `3 tests` and passed.

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline src.lib_guard.test.test_catalog_timeline -q
```

Result: `Ran 110 tests` and `OK` (the prior 107-test baseline plus three independent-review regressions).

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m compileall -q src
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q
```

Result: compile completed successfully; `Ran 365 tests` and `OK`.

### Remediation Commit

Implementation: `496d28f fix: preserve scan identity catalog compatibility`.

## Second Independent Review Remediation

### Fixed Boundaries

- Kept `scan_meta.input_fingerprint` and `file_inventory.input_fingerprint` on the unchanged `version_input_fingerprint.v1` metadata contract used by Catalog stale comparison.
- Added a private `scan_snapshot_fingerprint.v1` summary for snapshot identity only. It hashes normalized path, size, mtime, file type, SHA-256, hash status, and hash policy, then persists only the resulting digest, coverage, count, and strength in the identity payload.
- Made `hash_policy=none` an explicit no-hash decision. Key files now retain `sha256: null`, `hash_status: NOT_REQUIRED`, and metadata evidence strength. Quick and inventory modes retain their effective `none` policy.
- `scan_meta` and `file_inventory` continue to carry the exact same `snapshot_identity` object.

### RED

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline.ScanPipelineTest.test_snapshot_identity_binds_content_digest_without_changing_catalog_fingerprint src.lib_guard.test.test_scan_pipeline.ScanPipelineTest.test_hash_policy_none_never_hashes_key_files -q
```

Result: failed as expected. Same path/size/mtime scans with distinct successful SHA-256 values produced an identical snapshot digest, and `hash_policy=none` incorrectly produced `full` evidence.

### GREEN

The same focused command ran `2 tests` and passed.

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline src.lib_guard.test.test_catalog_timeline -q
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m compileall -q src
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q
```

Result: scan/timeline regression ran `112 tests` and passed; compile completed successfully; full suite ran `367 tests` and passed.

### Compatibility Rationale

Catalog is not changed and does not recompute snapshot identity. Its stale comparison continues to read the legacy metadata-only `input_fingerprint.hash`, so preserved metadata snapshots remain comparable. Snapshot identity receives the compact content-aware fingerprint instead, separating content equivalence from the Catalog metadata contract without embedding the file inventory in identity JSON.

### Remediation Commit

Implementation: `f13dc94 fix: bind content evidence to scan identity`.
