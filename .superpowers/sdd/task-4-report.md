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

## Minimal Compare Intake Safety Follow-up

The accept validator now rejects an empty or non-object compare manifest, missing or invalid `old_target`/`new_target`, and an effective `new_target` with neither `effective_digest` nor `manifest_sha256`. Each error directs the operator to rebuild compare evidence before accepting the window. Validation remains before approval and pointer writes, so rejected compare evidence cannot create or replace either artifact.

New compare artifacts already produced by `effective/compare.py` contain both `effective_digest` and `manifest_sha256` for effective targets. The validator accepts either lock for compatibility with valid historical evidence, while still verifying any supplied lock against the candidate manifest.

### RED/GREEN

- Added one table-driven accept-path regression covering empty compare data, missing `old_target`, missing `new_target`, and an unlocked effective candidate; each case asserts approval absence and an unchanged current pointer.
- The new test failed before the validator change because all four cases could reach acceptance and write artifacts.
- After the change, the focused regression passed and the existing hand-written compare fixtures were updated with the required candidate manifest SHA where they represent valid acceptance evidence.

### Follow-up Verification

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_effective_manifest \
  src.lib_guard.test.test_effective_pointer \
  src.lib_guard.test.test_window_intake -q
```

Result: `Ran 43 tests` and `OK`.

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m compileall -q src
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest discover \
  -s src/lib_guard/test -p 'test*.py' -q
```

Result: compileall exited `0`; full suite ran `381 tests` and `OK`.

Changed for this follow-up: `src/lib_guard/window/cli.py`, `src/lib_guard/test/test_window_intake.py`, and this report. `fix.md` remains untracked and was not changed.

## Final Review Remediation

| Final review finding | Fix | Regression coverage |
| --- | --- | --- |
| An `effective -> effective` compare locked only the candidate, so replacing the old manifest in place with a different self-consistent identity could still be accepted. | `_validate_accept_compare()` now validates both effective targets: canonical target label, manifest path, manifest identity, `effective_digest`, and `manifest_sha256`. Missing locks direct the operator to rebuild compare evidence. Raw targets remain exempt from effective locks. | A real effective-to-effective compare replaces the old manifest at the same path with the same effective ID and a different digest while leaving pointer ID/revision unchanged; `cmd_accept()` rejects it. Normal first accept uses complete two-ended effective evidence. |
| Approval integrity did not bind the declared compare artifact. | `approval_integrity_for_manifest()` verifies a declared `compare_manifest` exists and its SHA-256 matches. A declared compare path without a SHA is `MISSING`; approvals with no compare declaration retain the established candidate-SHA fallback. | Pointer status changes from `MATCH` to `MISSING` after compare deletion and to `MISMATCH` after compare tampering. The real accept path rejects a tampered declared compare approval. |
| Malformed manifest `components` could reach identity construction and raise `AttributeError`. | `validate_effective_manifest()` validates that components is a non-string sequence of mappings before recomputing identity. | Mapping and non-mapping component sequences return `valid=False` and `integrity_status=MISMATCH` without raising. |

### RED/GREEN

- The focused final-review regressions failed on HEAD `1a3cfef`: malformed components raised `AttributeError`; a deleted declared compare artifact still returned `MATCH`; and a rebuilt old effective manifest was accepted.
- After the focused fixes, the three new regressions and the existing related coverage ran successfully (`46` tests).

### Final Verification

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_effective_manifest \
  src.lib_guard.test.test_effective_pointer \
  src.lib_guard.test.test_window_intake -q
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m compileall -q src
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest discover \
  -s src/lib_guard/test -p 'test*.py' -q
git diff --check
```

Result: related modules ran `46 tests` and `OK`; compileall exited `0`; the full suite ran `384 tests` and `OK`; `git diff --check` was clean.

## Latest Final Review Remediation

Baseline: `2cf3dd9`

| Final review finding | Fix | Regression coverage |
| --- | --- | --- |
| Dict compare targets with only `label`/`spec=effective:<id>` bypassed effective validation. | `_target_type()` now infers the type from `label`/`spec`, and `_validate_effective_compare_target()` infers the target ID from the same canonical label before requiring manifest, effective digest, and manifest SHA-256 locks. | Label-only and spec-only effective candidates are rejected instead of reaching accept; complete two-ended effective evidence remains valid. |
| Accept derived the expected revision from the live pointer, weakening compare-and-swap protection. | Resolver snapshots `pointer_revision` into `base_effective` (`0` without a pointer/raw baseline) and preserves it while a pending window remains open. `cmd_accept()` passes only the window's ID/revision expectations to `write_current_pointer()`. | First-window concurrent pointer creation and same-ID revision changes are rejected. Historical windows with an ID but no revision retain ID-only CAS; historical first accepts without ID/revision require revision `0` and still pass normally. |
| Digest-bearing approvals could return `MATCH` with incomplete candidate/compare evidence. | An approval with `candidate_effective_digest` now requires candidate manifest, candidate SHA-256, compare manifest, and compare SHA-256 before digest comparison. Historical approvals without the digest retain candidate-SHA fallback, and any declared compare still requires its SHA. | A table-driven test removes each required new-format field and requires `MISSING`; historical candidate-SHA and declared-compare behavior remains covered. |
| New approval paths were not guaranteed canonical, while historical relative compare paths had only one resolution base. | New approvals write resolved absolute candidate and compare paths. Historical relative compare paths are checked against both the current working directory and approval directory, with the declared SHA selecting the actual artifact; a different file is `MISMATCH`. | Approval output asserts canonical absolute paths. Relative compare tests cover both historical bases and reject a different file digest. |
| Normal and historical acceptance compatibility needed explicit protection after CAS and approval hardening. | No CLI, page, policy, or dependency was added. Existing ID-only pending windows and first-accept behavior use explicit compatibility branches. | Existing normal accept advances revision, the historical no-revision current-ID path passes, and a first accept without a pointer writes revision `1`. |

### Latest RED/GREEN

- Focused RED produced nine expected behavior failures plus two missing `pointer_revision` key errors: label/spec targets were accepted, live pointer revisions were trusted, digest-only approvals matched, cwd-relative compare references failed, and resolver windows lacked revision snapshots.
- After the minimal implementation and compatibility fixture updates, the related effective manifest, pointer, and window intake modules ran `51 tests` and passed.

### Latest Verification

```sh
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_effective_manifest \
  src.lib_guard.test.test_effective_pointer \
  src.lib_guard.test.test_window_intake -q
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m unittest discover \
  -s src/lib_guard/test -p 'test*.py' -q
PYTHONPYCACHEPREFIX=/tmp/ai_lib_pycache PYTHONPATH=src python3 -m compileall -q src
git diff --check
```

Result: related modules ran `51 tests` and `OK`; the full suite ran `389 tests` and `OK`; compileall and `git diff --check` exited `0`.

Changed for this remediation: `effective/pointer.py`, `window/cli.py`, `window/resolver.py`, `test_effective_pointer.py`, `test_window_intake.py`, and this report. `fix.md` remains untracked and unchanged.
