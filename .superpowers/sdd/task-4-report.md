# Task 4 Report: Reproducible Effective Lock Artifact

## Requirement Mapping

| Requirement | Implementation boundary | Verification |
| --- | --- | --- |
| Bind the effective composition to ordered component evidence | `effective/manifest.py` component metadata and `build_effective_identity()` | Order and snapshot-digest regression tests |
| Preserve evidence provenance and weak/missing evidence | Component `identity_source`, `evidence_strength`, plus manifest identity status | Legacy fingerprint and missing-evidence regression test |
| Bind current pointer and approval records to the effective digest | `effective/pointer.py` and `window/cli.py` | Pointer/approval digest and mismatch regression test |
| Detect stale/tampered references during read/accept | Pointer read consistency status and accept-window compare/approval checks | Pointer, compare, and approval mismatch assertions |

## RED

Command:

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_effective_manifest.EffectiveManifestTest.test_effective_digest_binds_component_order_and_snapshots \
  src.lib_guard.test.test_effective_manifest.EffectiveManifestTest.test_effective_digest_excludes_created_at_and_paths \
  src.lib_guard.test.test_effective_manifest.EffectiveManifestTest.test_effective_components_mark_legacy_and_missing_evidence \
  src.lib_guard.test.test_effective_manifest.EffectiveManifestTest.test_pointer_and_approval_bind_effective_digest_and_detect_mismatch -q
```

Result: failed as expected with missing `manifest["identity"]`, component `snapshot_digest`, and pointer `effective_digest` fields.

## GREEN

The same focused command ran 4 tests and passed.

Implemented behavior:

- Each component records role, version, scope, order, snapshot digest, evidence strength, and identity source.
- Scan `snapshot_identity` is preferred; historical `input_fingerprint.hash` is retained as `legacy_input_fingerprint`; absent evidence is marked `missing_evidence` with `UNAVAILABLE` manifest status.
- `build_effective_identity()` receives only stable composition fields, so audit time and filesystem paths do not change the digest.
- Pointers persist `effective_digest`; pointer reads expose `MATCH` or `MISMATCH` after recomputing the manifest identity.
- Review approvals persist `candidate_effective_digest`; accept-window rejects declared compare or approval effective-digest mismatches.

## Verification

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_effective_manifest \
  src.lib_guard.test.test_effective_pointer \
  src.lib_guard.test.test_window_intake -q
```

Result: `Ran 34 tests` and `OK`.

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m compileall -q src
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q
```

Result: compileall completed successfully; full suite ran `372 tests` and `OK`.

## Changed Files

- `src/lib_guard/effective/manifest.py`
- `src/lib_guard/effective/pointer.py`
- `src/lib_guard/window/cli.py`
- `src/lib_guard/test/test_effective_manifest.py`
- `.superpowers/sdd/task-4-report.md`

## Compatibility Boundaries

- Historical manifests without `identity` retain manifest SHA-256 validation and are marked `manifest_sha256_fallback` in newly written pointers.
- Existing compare artifacts without an effective digest retain their current SHA-256/target validation; effective-digest validation applies when compare evidence declares it.
- No commands, UI/pages, dependencies, resolver window-selection policy, or existing effective file-map fields changed.

## Commits

- Implementation: `a6b9edd feat: lock effective compositions to evidence digests`
- Report: recorded in the follow-up documentation commit.
