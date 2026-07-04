Status: current

# lib_guard Boundary Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close existing `lib_guard` release/effective/review semantics without deleting force entry points or adding workflow/platform features.

**Architecture:** Keep the current CLI and JSON file workflow. Add small audit/explain helpers where needed, pass force metadata through existing manifest release paths, and move review-facing rules into review model helpers instead of render-only logic.

**Tech Stack:** Python standard library, existing `unittest` suite, existing static JSON/HTML outputs.

---

## Scope Contract

Target user: PD/lib owner reviewing whether a library version can be released or force-released.

Main judgement: Is release blocked, ready, force previewed, force applied, or physically failed, and what evidence explains that judgement?

Allowed input: Existing catalog JSON, release manifest JSON, review gate JSON, release check JSON, action files, current effective pointer files.

Allowed output: Small Python/source-doc changes, release audit JSON, release explain JSON, canonical latest effective ref fields, review gate explanation fields.

Forbidden expansions: No database, no approval workflow, no workflow engine, no project lock, no parser platform, no generated HTML edits, no deletion of `--force`, `--force-reason`, `@rerelease`, or `@ALL redo`.

## File Map

- Modify `src/lib_guard/release/linker.py`: add manifest-driven force parameters, statuses, force override audit, and verify metadata passthrough.
- Modify `src/lib_guard/cli.py`: expose `--force-by` and `--explain` only on existing release commands.
- Modify `src/lib_guard/cli_commands/catalog.py`: pass force metadata to manifest linker; record verify skip; call explain helper for release-check.
- Modify `src/lib_guard/short_cli.py`: expand `rel --force-by` and `rel --explain`; freeze action output audit for `@ALL redo`.
- Modify `src/lib_guard/release/result.py`: include force metadata and verify skip fields in unified release result.
- Create `src/lib_guard/release/explain.py`: pure JSON summarizer for release-check/link failure reasons.
- Modify `src/lib_guard/effective/pointer.py`: add canonical latest effective ref helper functions.
- Modify `src/lib_guard/render/catalog_report.py`, `src/lib_guard/render/catalog_workspace_report.py`, `src/lib_guard/render/version_detail_report.py`, `src/lib_guard/review/state.py`, `src/lib_guard/effective/cli.py`: read latest effective refs through helpers and avoid new ad hoc fallback logic.
- Create `src/lib_guard/review/model_rules.py`: hold review base/lane/comparison rules migrated from renderer.
- Modify `docs/command_surface.md`, `docs/manual_confirmation_action.md`, `docs/review_gate.md`, `docs/user_guide.md`, `README.md`: document force audit, frozen action syntax, review gate explanations.
- Add tests under `src/lib_guard/test/`: `test_release_force_manifest.py`, `test_short_cli_force.py`, `test_effective_pointer.py`, and targeted updates to existing review/catalog tests.

---

### Task 1: Manifest Force Release Audit

**Files:**
- Modify: `src/lib_guard/release/linker.py`
- Modify: `src/lib_guard/release/result.py`
- Test: `src/lib_guard/test/test_release_force_manifest.py`

- [ ] **Step 1: Write failing force manifest tests**

Add tests covering:

```python
with self.assertRaisesRegex(ValueError, "force release requires --force-reason"):
    link_release_from_manifest(manifest_path, force=True)

dry = link_release_from_manifest(manifest_path, force=True, force_reason="owner accepted", force_by="shenhao")
self.assertEqual(dry["status"], "FORCE_DRY_RUN")
self.assertTrue((run_dir / "release_override.json").exists())

applied = link_release_from_manifest(manifest_path, apply=True, mode="copy", force=True, force_reason="owner accepted", force_by="shenhao")
self.assertEqual(applied["status"], "FORCED_APPLIED")
self.assertEqual(json.loads((run_dir / "release_result.json").read_text())["force_by"], "shenhao")
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m unittest src.lib_guard.test.test_release_force_manifest`

Expected: fail because `link_release_from_manifest` has no `force` parameters.

- [ ] **Step 3: Implement minimal manifest force parameters**

In `link_release_from_manifest`, add keyword-only parameters:

```python
force: bool = False,
force_reason: str | None = None,
force_by: str | None = None,
review_gate_path: str | Path | None = None,
release_check_path: str | Path | None = None,
verify_skipped: bool = False,
verify_skip_reason: str = "",
```

