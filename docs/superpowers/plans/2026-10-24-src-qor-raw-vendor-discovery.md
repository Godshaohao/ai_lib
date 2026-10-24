# src_qor RAW Vendor Discovery Implementation Plan

> **For agentic workers:** Execute the checked steps in order and keep the focused tests green.

**Goal:** Restore the previous Catalog/Discover semantics for RAW library/version discovery and registration inside the standalone `src_qor` workbench.

**Architecture:** A small `src_qor` discovery module recursively finds candidate library roots whose direct children are delivery/version directories. It preserves the full relative path as Vendor, middle path, and library, plus each version path; view names come from filenames only. The workbench previews candidates, then explicitly registers selected libraries and their versions in its existing YAML IP registry; existing per-IP check execution remains unchanged.

**Tech Stack:** Python 3.11, Flask, PyYAML, pathlib, unittest, existing HTML/CSS/JavaScript.

## Global Constraints

- Keep the service standalone under `src_qor`; do not mount the legacy Catalog web app.
- RAW discovery is read-only; registration writes only the configured YAML registry.
- Do not copy RAW files, create links, calculate hashes, parse view contents, or alter release decisions.
- Accept libraries with one RAW version; preserve Vendor/middle_path/library hierarchy, all discovered version names, and absolute paths.
- Preserve all user-created untracked artifacts and unrelated source state.

---

### Task 1: RAW Inventory Discovery

**Files:**
- Create: `src_qor/lib_guard/raw_discovery.py`
- Test: `src_qor/test/test_raw_discovery.py`

**Interfaces:** `discover_raw_libraries(raw_root: str | Path) -> list[dict[str, Any]]`; each result contains `vendor`, `library_id`, `library_name`, `root`, and sorted `versions` entries (`id`, `path`, `views`).

- [x] Add fixtures for one-version and multi-version `Vendor/Library/Version/View/file` trees.
- [x] Verify non-view noise is ignored and discovery never writes beneath RAW.
- [x] Implement directory-level discovery with view suffix classification and deterministic sorting.
- [x] Run focused discovery tests (3 passed).

### Task 2: Registry Registration

**Files:**
- Modify: `src_qor/lib_guard/workbench.py`
- Test: `src_qor/test/test_workbench.py`

**Interfaces:** `POST /discover` previews a user-supplied root; `POST /register-discovered` registers selected library IDs and preserves discovered versions under each IP entry.

- [x] Test preview route, missing/invalid roots, one-version registration, multi-version registration, and duplicate registration refresh.
- [x] Implement route handlers with existing loopback-write protection and atomic YAML writes.
- [x] Ensure re-registration updates inventory paths/version list without replacing that IP's existing check configuration.
- [x] Run focused workbench tests.

### Task 3: Vendor / Library / Version UI

**Files:**
- Modify: `src_qor/lib_guard/templates/workbench.html`
- Modify: `src_qor/lib_guard/static/workbench.css`
- Modify: `src_qor/lib_guard/static/workbench.js`
- Test: `src_qor/test/test_workbench.py`
- Modify: `src_qor/README.md`

- [x] Add a RAW discovery tab with path input, preview, candidate selection, and explicit register action.
- [x] Render registered libraries grouped by Vendor, with version counts and per-version path/view summary.
- [x] Keep existing check configuration/history tabs and runner behavior intact.
- [x] Test navigation, selection controls, discover result rendering, and YAML persistence.
- [x] Run all `src_qor` tests and inspect the rendered page in a real browser; the available in-app viewport is ~300px wide, so desktop pixel-spacing validation remains limited.

## Validation

Run `PYTHONPATH=src_qor:<bundled-python-site-packages> python3 -m unittest discover -s src_qor/test -v` and confirm all tests pass. Also run `python3 -m compileall -q src_qor/lib_guard` and `node --check src_qor/lib_guard/static/workbench.js`.

## Completed Evidence

- `src_qor` regression: 34 tests passed.
- Actual RAW root `/home/polaris/proj/mx/ai_lib/3rd_IP`: discovered 2 Vendors, 2 libraries, 2 versions.
- Browser flow on isolated port 5084: preview did not register; selecting all registered both libraries and version paths; existing check workspace tab remained reachable.
- Browser test registry/output were isolated under `/tmp`; RAW and repository example data were not modified.
