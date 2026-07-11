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

## Independent Review Remediation

Baseline: `86ea67d`

| Review finding | Fix | Regression coverage |
| --- | --- | --- |
| 1. Generated compare targets did not bind the effective identity | `effective/compare.py` now validates the resolved effective manifest and records its recomputed `effective_digest`, manifest SHA-256, identity source/status, and evidence provenance. `accept-window` checks the effective digest before the file SHA lock. | A real `build_effective_manifest()` -> `build_compare_manifest()` -> `cmd_accept()` path replaces the manifest with the same effective ID but a different self-consistent snapshot and is rejected. |
| 2. Manifest validation compared only the digest | `effective/manifest.py::validate_effective_manifest()` is the central validator. It compares the complete stored identity object (`schema_version`, `digest`, and `payload`), validates component provenance coherence, and recomputes the top-level status/source/trust tuple. Pointer, compare, and window consume this result. | Tests tamper identity payload, schema, top-level provenance, and component provenance independently and require `MISMATCH`. |
| 3. Pointer integrity and evidence status were conflated | Pointer output now has `effective_integrity_status` plus independent `effective_evidence_status/source/trust`. `MIXED_EVIDENCE` remains the manifest compatibility value while the new pointer status is `MIXED`; `UNAVAILABLE` remains visible when integrity is `MATCH`. Existing `effective_identity_*` fields retain their read/write compatibility behavior. | Pointer tests cover trusted, mixed, and unavailable evidence without allowing `MATCH` to overwrite evidence state. |
| 4. Historical pointers did not reliably validate the actual manifest file | Identity-less manifests use actual file SHA-256. Old pointers validate either `manifest_sha256` or `manifest_sha256_fallback` and return `MATCH`, `MISMATCH`, or `MISSING`. | A historical manifest/pointer regression validates both field names, then mutates the file and requires `MISMATCH`. |
| 5. Declared approvals could fail silently | Approval validation is shared in `effective/pointer.py`. Missing files, approval hash mismatch, candidate manifest SHA mismatch, and candidate effective digest mismatch produce an independent `approval_integrity_status`; `cmd_accept()` rejects every declared non-`MATCH` approval. Historical approvals without an effective digest remain valid when `candidate_effective_sha256` matches the manifest. Newly written approvals always include `candidate_effective_digest`. | Pointer tests cover candidate SHA, candidate digest, approval SHA, missing file, and historical fallback. The real accept path rejects missing, hash-mismatched, and digest-mismatched approvals. |
| 6. Accept did not consistently consume the hardened validators | `cmd_accept()` validates generated compare identity evidence, centralized manifest integrity/provenance, and any declared approval before conflict checks or pointer mutation. Window selection and command surface are unchanged. | Window intake tests exercise real compare generation and real accept calls. |

### Follow-up RED

The first focused run failed five tests for the missing central validator, missing pointer status fields, missing legacy SHA fallback behavior, missing approval status, and missing generated compare digest. A second focused run failed the mixed-evidence normalization assertion (`MIXED_EVIDENCE` versus `MIXED`).

### Follow-up GREEN

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_effective_manifest \
  src.lib_guard.test.test_effective_pointer \
  src.lib_guard.test.test_window_intake -q
```

Result: `Ran 40 tests` and `OK`.

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest discover \
  -s src/lib_guard/test -p 'test*.py' -q
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m compileall -q src
```

Result: full suite ran `378 tests` and `OK`; compileall exited `0`.

### Follow-up Changed Files

- `src/lib_guard/effective/manifest.py`
- `src/lib_guard/effective/pointer.py`
- `src/lib_guard/effective/compare.py`
- `src/lib_guard/window/cli.py`
- `src/lib_guard/test/test_effective_manifest.py`
- `src/lib_guard/test/test_effective_pointer.py`
- `src/lib_guard/test/test_window_intake.py`
- `.superpowers/sdd/task-4-report.md`

No command, page, dependency, or review-window selection policy was added or changed.

## Approval Manifest Path Equivalence Follow-up

`approval_integrity_for_manifest()` now accepts equivalent approval manifest references when one side is relative and the other absolute. Existing files are compared with `os.path.samefile()` first; unresolved references fall back to `Path.resolve(strict=False)`. Relative approval declarations are checked against both the current working directory and the approval file's directory, while distinct resolved paths remain mismatches.

### RED/GREEN

- Added regression coverage for relative approval declaration versus absolute validation path, and the reverse absolute declaration versus relative validation path.
- The two tests failed on the original direct `Path` comparison and passed after the focused fix.

### Verification

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_effective_pointer -q
```

Result: `Ran 10 tests` and `OK`.

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_effective_manifest \
  src.lib_guard.test.test_effective_pointer \
  src.lib_guard.test.test_window_intake -q
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m compileall -q src
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest discover \
  -s src/lib_guard/test -p 'test*.py' -q
```

Result: related modules ran `42 tests` and `OK`; compileall completed successfully; full suite ran `380 tests` and `OK`.