Rules:
- `force and not force_reason` raises `ValueError("force release requires --force-reason")`.
- `force_by = force_by or os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"`.
- `force and not apply` writes `FORCE_DRY_RUN`.
- `force and apply and failed_links` writes `FORCE_FAILED`.
- `force and apply and not failed_links` writes `FORCED_APPLIED`.

- [ ] **Step 4: Write `release_override.json`**

When `force=True`, write `<run_dir>/release_override.json` with:

```python
{
    "schema_version": "release_override.v1",
    "force": True,
    "force_reason": force_reason,
    "force_by": force_by,
    "force_at": utc_now(),
    "apply": bool(apply),
    "dry_run": not bool(apply),
    "release_id": manifest.get("release_id"),
    "alias": manifest.get("alias"),
    "manifest_path": str(Path(manifest_path)),
    "review_gate_path": str(review_gate_path or ""),
    "release_check_path": str(release_check_path or ""),
    "bypassed_gate_summary": _force_gate_summary(review_gate_path, release_check_path),
    "selected_versions": _force_selected_versions(manifest),
}
```

- [ ] **Step 5: Include force fields in link result and release result**

`release_link_result.json` and `release_result.json` must include:

```python
"force": bool(force),
"force_reason": force_reason or "",
"force_by": force_by if force else "",
"override_path": str(override_path) if force else "",
"verify_skipped": bool(verify_skipped),
"verify_skip_reason": verify_skip_reason,
```

- [ ] **Step 6: Verify**

Run:

```bash
python -m unittest src.lib_guard.test.test_release_force_manifest
python -m unittest src.lib_guard.test.test_release_manifest_flow
```

Expected: all pass.

---

### Task 2: CLI Force Pass-Through

**Files:**
- Modify: `src/lib_guard/cli.py`
- Modify: `src/lib_guard/cli_commands/catalog.py`
- Modify: `src/lib_guard/short_cli.py`
- Test: `src/lib_guard/test/test_short_cli_force.py`

- [ ] **Step 1: Write failing CLI tests**

Add tests asserting:

```python
commands = build_cli_commands([
    "rel", "ucie", "stable_20250608",
    "--force", "--force-reason", "owner accepted", "--force-by", "shenhao",
], cwd=workspace)
self.assertIn("--force", commands[-1])
self.assertIn("--force-reason", commands[-1])
self.assertIn("--force-by", commands[-1])
```

Patch `lib_guard.release.linker.link_release_from_manifest` in `run_catalog_release_batch` and assert `force=True`, `force_reason="owner accepted"`, `force_by="shenhao"`, `verify_skipped=True` when `--no-verify` is used.

- [ ] **Step 2: Add CLI args**

Add:

```python
p.add_argument("--force-by", help="User name for force release audit. Defaults to USER/USERNAME.")
p.add_argument("--explain", action="store_true", help="Print release-check explanation JSON without applying release.")
```

Use `--force-by` on `release-batch`, `catalog release-link`, and short `rel`.

- [ ] **Step 3: Pass force args to linker**

In `run_catalog_release_link` and `run_catalog_release_batch`, pass:

```python
force=bool(args.force),
force_reason=getattr(args, "force_reason", None),
force_by=getattr(args, "force_by", None),
verify_skipped=bool(getattr(args, "no_verify", False)),
verify_skip_reason="no_verify requested" if getattr(args, "no_verify", False) else "",
```

- [ ] **Step 4: Expand short command**

In `short_cli.py`, add:

```python
if args.force_by:
    command.extend(["--force-by", args.force_by])
if args.explain:
    check_cmd.append("--explain")
```

Do not remove `--force` or `--force-reason`.

- [ ] **Step 5: Verify**

Run:

```bash
python -m unittest src.lib_guard.test.test_short_cli_force
python -m unittest src.lib_guard.test.test_review_gate
```

Expected: all pass.

---

### Task 3: Release Explain JSON

**Files:**
- Create: `src/lib_guard/release/explain.py`
- Modify: `src/lib_guard/cli_commands/catalog.py`
- Modify: `src/lib_guard/short_cli.py`
- Test: `src/lib_guard/test/test_release_explain.py`

- [ ] **Step 1: Write failing explain test**

Test `explain_release_check` with a blocked review gate:

```python
explain = explain_release_check({
    "release_check_status": "BLOCK",
    "review_gate": {"status": "REVIEW_REQUIRED", "blocking_items": [{"id": "metadata.db.changed:db/ucie.db", "category": "metadata_only", "title": "Metadata-only view changed", "message": "DB changed", "next_action": "rv-accept or force release"}]},
    "library_name": "ucie",
    "version": "stable_20250608",
})
self.assertEqual(explain["failed_phase"], "REVIEW_GATE_BLOCKED")
self.assertTrue(explain["blockers"])
self.assertTrue(explain["safe_actions"])
self.assertTrue(explain["force_actions"])
```

