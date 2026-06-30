# Version Review Reliability Experience Implementation Plan

Status: current

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Version Detail trust, evidence readability, and expert opt-in behavior without changing the main Catalog -> Version Review -> Release workflow.

**Architecture:** Keep Version Detail as the normal reviewer entry. Add model fields and renderer sections that make base trust, summary-only evidence, metadata-only evidence, view/type/release evidence, and next actions visible in the primary update panel. Split shared render helpers into `catalog_render_common.py` so `catalog_workspace_report.py` and `version_detail_report.py` no longer import `catalog_report.py` private helpers.

**Tech Stack:** Python 3.11 standard library, `unittest`, static HTML renderer helpers in `product_theme.py`, JSON diff artifacts, `scripts/lg.csh` / `lib_guard.short_cli`.

---

## Scope Check

This is one product surface: Version Review reliability and reviewer confidence. It touches three coupled areas:

- Version Detail model and renderer.
- Short CLI expert File Diff opt-in.
- Render helper dependency boundaries.

Do not change the main flow, catalog discovery, pairwise default generation policy, release gate policy, or OpenROAD fixture content. This plan deliberately keeps UI changes inside Version Detail's update panel and helper extraction inside render modules.

## File Structure

Create or modify these files:

- Create: `src/lib_guard/render/catalog_render_common.py`
  - Shared render/data helpers that are not page owners.
- Modify: `src/lib_guard/render/catalog_report.py`
  - Import shared helpers from `catalog_render_common.py`; remain catalog facade/state adapter.
- Modify: `src/lib_guard/render/catalog_workspace_report.py`
  - Import shared helpers from `catalog_render_common.py`; stop using `_cr()` for migrated common helpers.
- Modify: `src/lib_guard/render/version_detail_report.py`
  - Add headline/confidence/action model fields, lane-specific evidence groups, trust/status copy, evidence summary sections, and Markdown parity.
- Modify: `src/lib_guard/short_cli.py`
  - Add `--force-large` expert opt-in for summary-only and metadata-only file types.
- Modify: `docs/cli_reference.md`
  - Document safe default fd lanes and `--force-large`.
- Modify: `docs/data_contract.md`
  - Document `headline`, `confidence_note`, `primary_next_action`, update-lane groups, and status copy.
- Modify: `src/lib_guard/test/test_version_detail_report.py`
  - Add model/render/Markdown tests for Version Detail evidence and trust behavior.
- Modify: `src/lib_guard/test/test_pairwise_policy.py`
  - Add expert `fd --force-large` tests and ensure pairwise defaults remain unchanged.
- Modify: `src/lib_guard/test/test_repository_cleanup.py`
  - Add guard that workspace/detail renderers do not import `catalog_report` private helpers after common split.
- Modify: `src/lib_guard/test/test_scan_pipeline.py`
  - Extend help/docs checks for `--force-large` and safe default fd lane text.

## Commit Policy

Commit after every task:

```bash
git commit -m "test: cover version detail evidence grouping"
git commit -m "feat: add version detail headline and trust context"
git commit -m "feat: split update evidence panels"
git commit -m "feat: allow expert file diff opt in"
git commit -m "refactor: split catalog render common helpers"
git commit -m "feat: surface view release diff evidence"
git commit -m "docs: document version review reliability flow"
git commit -m "test: add final reliability guardrails"
```

## Shared Test Fixture

Several tasks use this helper in `src/lib_guard/test/test_version_detail_report.py`. Add it near the top of the test class in Task 1.

```python
    def _write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _diff_fixture(self, root: Path) -> tuple[Path, dict, dict]:
        diff_dir = root / "diff"
        self._write_json(
            diff_dir / "diff_summary.json",
            {
                "status": "DIFF",
                "changed_files": 7,
                "added_files": 1,
                "removed_files": 1,
                "view_changes": 2,
                "type_changes": 3,
                "release_evidence_changes": 1,
                "recommended_actions": ["Run recommended File Diff"],
            },
        )
        self._write_json(
            diff_dir / "file_diff.json",
            {
                "changed": [
                    {"path": "lef/top.lef", "file_type": "lef"},
                    {"path": "rtl/top.v", "file_type": "verilog"},
                    {"path": "timing/top.lib", "file_type": "liberty"},
                    {"path": "parasitics/top.spef", "file_type": "spef"},
                    {"path": "db/top.db", "file_type": "db"},
                    {"path": "layout/top.gds", "file_type": "gds"},
                    {"path": "layout/top.oas", "file_type": "oas"},
                ],
                "added": [{"path": "constraints/top.sdc", "file_type": "sdc"}],
                "removed": [],
            },
        )
        self._write_json(
            diff_dir / "view_diff.json",
            {"summary": {"changed": 2}, "changed": [{"view": "lef"}, {"view": "timing"}]},
        )
        self._write_json(
            diff_dir / "type_diff.json",
            {"summary": {"changed_types": 3}, "changed": [{"file_type": "lef"}, {"file_type": "liberty"}, {"file_type": "db"}]},
        )
        self._write_json(
            diff_dir / "release_readiness_diff.json",
            {"status": "REGRESSED", "regressions": [{"check": "required_view_status", "from": "PASS", "to": "WARNING"}]},
        )
        self._write_json(
            diff_dir / "release_evidence_diff.json",
            {"status": "DIFF", "changed": [{"artifact": "release_readiness.json"}]},
        )
        self._write_json(
            diff_dir / "diff_issues.json",
            {
                "issues": [
                    {"severity": "blocking", "category": "base_trust", "title": "Base requires confirmation"},
                    {"severity": "warning", "category": "view_diff", "title": "Timing view changed"},
                ]
            },
        )
        lib = {"library_id": "ip/ucie", "library_name": "ucie"}
        version = {
            "version_id": "patch_20260630",
            "current_effective_ref": "effective_20260620",
            "diff": {"current_effective_diff_dir": str(diff_dir)},
        }
        return diff_dir, lib, version
```

## Task 1: Version Detail Lane Group Regression Tests

