# Effective Library Intake Hardening Implementation Plan

Status: current

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make effective library intake deterministic: discovery only produces review candidates, confirmed catalog is the only source for normal catalog/scan/diff commands, and user-facing commands use formal library names plus version names.

**Architecture:** Keep the existing static-file architecture. `library_registry.py` owns candidate review and registry-to-catalog validation; `catalog/index.py` consumes confirmed catalog roots; `short_cli.py` exposes only formal library/version command names. Do not add a service, database, scheduler, agent workflow, or new mode system.

**Tech Stack:** Python standard library, existing unittest suite, current TSV/YAML/JSON/static HTML outputs.

---

## PD Vibe Guard Contract

**Target user:** library intake owner maintaining a raw IP library area.  
**Main judgement:** whether a directory is a confirmed library root and which versions can enter scan/diff.  
**Allowed input:** shallow directory structure, manually edited candidate/registry TSV, `library_catalog.yml`, existing `catalog.json`.  
**Allowed output:** candidate snapshot, formal catalog, library/version list, deterministic validation errors.  
**Forbidden expansions:** recursive catalog discovery during `cat`, automatic AI naming, deep parser during library discovery, multiple public ID schemes, full scan/diff refresh by default.

## Files

- Modify: `src/lib_guard/library_registry.py`
  - Upgrade ancestor/descendant OK roots from warning to validation error.
  - Reject negative library roots such as `source_package`, `lef`, `gds`, and `upstream_*` during apply, not only during discovery.
- Modify: `src/lib_guard/short_cli.py`
  - Make ambiguous alias guidance say “正式库名”, not internal `library_id`.
- Test: `src/lib_guard/test/test_library_registry.py`
  - Add regression tests for overlapping OK roots and source package roots.
- Test: `src/lib_guard/test/test_catalog_timeline.py`
  - Add ambiguous alias guidance regression test.

## Task 1: Registry Validation Blocks Poisoned Catalog Roots

- [x] **Step 1: Write failing tests**

Add tests that call `write_library_catalog()` with parent/child OK roots and with a `source_package` root. Expected result is `status == "FAILED"` with explicit errors.

- [x] **Step 2: Run registry tests to verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_library_registry -q
```

Expected: new tests fail because overlap is currently only a warning and negative roots are not rejected during apply.

- [x] **Step 3: Implement minimal validation**

Change `validate_library_rows()` so:

- Any selected root whose basename is a negative candidate directory is an error.
- Any selected root containing a negative path part under another selected root is still allowed only when the selected root itself is not the negative part. This keeps normal library roots valid while rejecting direct `source_package`/view roots.
- Any ancestor/descendant pair among OK rows is an error.

- [x] **Step 4: Run registry tests to verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_library_registry -q
```

Expected: `OK`.

## Task 2: User-Facing Name Guidance

- [x] **Step 1: Write/inspect failing assertion**

Check existing short CLI tests for ambiguous alias text. The expected message should tell users to use the formal library name, not internal `library_id`.

- [x] **Step 2: Implement minimal wording fix**

Change `_find_library()` ambiguity messages in short CLI and catalog resolver to:

```text
use formal library name
```

- [x] **Step 3: Run relevant tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline src.lib_guard.test.test_catalog_timeline -q
```

Expected: `OK`.

## Task 3: Final Validation

- [x] **Step 1: Compile changed modules**

Run:

```bash
PYTHONPATH=src python3 -m py_compile src/lib_guard/library_registry.py src/lib_guard/short_cli.py src/lib_guard/catalog/index.py
```

Expected: no output.

- [x] **Step 2: Run full unit suite**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p "test*.py" -q
```

Expected: `OK`. Known argparse output about rejected legacy scan modes may appear, but the process must exit 0.

## Self-Review

- Spec coverage: covers effective library root validation, catalog poisoning prevention, and public naming guidance.
- Placeholder scan: no placeholder steps.
- Scope check: no new architecture, no UI redesign, no scan/diff engine rewrite.