- [ ] **Step 2: Implement pure helper**

Create:

```python
def explain_release_check(result: Mapping[str, Any]) -> dict[str, Any]:
    ...
```

No file writes, no release action. Classify at least: `REVIEW_GATE_BLOCKED`, `RELEASE_CHECK_BLOCKED`, `MANIFEST_SOURCE_MISSING`, `TARGET_EXISTS`, `PERMISSION_DENIED`, `LINK_FAILED`, `VERIFY_FAILED`, `UNKNOWN`.

- [ ] **Step 3: Wire `--explain`**

If `catalog release-check --explain` is set, print explanation JSON instead of raw check result. Short `rel --check-first --explain` expands to release-check with `--explain`.

- [ ] **Step 4: Verify**

Run:

```bash
python -m unittest src.lib_guard.test.test_release_explain
python -m lib_guard.short_cli --help
```

Expected: `--explain` is visible for `rel`.

---

### Task 4: Canonical Latest Effective Ref

**Files:**
- Modify: `src/lib_guard/effective/pointer.py`
- Modify: `src/lib_guard/render/catalog_report.py`
- Modify: `src/lib_guard/render/catalog_workspace_report.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Modify: `src/lib_guard/review/state.py`
- Modify: `src/lib_guard/effective/cli.py`
- Test: `src/lib_guard/test/test_effective_pointer.py`
- Test: `src/lib_guard/test/test_effective_manifest.py`

- [ ] **Step 1: Write helper tests**

Assert:

```python
self.assertEqual(normalize_effective_ref("stable_20250608"), "raw:stable_20250608")
self.assertEqual(normalize_effective_ref("raw:stable_20250608"), "raw:stable_20250608")
self.assertEqual(normalize_effective_ref("effective:E1"), "effective:E1")
```

Also assert `write_latest_effective_ref(catalog, library_id, "effective:E1")` writes only `library["summary"]["latest_effective_ref"]`.

- [ ] **Step 2: Implement helpers**

Add:

```python
def normalize_effective_ref(value: str) -> str: ...
def latest_effective_ref_for_library(lib: Mapping[str, Any]) -> str: ...
def write_latest_effective_ref(catalog: Mapping[str, Any], library_id: str, ref: str) -> dict[str, Any]: ...
```

Compatibility reads may look at old fields, but new writes must only target `library.summary.latest_effective_ref`.

- [ ] **Step 3: Replace local fallback reads**

Use `latest_effective_ref_for_library` where render/short/review code currently guesses among `current_effective`, `current_version`, and `latest_effective_ref`.

- [ ] **Step 4: Verify**

Run:

```bash
python -m unittest src.lib_guard.test.test_effective_pointer src.lib_guard.test.test_effective_manifest
```

Expected: all pass; update expected refs to `raw:<id>` or `effective:<id>` where this is newly written canonical output.

---

### Task 5: Action Syntax Freeze Audit

**Files:**
- Modify: `src/lib_guard/short_cli.py`
- Modify: `docs/manual_confirmation_action.md`
- Test: `src/lib_guard/test/test_scan_pipeline.py`

- [ ] **Step 1: Add action audit test**

Extend existing action test so `@ALL redo` result includes:

```python
"force_all_redo": True
"source": "@ALL redo"
"warning": "All existing outputs may be regenerated."
```

- [ ] **Step 2: Implement action plan metadata**

In `_parse_review_actions`, keep existing verbs only and add metadata for `@ALL redo`. In action dry-run/output, include an action plan object with `force_all_redo`.

- [ ] **Step 3: Document frozen verbs**

In `docs/manual_confirmation_action.md`, list retained verbs and explicitly disallow workflow verbs such as `@if`, `@depends`, `@retry`, `@group`, `@include`, `@owner`, `@approve`, `@loop`, `@notify`.

- [ ] **Step 4: Verify**

Run:

```bash
python -m unittest src.lib_guard.test.test_scan_pipeline.ScanPipelineTest.test_short_cli_action_all_redo_forces_every_action
```

Expected: pass.

---

### Task 6: Review Gate Explanation Fields

**Files:**
- Modify: `src/lib_guard/review/state.py`
- Modify: `docs/review_gate.md`
- Test: `src/lib_guard/test/test_review_gate.py`

- [ ] **Step 1: Write failing tests**

Assert every blocking item and attention item has:

```python
for key in ["rule_id", "rule_source", "why", "next_action"]:
    self.assertIn(key, item)
