# Lib Guard Web MVP Implementation Plan

Status: current

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a small Flask desktop console that reads the existing catalog/runtime facts, exposes safe scan/compare/release-check actions, and links to the existing Version Detail projection.

**Architecture:** Flask is the only runtime server. The web package reads existing catalog/runtime artifacts and starts only allow-listed `lib_guard.short_cli` actions; it does not create a second fact model or invoke arbitrary shell commands. HTML/CSS/JavaScript are served as static assets from the Python package; Node.js is optional and not required to run the MVP.

**Tech Stack:** Python 3, Flask 3.0.3, existing `lib_guard` modules, HTML/CSS/vanilla JavaScript.

## Global Constraints

- Keep `catalog.json`, `catalog_runtime.json`, `scan_out`, `diff`, `effective`, `release`, and `run_manifest.json` as the only business facts.
- Do not add a database, background scheduler, WebSocket layer, authentication system, or a second Version Detail page.
- Do not expose arbitrary shell execution; web actions must use a fixed allow-list and validated path values.
- Keep the first screen desktop-oriented and Chinese-first.
- Web actions return a job ID and persist request/status/log data under the configured workspace.
- Workflow actions are explicit and separated into preview (`next`, `intake`, `window`) and write (`accept-window`, `mark`, `override`) operations.

---

### Task 1: Web read model and API contract

**Files:**
- Create: `src/lib_guard/web/__init__.py`
- Create: `src/lib_guard/web/read_model.py`
- Create: `src/lib_guard/test/test_web_read_model.py`

**Interfaces:**
- `load_web_state(config_path=None, cwd=None) -> dict[str, Any]`
- `list_library_rows(state) -> list[dict[str, Any]]`
- `list_version_rows(state, library_name) -> list[dict[str, Any]]`

- [ ] **Step 1: Write failing tests**

Test the existing smoke catalog fixture: library rows preserve formal names, version rows expose scan/diff/release status, and missing catalog paths return a clear error.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:
```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_web_read_model -q
```
Expected: import failure because `lib_guard.web.read_model` does not exist.

- [ ] **Step 3: Implement the read-only model**

Use `load_config()` and `load_catalog_view()`. Normalize only display fields; retain source paths and runtime status as returned facts. Do not scan RAW or discover libraries from the Web request.

- [ ] **Step 4: Run focused tests**

Expected: all read-model tests pass.

### Task 2: Flask application and safe action jobs

**Files:**
- Create: `src/lib_guard/web/app.py`
- Create: `src/lib_guard/test/test_web_app.py`
- Create: `requirements-web.txt`

**Interfaces:**
- `create_app(config_path=None, cwd=None, *, test_config=None) -> Flask`
- `POST /api/libraries/<library>/versions/<version>/scan`
- `POST /api/libraries/<library>/versions/<version>/compare`
- `POST /api/libraries/<library>/versions/<version>/release-check`
- `GET /api/runs/<job_id>`

- [ ] **Step 1: Write failing API tests**

Cover:
1. `GET /api/health` returns `PASS`.
2. `GET /api/libraries` returns formal library names.
3. Missing library returns HTTP 404.
4. Scan accepts only the version from the catalog and creates a job request.
5. Unknown action is not executable through the API.

- [ ] **Step 2: Run focused tests and verify failure**

Run the same unittest target. Expected: import failure because the Flask app is absent.

- [ ] **Step 3: Implement the minimal Flask app**

Use a fixed action map to existing short CLI command builders or the existing Python command entrypoint. Persist each request under `<workspace>/web_jobs/<job_id>/request.json` and status under `status.json`. Return `202` with `job_id`; do not wait synchronously for scan/cmp.

- [ ] **Step 4: Implement safe path and state validation**

Resolve the library/version through `load_web_state()` before writing a job. Reject path traversal, unknown versions, and arbitrary command names. Store command arguments as a JSON list for audit, never as a shell string.

- [ ] **Step 5: Run focused tests**

Expected: API tests pass with Flask 3.0.3.

### Task 3: Desktop console UI

**Files:**
- Create: `src/lib_guard/web/templates/index.html`
- Create: `src/lib_guard/web/static/app.js`
- Create: `src/lib_guard/web/static/styles.css`
- Modify: `src/lib_guard/web/app.py`
- Create: `src/lib_guard/test/test_web_ui_contract.py`

**Interfaces:**
- `GET /` serves the desktop console shell.
- JavaScript reads `/api/libraries` and `/api/libraries/<library>/versions`.
- Version Detail links point to existing generated HTML paths, never to a new review projection.

- [ ] **Step 1: Write UI contract tests**

Assert that the shell contains Chinese labels for library, version, scan status, compare status, current effective, and actions; it contains no arbitrary-command input; and the page exposes a bounded table container for large version lists.

- [ ] **Step 2: Run UI contract tests and verify failure**

Expected: template/static files are missing.

- [ ] **Step 3: Build the desktop-first layout**

Use a restrained engineering-console visual language: light neutral canvas, dark ink text, one amber action accent, compact typography, fixed-height scrollable tables, and clear status chips. Avoid marketing hero sections and decorative cards.

- [ ] **Step 4: Add interactions**

Library selection loads versions; version selection shows scan/diff/release facts and available Version Detail link; action buttons submit fixed API requests and show job status. No automatic scan or full catalog refresh occurs on page load.

- [ ] **Step 5: Run UI contract tests**

Expected: all UI contract assertions pass.

### Task 4: Documentation and integration verification

**Files:**
- Modify: `docs/basic_tutorial.md`
- Modify: `docs/architecture.md`
- Create: `docs/web_console_checklist.md`

- [ ] **Step 1: Document startup and boundaries**

Document dependency installation, `PYTHONPATH=src python3 -m lib_guard.web.app --config ...`, the read-only nature of page load, action job files, and the fact that Version Detail remains the only review projection.

- [ ] **Step 2: Run module, API, and real fixture smoke tests**

Run:
```bash
PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q
PYTHONPATH=src python3 -m compileall -q src
```

Then start the app against `work/single_library_smoke_20260805/lib_guard.yml`, request the health endpoint, list libraries, open a version, and verify the existing Version Detail HTML link.

- [ ] **Step 3: Run anti-overengineering review**

Confirm no database, scheduler, arbitrary shell route, new fact source, second review page, or automatic full refresh was introduced.

### Verification record

- `PYTHONPATH=src:work/web_deps python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q`: 530 tests passed.
- `PYTHONPATH=src:work/web_deps python3 -m compileall -q src/lib_guard/web`: passed.
- `node --check src/lib_guard/web/static/app.js`: passed.
- Browser smoke at `http://127.0.0.1:5055/`: library/version selection, status filtering, strategy controls, workflow controls, and desktop layout verified.
