Status: current

# Lib Guard Contract Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standardize configuration, command entry points, and run artifacts without changing the existing scan/diff/review/release workflow.

**Architecture:** Keep the current one-way fact pipeline and add contracts only at its boundaries. Existing dictionary configuration and historical JSON remain readable; new configuration and run manifests gain explicit versioned models and identifiers.

**Tech Stack:** Python 3.11 standard library, unittest, setuptools metadata, GitHub Actions.

## Global Constraints

- Do not add a database, plugin framework, scheduler, or second decision model.
- Do not change existing short-command names or historical artifact layouts.
- CLI arguments override workspace configuration; workspace configuration overrides code defaults.
- Generated HTML remains a rebuildable projection and never becomes a fact source.

---

### Task 1: Versioned workspace configuration

**Files:**
- Modify: `src/lib_guard/project_config.py`
- Modify: `src/lib_guard/short_cli_config.py`
- Test: `src/lib_guard/test/test_config_model.py`

**Interfaces:**
- Produces: `WorkspaceConfig`, `load_workspace_config()`, `merge_config_overrides()`.
- Preserves: `load_config()` returns the existing dictionary shape.

- [x] Add failing tests for `config_version`, typed access, and override precedence.
- [x] Run the focused test and confirm the missing-contract failures.
- [x] Add the minimal model and compatibility adapter.
- [x] Run the focused test to green.

### Task 2: Stable run artifact identity

**Files:**
- Modify: `src/lib_guard/artifacts.py`
- Create: `src/lib_guard/schemas/run_manifest.v1.schema.json`
- Test: `src/lib_guard/test/test_artifacts.py`

**Interfaces:**
- Produces: additive `producer`, `generated_at`, and `identity` fields.
- Preserves: existing `created_at` and nested `library` fields.

- [x] Add failing tests for normalized identity and schema coverage.
- [x] Run the focused test and confirm failure.
- [x] Implement additive manifest fields and checked identity values.
- [x] Run artifact tests to green.

### Task 3: Standard command and repository gates

**Files:**
- Create: `pyproject.toml`
- Create: `.github/workflows/ci.yml`
- Create: `.github/pull_request_template.md`
- Test: `src/lib_guard/test/test_architecture_invariants.py`

**Interfaces:**
- Produces: `lg` and `lib-guard` console entry points.
- Preserves: `scripts/lg.csh` as the intranet environment wrapper.

- [x] Add failing repository-contract tests.
- [x] Add minimal packaging metadata and CI/PR gates.
- [x] Verify both module and installed-style entry-point targets.

### Task 4: Documentation and complete verification

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/config_reference.md`
- Create: `docs/development.md`

- [x] Document ownership, precedence, compatibility, and Definition of Done.
- [x] Run compileall, focused tests, full unittest discovery, and both CLI help commands.
- [x] Run a real workspace read-only smoke test.
- [x] Review the final diff for unrelated changes and contract duplication.