```

- [ ] **Step 2: Extend `_gate_item`**

Add optional parameters:

```python
rule_id: str = "",
rule_source: str = "review_gate.v1",
why: str = "",
next_action: str = "",
```

Default them from category/title when needed so no item is blank.

- [ ] **Step 3: Add explicit metadata and pairwise rules**

Metadata-only blocker:

```python
rule_id="metadata_only.changed.blocks_current"
why="DB/GDS/OAS are metadata-only in default scan; semantic safety cannot be proven automatically."
next_action="Owner accept/waive or release with --force and audit reason."
```

Pairwise attention:

```python
rule_id="pairwise.recommended.attention"
why="Focused file diff is useful evidence but not mandatory for current by default."
next_action="Run lg fd for recommended P0/P1 files when needed."
```

- [ ] **Step 4: Verify**

Run:

```bash
python -m unittest src.lib_guard.test.test_review_gate
```

Expected: pass.

---

### Task 7: Render Rule Extraction

**Files:**
- Create: `src/lib_guard/review/model_rules.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Test: `src/lib_guard/test/test_version_detail_report.py`
- Test: `src/lib_guard/test/test_repository_cleanup.py`

- [ ] **Step 1: Add model rule tests**

Test:

```python
self.assertEqual(resolve_review_base(version)["base_ref"], "current_effective")
self.assertEqual(classify_review_lane("db")["lane"], "metadata_only")
self.assertEqual(comparison_semantics_for_package("PARTIAL_UPDATE")["comparison_scope"], "incremental")
```

- [ ] **Step 2: Create `model_rules.py`**

Move the logic behind `_select_base`, `_review_lane`, and `_comparison_semantics` into:

```python
def resolve_review_base(version: Mapping[str, Any], library: Mapping[str, Any] | None = None) -> dict[str, Any]: ...
def classify_review_lane(file_type: str) -> dict[str, str]: ...
def comparison_semantics_for_package(package_type: str, node_kind: str = "") -> dict[str, str]: ...
```

- [ ] **Step 3: Keep renderer as renderer**

`version_detail_report.py` should call these helpers and keep HTML assembly only. Do not edit generated reports.

- [ ] **Step 4: Verify**

Run:

```bash
python -m unittest src.lib_guard.test.test_version_detail_report src.lib_guard.test.test_repository_cleanup
```

Expected: pass.

---

### Task 8: Documentation And Final Verification

**Files:**
- Modify: `docs/command_surface.md`
- Modify: `docs/manual_confirmation_action.md`
- Modify: `docs/review_gate.md`
- Modify: `docs/user_guide.md`
- Modify: `README.md`

- [ ] **Step 1: Update docs**

Document:
- force retained and requires reason.
- `release-batch` supports force and writes `release_override.json`.
- `rel --explain` explains blocked release without applying release.
- action syntax frozen while retaining `@rerelease` and `@ALL redo`.
- review gate is technical blocker evidence, not approval workflow.

- [ ] **Step 2: Run acceptance commands**

Run:

```bash
python -m py_compile src/lib_guard/short_cli.py src/lib_guard/cli.py src/lib_guard/cli_commands/catalog.py src/lib_guard/release/linker.py src/lib_guard/release/result.py
python -m unittest discover -s src/lib_guard/test -p "test*.py"
python -m lib_guard.cli --help
python -m lib_guard.short_cli --help
python -m lib_guard.short_cli --dry-run rel ucie stable_20250608 --force --force-reason "owner accepted metadata-only change" --force-by shenhao
git diff --check
```

Expected: all pass; dry-run command includes `release-batch`, `--force`, `--force-reason`, and `--force-by`.

## Self-Review

Spec coverage:
- P0-1 covered by Task 1.
- P0-2 force pass-through covered by Task 2.
- P0-3 release explain covered by Task 3.
- P0-4 latest effective ref covered by Task 4.
- P1-2 action syntax freeze covered by Task 5.
- P1-3 review gate explanation covered by Task 6.
- P1-4 render rule extraction covered by Task 7.
- Documentation and final validation covered by Task 8.

Placeholder scan: no TBD/TODO/implement-later placeholders remain.

Type consistency: force fields use `force`, `force_reason`, `force_by`, `override_path`; effective refs use `raw:<id>` and `effective:<id>`; review gate fields use `rule_id`, `rule_source`, `why`, `next_action`.