**Files:**
- Modify: `src/lib_guard/test/test_version_detail_report.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Test: `src/lib_guard/test/test_version_detail_report.py`

- [ ] **Step 1: Add failing lane grouping test**

Add this test to `VersionDetailReportTest` after the existing base-selection tests:

```python
    def test_summary_only_and_metadata_only_are_rendered_separately(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _diff_dir, lib, version = self._diff_fixture(root)

            from lib_guard.render.version_detail_report import build_version_update_detail_model, render_version_update_detail_panel

            model = build_version_update_detail_model(root / "html", lib, version)
            html = render_version_update_detail_panel(model)

            self.assertEqual([item["path"] for item in model["recommended_file_diff"]], ["lef/top.lef", "constraints/top.sdc"])
            self.assertEqual(
                [item["path"] for item in model["summary_only_reviewed"]],
                ["rtl/top.v", "timing/top.lib", "parasitics/top.spef"],
            )
            self.assertEqual(
                [item["path"] for item in model["metadata_only_reviewed"]],
                ["db/top.db", "layout/top.gds", "layout/top.oas"],
            )
            self.assertIn("Recommended File Diff", html)
            self.assertIn("Summary-only Reviewed", html)
            self.assertIn("Metadata-only Reviewed", html)
            self.assertIn("已完成摘要级审查；默认无需展开全文。", html)
            self.assertIn("已完成 metadata-only 审查；二进制/版图文件默认不做全文 diff。", html)
            summary_section = html.split("Summary-only Reviewed", 1)[1].split("Metadata-only Reviewed", 1)[0]
            metadata_section = html.split("Metadata-only Reviewed", 1)[1]
            self.assertNotIn("未生成 File Diff", summary_section)
            self.assertNotIn("未生成 File Diff", metadata_section)
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
cd /home/polaris/proj/mx/ai_lib/repo
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_summary_only_and_metadata_only_are_rendered_separately -q
```

Expected: FAIL because `recommended_file_diff`, `summary_only_reviewed`, and `metadata_only_reviewed` are not in the model.

- [ ] **Step 3: Add lane grouping helpers**

In `src/lib_guard/render/version_detail_report.py`, add these helpers after `_file_diff_commands`:

```python
def _file_change_evidence(item: Mapping[str, Any]) -> str:
    file_type = str(item.get("file_type") or "-").lower()
    path = str(item.get("path") or "-")
    if file_type in SUMMARY_ONLY_TYPES:
        return f"summary evidence: type={file_type}; path={path}"
    if file_type in BINARY_METADATA_ONLY_TYPES:
        return f"metadata evidence: type={file_type}; hash/size/path/count from scan and diff artifacts"
    return f"file diff evidence: type={file_type}; path={path}"


def _group_update_file_changes(changes: list[dict[str, Any]], recommendations: list[dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    command_by_path = {str(item.get("path") or ""): str(item.get("command") or "") for item in recommendations}
    grouped = {
        "recommended_file_diff": [],
        "summary_only_reviewed": [],
        "metadata_only_reviewed": [],
    }
    for item in changes:
        file_type = str(item.get("file_type") or "").lower()
        row = dict(item)
        row["reason"] = str(item.get("hint") or "-")
        row["summary_evidence"] = _file_change_evidence(item)
        row["metadata_evidence"] = _file_change_evidence(item)
        row["command"] = command_by_path.get(str(item.get("path") or ""), "")
        if str(item.get("review_lane") or "") in {"P0", "P1"}:
            grouped["recommended_file_diff"].append(row)
        elif file_type in SUMMARY_ONLY_TYPES:
            grouped["summary_only_reviewed"].append(row)
        elif file_type in BINARY_METADATA_ONLY_TYPES:
            grouped["metadata_only_reviewed"].append(row)
    return grouped
```

In `build_version_update_detail_model()`, replace:

```python
metadata_only = [item for item in file_changes if item.get("review_lane") in {"Metadata-only", "Summary-only"}]
commands = _file_diff_commands(lib, version, base_version, file_changes)
```

with:

```python
commands = _file_diff_commands(lib, version, base_version, file_changes)
file_groups = _group_update_file_changes(file_changes, commands)
metadata_only = file_groups["metadata_only_reviewed"] + file_groups["summary_only_reviewed"]
```

Add these model fields before `"metadata_only_changes"`:

```python
        "recommended_file_diff": file_groups["recommended_file_diff"],
        "summary_only_reviewed": file_groups["summary_only_reviewed"],
        "metadata_only_reviewed": file_groups["metadata_only_reviewed"],
```

- [ ] **Step 4: Add renderer rows**

In `version_detail_report.py`, add after `_file_change_rows()`:

```python
def _recommended_file_diff_rows(model: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in model.get("recommended_file_diff", []) or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td>{ui.badge(item.get('review_lane') or 'P1', item.get('review_lane') or 'P1')}</td>"
            f"<td><code>{ui.esc(item.get('file_type') or '-')}</code></td>"
            f"<td><code>{ui.esc(item.get('path') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('reason') or '-')}</td>"
            f"<td><code>{ui.esc(item.get('command') or '-')}</code></td>"
            "</tr>"
        )
    return rows


def _summary_only_rows(model: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in model.get("summary_only_reviewed", []) or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('file_type') or '-')}</code></td>"
            f"<td><code>{ui.esc(item.get('path') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('summary_evidence') or '-')}</td>"
            f"<td>{ui.esc(item.get('reason') or '已完成摘要级审查；默认无需展开全文。')}</td>"
            "</tr>"
        )
    return rows


def _metadata_only_rows(model: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in model.get("metadata_only_reviewed", []) or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td><code>{ui.esc(item.get('file_type') or '-')}</code></td>"
            f"<td><code>{ui.esc(item.get('path') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('metadata_evidence') or '-')}</td>"
            f"<td>{ui.esc(item.get('reason') or '已完成 metadata-only 审查；二进制/版图文件默认不做全文 diff。')}</td>"
            "</tr>"
        )
    return rows
```

In `render_version_update_detail_panel()`, replace the single "变化文件" section with the three tables:

```python
        + "<h3>Recommended File Diff</h3>"
        + ui.faceted_table(
            "recommended-file-diff-table",
            ["Priority", "file_type", "path", "reason", "command"],
            _recommended_file_diff_rows(model),
            "暂无 P0/P1 文件级 Diff 建议",
            "搜索 priority / file_type / path",
            [(0, "Priority"), (1, "file_type")],
        )
        + "<h3>Summary-only Reviewed</h3>"
        + "<div class='quality-note'>已完成摘要级审查；默认无需展开全文。</div>"
        + ui.faceted_table(
            "summary-only-reviewed-table",
            ["file_type", "path", "summary evidence", "reason"],
            _summary_only_rows(model),
            "暂无 summary-only reviewed 文件",
            "搜索 file_type / path",
            [(0, "file_type")],
        )
        + "<h3>Metadata-only Reviewed</h3>"
        + "<div class='quality-note'>已完成 metadata-only 审查；二进制/版图文件默认不做全文 diff。</div>"
        + ui.faceted_table(
            "metadata-only-reviewed-table",
            ["file_type", "path", "hash/size/path/count evidence", "reason"],
            _metadata_only_rows(model),
            "暂无 metadata-only reviewed 文件",
            "搜索 file_type / path",
            [(0, "file_type")],
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_summary_only_and_metadata_only_are_rendered_separately -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lib_guard/test/test_version_detail_report.py src/lib_guard/render/version_detail_report.py
git commit -m "test: cover version detail evidence grouping"
```

## Task 2: Human-Readable Headline And Primary Action

**Files:**
- Modify: `src/lib_guard/test/test_version_detail_report.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Test: `src/lib_guard/test/test_version_detail_report.py`

- [ ] **Step 1: Add failing headline test**

Add:

```python
    def test_version_detail_headline_mentions_base_and_action_counts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _diff_dir, lib, version = self._diff_fixture(root)

            from lib_guard.render.version_detail_report import build_version_update_detail_model, render_version_update_detail_panel

            model = build_version_update_detail_model(root / "html", lib, version)
            html = render_version_update_detail_panel(model)

            self.assertIn("headline", model)
            self.assertIn("confidence_note", model)
            self.assertEqual(model["primary_next_action"]["kind"], "file_diff_recommended")
            self.assertEqual(model["primary_next_action"]["command_count"], 2)
            self.assertIn("当前版本相对 current_effective", model["headline"])
            self.assertIn("2 个建议下钻", model["headline"])
            self.assertIn("5 个已按 Summary/Metadata-only 审查", model["headline"])
            self.assertIn("Base source=current_effective", model["confidence_note"])
            self.assertIn("comparison_semantics=full", model["confidence_note"])
            self.assertIn(model["headline"], html)
            self.assertIn(model["confidence_note"], html)
            self.assertIn("Run recommended File Diff", html)
```

- [ ] **Step 2: Run the failing test**

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_version_detail_headline_mentions_base_and_action_counts -q
```

Expected: FAIL because `headline`, `confidence_note`, and `primary_next_action` are missing.

- [ ] **Step 3: Implement headline helpers**

Add after `_group_update_file_changes()`:

```python
def _build_update_headline(base_ref: str, changed_files: int, file_groups: Mapping[str, list[dict[str, Any]]]) -> str:
    recommended = len(file_groups.get("recommended_file_diff", []) or [])
    reviewed = len(file_groups.get("summary_only_reviewed", []) or []) + len(file_groups.get("metadata_only_reviewed", []) or [])
    return f"当前版本相对 {base_ref} 有 {changed_files} 个变化；{recommended} 个建议下钻，{reviewed} 个已按 Summary/Metadata-only 审查。"


def _build_confidence_note(base_ref: str, comparison_semantics: str, delete_semantics: str) -> str:
    return f"Base source={base_ref}；comparison_semantics={comparison_semantics}；delete_semantics={delete_semantics}。"


def _primary_next_action(file_groups: Mapping[str, list[dict[str, Any]]], status: str) -> dict[str, Any]:
    recommended = len(file_groups.get("recommended_file_diff", []) or [])
    if status == "NEEDS_BASE_CONFIRM":
        return {"label": "Confirm base", "kind": "base_confirm_required", "command_count": 0}
    if recommended:
        return {"label": "Run recommended File Diff", "kind": "file_diff_recommended", "command_count": recommended}
    return {"label": "Review summary and metadata evidence", "kind": "review_evidence", "command_count": 0}
```

In `build_version_update_detail_model()`, after `file_groups` and `status` are available, compute:

```python
    headline = _build_update_headline(base_ref, _as_int(changed_files), file_groups)
    confidence_note = _build_confidence_note(base_ref, comparison_semantics, delete_semantics)
    primary_next_action = _primary_next_action(file_groups, status)
```

Add to returned model:

```python
        "headline": headline,
        "confidence_note": confidence_note,
        "primary_next_action": primary_next_action,
```

- [ ] **Step 4: Render headline first**

At the start of `render_version_update_detail_panel()`, before `ui.metric_grid(...)`, add:

```python
    primary = _as_mapping(model.get("primary_next_action"))
    headline_html = (
        "<div class='update-headline'>"
        f"<h3>{ui.esc(model.get('headline') or '尚未生成更新详情；请运行 lg refresh <LIB>。')}</h3>"
        f"<p>{ui.esc(model.get('confidence_note') or '-')}</p>"
        f"<div>{ui.badge(primary.get('kind') or 'review_evidence', primary.get('label') or 'Review evidence')} "
        f"<span class='muted'>commands={ui.esc(primary.get('command_count', 0))}</span></div>"
        "</div>"
    )
```

Then prepend `headline_html` to the panel body:

```python
        headline_html
        + ui.metric_grid(
```

- [ ] **Step 5: Run test to verify it passes**

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_version_detail_headline_mentions_base_and_action_counts -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lib_guard/test/test_version_detail_report.py src/lib_guard/render/version_detail_report.py
git commit -m "feat: add version detail headline and trust context"
```

## Task 3: Base Trust Prompt And Blocking Missing Base

**Files:**
- Modify: `src/lib_guard/test/test_version_detail_report.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Test: `src/lib_guard/test/test_version_detail_report.py`

- [ ] **Step 1: Add failing trust tests**

Add:

```python
    def test_adjacent_fallback_shows_warning_not_normal_update_detail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            diff_dir = root / "adjacent_diff"
            self._write_json(diff_dir / "diff_summary.json", {"status": "DIFF", "changed_files": 1})

            from lib_guard.render.version_detail_report import build_version_update_detail_model, render_version_update_detail_panel

            model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {
                    "version_id": "patch_20260630",
                    "diff": {"adjacent_old_version": "raw_previous", "adjacent_diff_dir": str(diff_dir)},
                },
            )
            html = render_version_update_detail_panel(model)

            self.assertEqual(model["base_ref"], "adjacent_fallback")
            self.assertEqual(model["base_trust_status"], "WARNING")
            self.assertIn("该结果不是标准 current-effective 更新详情，仅供手动 compare/debug；release 前请确认 base。", html)
            self.assertIn("Base source", html)
            self.assertIn("Base version", html)
            self.assertIn("Target version", html)
            self.assertIn("Comparison semantics", html)
            self.assertIn("Delete semantics", html)

    def test_needs_base_confirm_is_blocking_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            from lib_guard.render.version_detail_report import build_version_update_detail_model, render_version_update_detail_panel

            model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/ucie", "library_name": "ucie"},
                {"version_id": "orphan_20260630"},
            )
            html = render_version_update_detail_panel(model)

            self.assertEqual(model["status"], "NEEDS_BASE_CONFIRM")
            self.assertEqual(model["base_trust_status"], "BLOCKING")
            self.assertEqual(model["primary_next_action"]["kind"], "base_confirm_required")
            self.assertIn("无法确定 base；请先确认 current_effective 或 previous_effective。", html)
            self.assertIn("BLOCKING", html)
```

- [ ] **Step 2: Run failing tests**

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_adjacent_fallback_shows_warning_not_normal_update_detail src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_needs_base_confirm_is_blocking_status -q
```

Expected: FAIL because `base_trust_status` and trust copy are missing.

- [ ] **Step 3: Add trust helpers**

Add after `_primary_next_action()`:

```python
STANDARD_BASE_REFS = {"current_effective", "previous_effective", "explicit"}
FALLBACK_BASE_REFS = {"adjacent_fallback", "recorded_base", "recorded_base_fallback", "unknown"}


def _base_trust_status(base_ref: str) -> str:
    if base_ref == "NEEDS_BASE_CONFIRM":
        return "BLOCKING"
    if base_ref in STANDARD_BASE_REFS:
        return "PASS"
    if base_ref in FALLBACK_BASE_REFS:
        return "WARNING"
    return "WARNING"


def _base_trust_note(base_ref: str) -> str:
    if base_ref == "NEEDS_BASE_CONFIRM":
        return "无法确定 base；请先确认 current_effective 或 previous_effective。"
    if base_ref in STANDARD_BASE_REFS:
        return "Base 已按标准 Version Review 语义确认。"
    return "该结果不是标准 current-effective 更新详情，仅供手动 compare/debug；release 前请确认 base。"
```

In `build_version_update_detail_model()`, add:

```python
    base_trust_status = _base_trust_status(base_ref)
    base_trust_note = _base_trust_note(base_ref)
```

Add returned fields:

```python
        "base_trust_status": base_trust_status,
        "base_trust_note": base_trust_note,
```

- [ ] **Step 4: Render trust context**

In `render_version_update_detail_panel()`, replace the existing compact meta with explicit labels:

```python
    trust_note = str(model.get("base_trust_note") or "")
    trust_status = str(model.get("base_trust_status") or "WARNING")
    meta = ui.compact_meta(
        [
            ("Base source", model.get("base_ref") or "NEEDS_BASE_CONFIRM"),
            ("Base version", base_version),
            ("Target version", model.get("target_version") or model.get("version_id") or "-"),
            ("Comparison semantics", model.get("comparison_semantics") or "-"),
            ("Delete semantics", model.get("delete_semantics") or "-"),
            ("Markdown export", model.get("markdown_export_path") or "-"),
        ]
    )
    trust_html = f"<div class='quality-note'>{ui.badge(trust_status, trust_status)} {ui.esc(trust_note)}</div>"
```

Place `trust_html + meta` immediately after `headline_html`.

- [ ] **Step 5: Run tests to verify they pass**

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_adjacent_fallback_shows_warning_not_normal_update_detail src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_needs_base_confirm_is_blocking_status -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lib_guard/test/test_version_detail_report.py src/lib_guard/render/version_detail_report.py
git commit -m "feat: add base trust prompts"
```

## Task 4: Expert `fd --force-large` Opt-In

**Files:**
- Modify: `src/lib_guard/test/test_pairwise_policy.py`
- Modify: `src/lib_guard/short_cli.py`
- Modify: `docs/cli_reference.md`
- Test: `src/lib_guard/test/test_pairwise_policy.py`

- [ ] **Step 1: Add failing short CLI tests**

Append to `PairwisePolicyTest`:

```python
    def _fd_workspace(self, root: Path, file_name: str = "top.v") -> Path:
        workspace = root / "work"
        raw = root / "raw"
        base_dir = raw / "ucie" / "base"
        patch_dir = raw / "ucie" / "patch"
        base_dir.mkdir(parents=True, exist_ok=True)
        patch_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / file_name).write_text("module top; endmodule\n", encoding="utf-8")
        (patch_dir / file_name).write_text("module top; wire a; endmodule\n", encoding="utf-8")
        catalog = workspace / "catalog" / "catalog.json"
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.write_text(
            json.dumps(
                {
                    "libraries": [
                        {
                            "library_id": "ip/ucie",
                            "library_name": "ucie",
                            "versions": [
                                {"version_id": "base", "raw_path": str(base_dir)},
                                {"version_id": "patch", "raw_path": str(patch_dir), "previous_effective_version": "base"},
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        from lib_guard.short_cli import write_default_config

        write_default_config(workspace, raw_root=raw)
        return workspace

    def test_fd_summary_only_without_force_large_fails_with_clear_message(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._fd_workspace(Path(td), "top.v")
            with self.assertRaisesRegex(ValueError, "summary-only.*--force-large"):
                build_cli_commands(["fd", "ucie", "patch", "top.v", "--type", "verilog"], cwd=workspace)

    def test_fd_force_large_allows_manual_summary_only_type(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._fd_workspace(Path(td), "top.v")
            commands = build_cli_commands(["fd", "ucie", "patch", "top.v", "--type", "verilog", "--force-large"], cwd=workspace)

        self.assertEqual(commands[0][0], "file-diff")
        self.assertEqual(commands[0][1], "verilog")
        self.assertIn("--manual-large-file-opt-in", commands[0])
```

- [ ] **Step 2: Run failing tests**

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_pairwise_policy.PairwisePolicyTest.test_fd_summary_only_without_force_large_fails_with_clear_message src.lib_guard.test.test_pairwise_policy.PairwisePolicyTest.test_fd_force_large_allows_manual_summary_only_type -q
```

Expected: FAIL because parser rejects `--type verilog` and `--force-large` does not exist.

- [ ] **Step 3: Implement expert lane constants**

In `src/lib_guard/short_cli.py`, import the lane constants:

```python
from lib_guard.project_config import (
    BINARY_METADATA_ONLY_TYPES,
    CATALOG_POLICY_FILE,
    CONFIG_NAME,
    DEFAULT_LIBRARY_TYPE,
    DEFAULT_FILE_DIFF_TYPES,
    DEFAULT_PARSE_JOBS,
    DEFAULT_SCAN_MODE,
    PROJECT_CONFIG_DIR,
    SUMMARY_ONLY_TYPES,
    project_policy_path,
    workspace_defaults,
)
```

Replace:

```python
PAIRWISE_FILE_DIFF_TYPES = set(DEFAULT_FILE_DIFF_TYPES)
```

with:

```python
PAIRWISE_FILE_DIFF_TYPES = set(DEFAULT_FILE_DIFF_TYPES)
FORCE_LARGE_FILE_DIFF_TYPES = set(SUMMARY_ONLY_TYPES) | set(BINARY_METADATA_ONLY_TYPES)
MANUAL_FILE_DIFF_TYPES = PAIRWISE_FILE_DIFF_TYPES | FORCE_LARGE_FILE_DIFF_TYPES
```

Add helper after `_infer_file_type()`:

```python
def _validate_file_diff_type(file_type: str, *, force_large: bool) -> None:
    key = str(file_type or "").lower()
    if key in PAIRWISE_FILE_DIFF_TYPES:
        return
    if key in FORCE_LARGE_FILE_DIFF_TYPES:
        if force_large:
            return
        lane = "summary-only" if key in SUMMARY_ONLY_TYPES else "metadata-only"
        raise ValueError(
            f"file type {key!r} is {lane}; default Version Review records summary/metadata evidence and does not run full file diff. "
            "Pass --force-large only for expert manual review."
        )
    raise ValueError(f"file type {key!r} is not supported by pairwise file-diff")
```

Change `_infer_file_type()` to validate against `MANUAL_FILE_DIFF_TYPES`:

```python
    if file_type not in MANUAL_FILE_DIFF_TYPES:
        raise ValueError(f"file type {file_type!r} is not supported by pairwise file-diff")
```

- [ ] **Step 4: Add CLI argument and command flag**

In `_build_parser()`, change the `--type` choices:

```python
    p.add_argument("--type", choices=sorted(MANUAL_FILE_DIFF_TYPES), help="Override inferred file type")
    p.add_argument("--force-large", action="store_true", help="Expert opt-in: allow summary-only or metadata-only file types to run manual file diff")
```

In `build_cli_commands()` file-diff path, replace:

```python
        if file_type not in PAIRWISE_FILE_DIFF_TYPES:
            raise ValueError(f"file type {file_type!r} is not supported by pairwise file-diff")
```

with:

```python
        _validate_file_diff_type(file_type, force_large=bool(getattr(args, "force_large", False)))
```

Append to the returned command list before `--library-id`:

```python
                *(
                    ["--manual-large-file-opt-in"]
                    if bool(getattr(args, "force_large", False)) and file_type in FORCE_LARGE_FILE_DIFF_TYPES
                    else []
                ),
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_pairwise_policy -q
```

Expected: PASS.

- [ ] **Step 6: Document force-large**

In `docs/cli_reference.md`, add under the `fd` section:

```markdown
### Expert opt-in: `fd --force-large`

默认 `lg fd` 只允许 `DEFAULT_FILE_DIFF_TYPES`。Verilog/SystemVerilog、Liberty/Lib、SPEF 属于 `SUMMARY_ONLY_TYPES`，DB/GDS/OAS/Layout/Milkyway/NDM 属于 `BINARY_METADATA_ONLY_TYPES`，不会进入默认推荐，也不会由 pairwise 自动生成命令。

专家需要手动展开全文时必须显式 opt-in：

```csh
lg.csh fd ucie patch_20260630 rtl/top.v --type verilog --force-large
lg.csh fd ucie patch_20260630 timing/top.lib --type liberty --force-large
```

不加 `--force-large` 会报错，并提示该类型默认走 summary-only 或 metadata-only 审查。
```

- [ ] **Step 7: Commit**

```bash
git add src/lib_guard/test/test_pairwise_policy.py src/lib_guard/short_cli.py docs/cli_reference.md
git commit -m "feat: allow expert file diff opt in"
```

## Task 5: Split `catalog_render_common.py`

**Files:**
- Create: `src/lib_guard/render/catalog_render_common.py`
- Modify: `src/lib_guard/render/catalog_report.py`
- Modify: `src/lib_guard/render/catalog_workspace_report.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Modify: `src/lib_guard/test/test_repository_cleanup.py`
- Test: `src/lib_guard/test/test_repository_cleanup.py`

- [ ] **Step 1: Add failing dependency guard**

Add to `RepositoryCleanupTest`:

```python
    def test_workspace_and_version_detail_do_not_import_catalog_report_private_helpers_after_common_split(self) -> None:
        workspace_report = (ROOT / "src" / "lib_guard" / "render" / "catalog_workspace_report.py").read_text(encoding="utf-8")
        version_detail_report = (ROOT / "src" / "lib_guard" / "render" / "version_detail_report.py").read_text(encoding="utf-8")
        common_report = (ROOT / "src" / "lib_guard" / "render" / "catalog_render_common.py")

        self.assertTrue(common_report.exists())
        self.assertNotIn("from lib_guard.render import catalog_report as cr", workspace_report)
        self.assertNotIn("from lib_guard.render import catalog_report as cr", version_detail_report)
        self.assertNotIn("def _cr(", workspace_report)
        self.assertNotIn("def _cr(", version_detail_report)
        forbidden_calls = [
            "cr._safe",
            "cr._href",
            "cr._rel_href",
            "cr._write_text",
            "cr._short_path",
            "cr._status_key",
            "cr._truthy",
            "cr._version_links",
            "cr._relation_status",
            "cr._relation_label",
            "cr._file_review_status",
            "cr._file_review_text",
            "cr._package_type",
            "cr._version_diff_summary",
            "cr._version_file_diff",
            "cr._version_diff_json",
            "cr._relative_display_path",
            "cr._version_release_notes",
        ]
        hits = [token for token in forbidden_calls if token in workspace_report or token in version_detail_report]
        self.assertFalse(hits, "private catalog_report helper calls remain:\n" + "\n".join(hits))
```

- [ ] **Step 2: Run failing guard**

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_repository_cleanup.RepositoryCleanupTest.test_workspace_and_version_detail_do_not_import_catalog_report_private_helpers_after_common_split -q
```

Expected: FAIL because `catalog_render_common.py` does not exist and both renderers use `_cr()`.

- [ ] **Step 3: Create common helper module**

Create `src/lib_guard/render/catalog_render_common.py` with this content:

```python
"""Shared catalog render helpers that do not own pages."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import os
import re

from lib_guard.review.io import as_file_href, read_json


def safe(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "item")).strip("._")
    return text or "item"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def version_links(version: Mapping[str, Any]) -> Mapping[str, Any]:
    links = version.get("links") or {}
    return links if isinstance(links, Mapping) else {}


def href(path: Any) -> str:
    return as_file_href(path) if path else ""


def rel_href(base: Path, path: Any) -> str:
    if not path:
        return ""
    try:
        target = Path(str(path))
        if target.is_absolute():
            return Path(os.path.relpath(target, base)).as_posix()
    except Exception:
        pass
    return str(path).replace("\\", "/")


def status_key(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper()


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "ok"}


def short_path(path: Any, limit: int = 72) -> str:
    text = str(path or "-")
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]


def short_name(value: Any, head: int = 26, tail: int = 18) -> str:
    text = str(value or "-")
    if len(text) <= head + tail + 3:
        return text
    return f"{text[:head]}...{text[-tail:]}"


def package_type(version: Mapping[str, Any]) -> str:
    return str(version.get("package_type") or version.get("version_type") or version.get("stage") or "UNKNOWN").upper()


def base_full_version(version: Mapping[str, Any]) -> str | None:
    diff = version.get("diff") or {}
    lineage = version.get("lineage") or {}
    for key in ["base_full_version", "base_version"]:
        value = version.get(key)
        if value:
            return str(value)
    for value in [diff.get("cumulative_base_version"), diff.get("base_version"), lineage.get("base_candidate")]:
        if value:
            return str(value)
    return None


def previous_effective_version(version: Mapping[str, Any]) -> str | None:
    diff = version.get("diff") or {}
    lineage = version.get("lineage") or {}
    for key in ["previous_effective_version", "parent_version"]:
        value = version.get(key)
        if value:
            return str(value)
    for value in [diff.get("adjacent_old_version"), lineage.get("parent_candidate")]:
        if value:
            return str(value)
    return None


def is_full_baseline(version: Mapping[str, Any]) -> bool:
    pkg = package_type(version)
    return bool(truthy(version.get("standalone")) or pkg in {"FULL_PACKAGE", "FULL"})


def relation_status(version: Mapping[str, Any]) -> str:
    pkg = package_type(version)
    if is_full_baseline(version):
        return "FULL_BASELINE"
    base_full = base_full_version(version)
    prev_eff = previous_effective_version(version)
    base_required = truthy(version.get("base_required")) or pkg in {"PARTIAL_UPDATE", "HOTFIX", "DOC_UPDATE", "DOC_ONLY"}
    if base_required and not (base_full or prev_eff):
        return "NEED_BINDING"
    if base_full or prev_eff:
        return "BOUND"
    return "STANDALONE"


def relation_label(status: str) -> str:
    return {
        "FULL_BASELINE": "完整基线",
        "NEED_BINDING": "待确认 base",
        "BOUND": "已绑定",
        "STANDALONE": "独立版本",
    }.get(str(status or ""), str(status or "-"))


def file_review_status(version: Mapping[str, Any]) -> str:
    diff = version.get("diff") or {}
    if diff.get("manual_pairwise_tasks") or diff.get("pairwise_tasks"):
        return "PAIRWISE_RECOMMENDED"
    if status_key(version.get("diff_status")) in {"DIFF", "CHANGED"}:
        return "REVIEW"
    return "PAIRWISE_EMPTY"


def file_review_text(version: Mapping[str, Any]) -> str:
    status = file_review_status(version)
    return {
        "PAIRWISE_RECOMMENDED": "建议文件级 Diff",
        "REVIEW": "查看更新详情",
        "PAIRWISE_EMPTY": "无默认文件级 Diff",
    }.get(status, status)


def node_package_type(version: Mapping[str, Any]) -> str:
    pkg = package_type(version)
    if pkg in {"PARTIAL_UPDATE", "PARTIAL"}:
        return "partial"
    if pkg in {"HOTFIX"}:
        return "hotfix"
    if pkg in {"DOC_UPDATE", "DOC_ONLY"}:
        return "doc"
    if pkg in {"FULL_PACKAGE", "FULL"}:
        return "full"
    return str(version.get("node_kind") or "raw")


def version_diff_summary(diff_dir: Path | None) -> Mapping[str, Any]:
    return read_json(diff_dir / "diff_summary.json", default={}) if diff_dir else {}


def version_file_diff(diff_dir: Path | None) -> Mapping[str, Any]:
    return read_json(diff_dir / "file_diff.json", default={}) if diff_dir else {}


def version_diff_json(diff_dir: Path | None, name: str) -> Mapping[str, Any]:
    return read_json(diff_dir / name, default={}) if diff_dir else {}


def relative_display_path(path: Any, *, base: Any = None, tail_parts: int = 4) -> str:
    text = str(path or "-")
    if base:
        try:
            return Path(text).relative_to(Path(str(base))).as_posix()
        except Exception:
            pass
    parts = Path(text).parts
    if len(parts) > tail_parts:
        return "/".join(parts[-tail_parts:])
    return text.replace("\\", "/")


def version_release_notes(raw_path: Any, *, limit: int = 3) -> list[dict[str, str]]:
    if not raw_path:
        return []
    root = Path(str(raw_path))
    if not root.exists():
        return []
    names = {"release", "release_note", "release_notes", "changelog", "changes", "update_note"}
    results: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if len(results) >= limit:
            break
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        stem = path.stem.lower()
        if not any(token in stem for token in names):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        summary = " ".join(line.strip() for line in text.splitlines() if line.strip())[:240]
        results.append({"path": relative_display_path(path, base=root), "summary": summary})
    return results
```

- [ ] **Step 4: Wire catalog_report wrappers to common**

At the top of `catalog_report.py`, add:

```python
from lib_guard.render import catalog_render_common as common
```

Replace helper bodies for `_safe`, `_write_text`, `_version_links`, `_href`, `_rel_href`, `_status_key`, `_truthy`, `_short_path`, `_short_name`, `_package_type`, `_base_full_version`, `_previous_effective_version`, `_is_full_baseline`, `_relation_status`, `_relation_label`, `_file_review_status`, `_file_review_text`, `_node_package_type`, `_version_diff_summary`, `_version_file_diff`, `_version_diff_json`, `_version_release_notes`, and `_relative_display_path` with one-line wrappers:

```python
def _safe(value: Any) -> str:
    return common.safe(value)
```

Use the same wrapper pattern for each helper, preserving old private names for internal compatibility in `catalog_report.py`.

- [ ] **Step 5: Replace migrated private calls in version detail**

In `version_detail_report.py`, replace:

```python
def _cr():
    from lib_guard.render import catalog_report as cr

    return cr
```

with:

```python
from lib_guard.render import catalog_render_common as common
```

Then replace migrated calls:

```python
cr._relative_display_path -> common.relative_display_path
cr._base_full_version -> common.base_full_version
cr._package_type -> common.package_type
cr._node_package_type -> common.node_package_type
cr._safe -> common.safe
cr._version_diff_summary -> common.version_diff_summary
cr._version_file_diff -> common.version_file_diff
cr._version_diff_json -> common.version_diff_json
cr._version_release_notes -> common.version_release_notes
cr._relation_status -> common.relation_status
cr._relation_label -> common.relation_label
cr._file_review_status -> common.file_review_status
cr._file_review_text -> common.file_review_text
cr._href -> common.href
cr._write_text -> common.write_text
```

Keep non-migrated page-specific calls to `catalog_report` only if they are not in the guard list, such as scan inventory table helpers. If any guarded `cr._...` remains, this task is not complete.

- [ ] **Step 6: Replace migrated private calls in workspace report**

In `catalog_workspace_report.py`, import:

```python
from lib_guard.render import catalog_render_common as common
```

Replace migrated wrappers:

```python
def _safe(value: Any) -> str:
    return common.safe(value)


def _write_text(path: Path, text: str) -> None:
    common.write_text(path, text)


def _href(path: Any) -> str:
    return common.href(path)


def _short_path(path: Any, limit: int = 72) -> str:
    return common.short_path(path, limit)
```

Replace migrated direct calls:

```python
cr._version_links -> common.version_links
cr._rel_href -> common.rel_href
cr._short_name -> common.short_name
cr._relation_status -> common.relation_status
cr._status_key -> common.status_key
cr._truthy -> common.truthy
cr._file_review_status -> common.file_review_status
cr._file_review_text -> common.file_review_text
```

Keep catalog timeline/effective helper calls for this task if they are not part of the guard list.

- [ ] **Step 7: Run dependency guard and render tests**

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_repository_cleanup.RepositoryCleanupTest.test_workspace_and_version_detail_do_not_import_catalog_report_private_helpers_after_common_split -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_catalog_timeline -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report -q
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/lib_guard/render/catalog_render_common.py src/lib_guard/render/catalog_report.py src/lib_guard/render/catalog_workspace_report.py src/lib_guard/render/version_detail_report.py src/lib_guard/test/test_repository_cleanup.py
git commit -m "refactor: split catalog render common helpers"
```

## Task 6: View/Type/Release/Diff Issue Evidence Panels

**Files:**
- Modify: `src/lib_guard/test/test_version_detail_report.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Test: `src/lib_guard/test/test_version_detail_report.py`

- [ ] **Step 1: Add failing evidence visibility test**

Add:

```python
    def test_view_type_release_issues_are_visible_in_update_detail_panel(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _diff_dir, lib, version = self._diff_fixture(root)

            from lib_guard.render.version_detail_report import build_version_update_detail_model, render_version_update_detail_panel

            model = build_version_update_detail_model(root / "html", lib, version)
            html = render_version_update_detail_panel(model)

            self.assertIn("View Changes", html)
            self.assertIn("Type Changes", html)
            self.assertIn("Release Readiness Changes", html)
            self.assertIn("Diff Issues", html)
            self.assertIn("Timing view changed", html)
            self.assertLess(html.index("Diff Issues"), html.index("建议动作"))
            self.assertIn("required_view_status", html)
            self.assertIn("release_readiness.json", html)
```

- [ ] **Step 2: Run failing test**

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_view_type_release_issues_are_visible_in_update_detail_panel -q
```

Expected: FAIL because evidence panels are not rendered in the primary update panel.

- [ ] **Step 3: Add evidence row helpers**

In `version_detail_report.py`, add after `_metadata_only_rows()`:

```python
def _mapping_rows(value: Mapping[str, Any], *, prefix: str = "") -> list[str]:
    rows: list[str] = []
    for key, item in value.items():
        if isinstance(item, Mapping):
            rows.append(f"<tr><td><code>{ui.esc(prefix + str(key))}</code></td><td>{ui.esc(json.dumps(item, ensure_ascii=False, sort_keys=True))}</td></tr>")
        elif isinstance(item, list):
            rows.append(f"<tr><td><code>{ui.esc(prefix + str(key))}</code></td><td>{ui.esc(json.dumps(item, ensure_ascii=False))}</td></tr>")
        else:
            rows.append(f"<tr><td><code>{ui.esc(prefix + str(key))}</code></td><td>{ui.esc(item)}</td></tr>")
    return rows


def _diff_issue_rows(model: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    issues = (_as_mapping(model.get("diff_issues"))).get("issues", []) or []
    for item in issues:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td>{ui.badge(item.get('severity') or 'info', item.get('severity') or 'info')}</td>"
            f"<td><code>{ui.esc(item.get('category') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('title') or item.get('message') or '-')}</td>"
            "</tr>"
        )
    return rows
```

Add `import json` at the top of `version_detail_report.py`.

- [ ] **Step 4: Render evidence panels before recommendations**

In `render_version_update_detail_panel()`, place this block before `<h3>建议动作</h3>`:

```python
        + "<h3>View Changes</h3>"
        + cr._scroll_table(["字段", "内容"], _mapping_rows(_as_mapping(model.get("view_diff"))), "暂无 view-level changes", "metric-scroll")
        + "<h3>Type Changes</h3>"
        + cr._scroll_table(["字段", "内容"], _mapping_rows(_as_mapping(model.get("type_diff"))), "暂无 type-level changes", "metric-scroll")
        + "<h3>Release Readiness Changes</h3>"
        + cr._scroll_table(["字段", "内容"], _mapping_rows(_as_mapping(model.get("release_readiness_diff"))), "暂无 release readiness changes", "metric-scroll")
        + "<h3>Release Evidence Changes</h3>"
        + cr._scroll_table(["字段", "内容"], _mapping_rows(_as_mapping(model.get("release_evidence_diff"))), "暂无 release evidence changes", "metric-scroll")
        + "<h3>Diff Issues</h3>"
        + ui.faceted_table(
            "diff-issues-table",
            ["严重度", "类别", "说明"],
            _diff_issue_rows(model),
            "暂无 blocking/warning diff issue",
            "搜索 issue",
            [(0, "严重度"), (1, "类别")],
        )
```

If Task 5 already removed `cr._scroll_table` from `version_detail_report.py`, use the replacement wrapper chosen in Task 5, such as `scroll_table(...)`.

- [ ] **Step 5: Run test to verify it passes**

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_view_type_release_issues_are_visible_in_update_detail_panel -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lib_guard/test/test_version_detail_report.py src/lib_guard/render/version_detail_report.py
git commit -m "feat: surface view release diff evidence"
```

## Task 7: Psychological Safety Status Copy

**Files:**
- Modify: `src/lib_guard/test/test_version_detail_report.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Test: `src/lib_guard/test/test_version_detail_report.py`

- [ ] **Step 1: Add failing status copy test**

Add:

```python
    def test_update_detail_status_copy_is_actionable(self) -> None:
        from lib_guard.render.version_detail_report import render_version_update_detail_panel

        cases = {
            "DIFF_NOT_RUN": "尚未生成更新详情；请运行 lg refresh <LIB>。",
            "NEEDS_BASE_CONFIRM": "无法确定 base；请先确认 current_effective 或 previous_effective。",
            "NO_DIFF_SUMMARY": "找到 diff 输出目录，但缺少 diff_summary.json；请检查 compare artifact。",
            "CHANGED": "已完成比较，有变化。",
            "SAME": "已完成比较，无变化。",
        }
        for status, message in cases.items():
            model = {
                "status": status,
                "base_ref": "current_effective",
                "base_version": "effective_20260620",
                "target_version": "patch_20260630",
                "comparison_semantics": "full",
                "delete_semantics": "real_delete",
                "headline": message,
                "confidence_note": "Base source=current_effective；comparison_semantics=full；delete_semantics=real_delete。",
                "primary_next_action": {"label": "Review evidence", "kind": "review_evidence", "command_count": 0},
                "summary_metrics": [],
                "recommended_file_diff": [],
                "summary_only_reviewed": [],
                "metadata_only_reviewed": [],
                "release_notes": [],
                "recommended_actions": [],
                "file_diff_recommendations": [],
            }
            html = render_version_update_detail_panel(model)
            self.assertIn(message, html)
```

- [ ] **Step 2: Run failing test**

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_update_detail_status_copy_is_actionable -q
```

Expected: FAIL for at least `NO_DIFF_SUMMARY` because no status copy helper exists.

- [ ] **Step 3: Implement status copy helper**

Add:

```python
UPDATE_STATUS_COPY = {
    "DIFF_NOT_RUN": "尚未生成更新详情；请运行 lg refresh <LIB>。",
    "NEEDS_BASE_CONFIRM": "无法确定 base；请先确认 current_effective 或 previous_effective。",
    "NO_DIFF_SUMMARY": "找到 diff 输出目录，但缺少 diff_summary.json；请检查 compare artifact。",
    "CHANGED": "已完成比较，有变化。",
    "SAME": "已完成比较，无变化。",
}


def _update_status_message(status: Any) -> str:
    return UPDATE_STATUS_COPY.get(str(status or "").upper(), "更新详情状态未知；请检查 compare artifact。")
```

In `build_version_update_detail_model()`, change status selection:

```python
    if base_ref == "NEEDS_BASE_CONFIRM":
        status = "NEEDS_BASE_CONFIRM"
    elif diff_dir and not summary:
        status = "NO_DIFF_SUMMARY"
    elif not summary and not diff_dir:
        status = "DIFF_NOT_RUN"
    elif summary_status in {"DIFF", "CHANGED"} or _as_int(changed_files):
        status = "CHANGED"
    else:
        status = summary_status or "SAME"
```

Add returned field:

```python
        "status_message": _update_status_message(status),
```

In `render_version_update_detail_panel()`, add under headline:

```python
    status_message = str(model.get("status_message") or _update_status_message(model.get("status")))
    status_html = f"<div class='quality-note'>{ui.badge(status, ui.status_label(status))} {ui.esc(status_message)}</div>"
```

Place `status_html` next to `trust_html`.

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_update_detail_status_copy_is_actionable -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib_guard/test/test_version_detail_report.py src/lib_guard/render/version_detail_report.py
git commit -m "feat: clarify version detail status copy"
```

## Task 8: Markdown Export Parity And Docs

**Files:**
- Modify: `src/lib_guard/test/test_version_detail_report.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Modify: `docs/data_contract.md`
- Test: `src/lib_guard/test/test_version_detail_report.py`

- [ ] **Step 1: Add failing Markdown parity test**

Add:

```python
    def test_markdown_export_uses_same_headline_and_evidence_counts_as_model(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _diff_dir, lib, version = self._diff_fixture(root)

            from lib_guard.render.version_detail_report import build_version_update_detail_model, export_current_lib_diff_markdown

            model = build_version_update_detail_model(root / "html", lib, version)
            md_path = root / "current_lib_diff.md"
            export_current_lib_diff_markdown(model, md_path)
            text = md_path.read_text(encoding="utf-8")

            self.assertIn(model["headline"], text)
            self.assertIn(model["confidence_note"], text)
            self.assertIn(f"recommended_file_diff: {len(model['recommended_file_diff'])}", text)
            self.assertIn(f"summary_only_reviewed: {len(model['summary_only_reviewed'])}", text)
            self.assertIn(f"metadata_only_reviewed: {len(model['metadata_only_reviewed'])}", text)
            self.assertIn("## Summary-only Reviewed", text)
            self.assertIn("## Metadata-only Reviewed", text)
            self.assertIn("## Diff Issues", text)
```

- [ ] **Step 2: Run failing test**

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_markdown_export_uses_same_headline_and_evidence_counts_as_model -q
```

Expected: FAIL because Markdown does not include the new headline and group counts.

- [ ] **Step 3: Update Markdown export**

In `export_current_lib_diff_markdown()`, add to YAML header after `changed_files`:

```python
        f"recommended_file_diff: {len(model.get('recommended_file_diff', []) or [])}",
        f"summary_only_reviewed: {len(model.get('summary_only_reviewed', []) or [])}",
        f"metadata_only_reviewed: {len(model.get('metadata_only_reviewed', []) or [])}",
```

Add after `# Current Library Diff`:

```python
        "",
        str(model.get("headline") or ""),
        "",
        str(model.get("confidence_note") or ""),
```

Add sections before `## Metadata-only Changes`:

```python
    lines.extend(["", "## Summary-only Reviewed", ""])
    for item in model.get("summary_only_reviewed", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- {item.get('file_type')} {item.get('path')} :: {item.get('summary_evidence')}")
    lines.extend(["", "## Metadata-only Reviewed", ""])
    for item in model.get("metadata_only_reviewed", []) or []:
        if isinstance(item, Mapping):
            lines.append(f"- {item.get('file_type')} {item.get('path')} :: {item.get('metadata_evidence')}")
```

Keep the existing `## Metadata-only Changes` section only if tests still need it; if duplicate content is confusing, replace it with the new `## Metadata-only Reviewed` section.

- [ ] **Step 4: Update data contract docs**

In `docs/data_contract.md`, add this section:

```markdown
## Version Update Detail Reviewer Fields

`version_update_detail_model` includes reviewer-facing fields:

- `headline`: first-screen human summary.
- `confidence_note`: base source, comparison semantics, and delete semantics in one sentence.
- `primary_next_action`: `{label, kind, command_count}` for the first reviewer action.
- `recommended_file_diff`: P0/P1 rows only.
- `summary_only_reviewed`: Verilog/SystemVerilog/Liberty/Lib/SPEF rows with summary evidence.
- `metadata_only_reviewed`: DB/GDS/OAS/Layout/Milkyway/NDM rows with hash/size/path/count evidence.
- `base_trust_status`: `PASS`, `WARNING`, or `BLOCKING`.
- `base_trust_note`: user-facing trust copy.
- `status_message`: actionable copy for `DIFF_NOT_RUN`, `NEEDS_BASE_CONFIRM`, `NO_DIFF_SUMMARY`, `CHANGED`, and `SAME`.

HTML must render from this model directly. Markdown export is optional evidence generated from the same model and is never an HTML input.
```

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_repository_cleanup -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lib_guard/test/test_version_detail_report.py src/lib_guard/render/version_detail_report.py docs/data_contract.md
git commit -m "docs: document version review reliability flow"
```

## Task 9: Final Guardrails And Validation

**Files:**
- Modify: `src/lib_guard/test/test_scan_pipeline.py`
- Modify: `src/lib_guard/test/test_repository_cleanup.py`
- Test: full test suite

- [ ] **Step 1: Add help guard for force-large**

In `test_scan_pipeline.py`, extend `test_short_cli_help_shows_minimal_workflow_examples`:

```python
        help_text = _build_parser().format_help()
        self.assertIn("--force-large", help_text)
        self.assertIn("spice", help_text)
        self.assertIn("touchstone", help_text)
```

Also add a focused parser help test:

```python
    def test_short_cli_file_diff_help_documents_force_large(self) -> None:
        from lib_guard.short_cli import _build_parser

        parser = _build_parser()
        fd_parser = parser._subparsers._group_actions[0].choices["file-diff"]
        help_text = fd_parser.format_help()

        self.assertIn("--force-large", help_text)
        self.assertIn("Expert opt-in", help_text)
```

- [ ] **Step 2: Add repository guard for no private common imports**

In `test_repository_cleanup.py`, add:

```python
    def test_common_render_helpers_are_not_reimported_from_catalog_report(self) -> None:
        common = (ROOT / "src" / "lib_guard" / "render" / "catalog_render_common.py").read_text(encoding="utf-8")
        self.assertIn("def safe", common)
        self.assertIn("def version_diff_summary", common)
        for rel in [
            "src/lib_guard/render/catalog_workspace_report.py",
            "src/lib_guard/render/version_detail_report.py",
        ]:
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("catalog_report as cr", text)
```

- [ ] **Step 3: Run final validation**

```bash
cd /home/polaris/proj/mx/ai_lib/repo
PYTHONPATH=src python3 -m compileall -q src
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_pairwise_policy -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_repository_cleanup -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline -q
PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p "test*.py" -q
PYTHONPATH=src python3 -m lib_guard.short_cli --help
git diff --check origin/codex/p0-flow-logic-fixes..HEAD
```

Expected:

- `compileall` exits 0.
- Targeted tests exit 0.
- Full discovery exits 0.
- `short_cli --help` shows `--force-large` and does not present summary-only or metadata-only types as default recommendations.
- `git diff --check` exits 0.

- [ ] **Step 4: Optional fixture smoke test**

If `/home/polaris/proj/mx/ai_lib/repo/lib_guard.yml` exists, run:

```bash
cd /home/polaris/proj/mx/ai_lib/repo
PYTHONPATH=src python3 -m lib_guard.short_cli --dry-run refresh vendor_A.openroad_platform.openroad_asap7
```

Expected: prints one or more generated `compare` commands and does not execute them. If `lib_guard.yml` is absent, skip this smoke test and record `config absent` in the PR notes.

- [ ] **Step 5: Commit final guardrails**

```bash
git add src/lib_guard/test/test_scan_pipeline.py src/lib_guard/test/test_repository_cleanup.py
git commit -m "test: add final reliability guardrails"
```

- [ ] **Step 6: Push and update PR**

```bash
git push
gh api -X PATCH repos/Godshaohao/ai_lib/issues/2 -f body=$'## Summary\n- Added first-screen Version Detail headline, confidence note, base trust status, and primary next action.\n- Split update evidence into Recommended File Diff, Summary-only Reviewed, and Metadata-only Reviewed sections.\n- Added visible View/Type/Release/Diff Issue evidence blocks before recommended actions.\n- Added expert `lg fd --force-large` opt-in while preserving safe default pairwise lanes.\n- Moved common render helpers into `catalog_render_common.py` so Version Detail and Library Workspace no longer depend on catalog_report private helpers.\n\n## Validation\n- PYTHONPATH=src python3 -m compileall -q src\n- PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p \"test*.py\" -q\n- PYTHONPATH=src python3 -m lib_guard.short_cli --help\n- git diff --check origin/codex/p0-flow-logic-fixes..HEAD\n\n## Notes\n- Main flow remains Catalog -> Version Review -> Release.\n- Pairwise default generation still excludes summary-only and metadata-only file types.\n- Generated work HTML and large raw fixtures were not pushed.'
```

Expected: branch pushes and PR #2 body updates.

## Self-Review

**Spec coverage:**

- Task 1 covers explicit UI separation for Recommended File Diff, Summary-only Reviewed, and Metadata-only Reviewed.
- Task 2 covers `headline`, `confidence_note`, and `primary_next_action`.
- Task 3 covers base source trust, warning fallback copy, and blocking `NEEDS_BASE_CONFIRM`.
- Task 4 covers expert `--force-large` opt-in without changing pairwise defaults or Version Detail recommendations.
- Task 5 covers `catalog_render_common.py` and prevents long-term private helper dependency.
- Task 6 covers View Changes, Type Changes, Release Readiness Changes, Release Evidence Changes, and Diff Issues in the main panel.
- Task 7 covers psychological safety status copy.
- Task 8 covers Markdown parity and data contract docs.
- Task 9 covers final validation and PR update.

**Placeholder scan:**

The plan contains concrete tests, implementation snippets, commands, expected outcomes, and commit steps for every task.

**Type consistency:**

The plan consistently uses `recommended_file_diff`, `summary_only_reviewed`, `metadata_only_reviewed`, `headline`, `confidence_note`, `primary_next_action`, `base_trust_status`, `base_trust_note`, `status_message`, `FORCE_LARGE_FILE_DIFF_TYPES`, and `MANUAL_FILE_DIFF_TYPES`.
