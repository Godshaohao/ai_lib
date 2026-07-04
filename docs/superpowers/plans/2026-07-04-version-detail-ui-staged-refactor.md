# Version Detail UI Staged Refactor Implementation Plan

Status: current

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the Version Detail page in stages so an IP user can decide whether a version is usable, what changed, and what evidence must be checked without being dragged through management audit noise.

**Architecture:** Keep generated HTML as output only. Make changes in the Version Detail view-model and renderer: `build_version_update_detail_model()` prepares facts, `render_version_detail_page()` and its helper panels decide what appears on the page. Do not add services, frontend frameworks, databases, or new workflows.

**Tech Stack:** Python 3.11, static HTML rendered by `lib_guard.render.version_detail_report`, existing `unittest` tests under `src/lib_guard/test`, existing `scripts/lg.csh` / `lib_guard.short_cli` render path.

---

## Scope And Guardrails

Target user: IP user reviewing one library version before use or intake.

Main judgement: Can I use this version now, and which evidence must I confirm first?

Allowed input:
- Existing catalog JSON.
- Existing scan output: `file_inventory.json`, `parser_manifest.json`, `parser_results.json`, `release_readiness.json`.
- Existing diff output: `diff_summary.json`, `file_diff.json`, `view_diff.json`, `type_diff.json`, `diff_issues.json`.

Allowed output:
- Updated renderer/view-model code.
- Updated tests.
- Re-rendered local generated HTML for manual inspection.

Forbidden expansions:
- No new frontend framework.
- No service, daemon, database, or scheduler.
- No generated HTML hand edits.
- No automatic semantic equivalence claims beyond deterministic file evidence.
- No broad scan/diff architecture rewrite.

## File Structure

- Modify `src/lib_guard/render/version_detail_report.py`
  - Owns Version Detail view-model, top facts, usage decision, focus table, and panel ordering.
  - Add small deterministic helpers for path move evidence and user-facing status vocabulary.
- Modify `src/lib_guard/test/test_version_detail_report.py`
  - Unit tests for model fields and focused render snippets.
- Modify `src/lib_guard/test/test_catalog_timeline.py`
  - Integration-style tests for the full generated Version Detail page.
- Optionally modify `src/lib_guard/render/html_report.py`
  - Only if Selected Diff page still leaks old “两两对比 / File Diff command” language after the Version Detail changes.
- Do not modify generated HTML directly under `work/`.
- Do not modify scanner/parser implementations for this UI refactor.

## Phase Strategy

1. Stage A: unify top-page vocabulary and status semantics.
2. Stage B: turn directory migration from a warning sentence into file-level evidence.
3. Stage C: reduce main-screen density and demote audit evidence.
4. Stage D: regenerate representative HTML and run product-level regression checks.

---

### Task 1: Top Status And Vocabulary Contract

**Files:**
- Modify: `src/lib_guard/test/test_version_detail_report.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Test: `src/lib_guard/test/test_version_detail_report.py`

- [ ] **Step 1: Write the failing test**

Append this test method inside `VersionDetailReportTest` in `src/lib_guard/test/test_version_detail_report.py`:

```python
    def test_version_detail_top_copy_uses_ip_user_status_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)
            version["review_gate"] = {
                "status": "REVIEW_REQUIRED",
                "blocking_items": [{"id": "gate.release_note", "title": "Release note missing"}],
                "attention_items": [],
            }

            from lib_guard.render.version_detail_report import render_version_detail_page

            page = Path(render_version_detail_page(root / "html", lib, version))
            html = page.read_text(encoding="utf-8")

            self.assertIn("必需 View 覆盖", html)
            self.assertNotIn("View 完整性", html)
            self.assertIn("Release note", html)
            self.assertIn("缺失", html)
            self.assertIn("管理门禁", html)
            self.assertIn("影响使用", html)
            self.assertNotIn("门禁状态</div><div class='metric-value'>需审阅", html)
            self.assertNotIn("阻塞项</div><div class='metric-value'>1", html)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_version_detail_top_copy_uses_ip_user_status_contract -q
```

Expected: FAIL because the current page still contains `View 完整性` and the management panel still uses the older `门禁状态 / 阻塞项` wording.

- [ ] **Step 3: Implement minimal vocabulary helpers**

In `src/lib_guard/render/version_detail_report.py`, add this helper after `_usage_decision()`:

```python
def _management_gate_user_impact(version: Mapping[str, Any]) -> tuple[str, str, str]:
    gate = version.get("review_gate") if isinstance(version.get("review_gate"), Mapping) else {}
    status = str((gate or {}).get("status") or "NOT_BUILT").upper()
    blocking = len((gate or {}).get("blocking_items", []) or [])
    attention = len((gate or {}).get("attention_items", []) or [])
    if blocking:
        return "影响使用", f"{blocking} 个管理阻塞项", "BLOCKED"
    if status in {"REVIEW_REQUIRED", "NEEDS_REVIEW", "ATTENTION"} or attention:
        return "需管理确认", f"{attention} 个关注项", "WARNING"
    if status in {"READY", "PASS", "OK"}:
        return "不影响使用", "管理门禁已关闭", "PASS"
    return "未建立", "无管理门禁证据", "INFO"
```

- [ ] **Step 4: Update top judgment labels**

In `_version_overview_panel()`, replace this tuple:

```python
("View 完整性", ui.status_label(delivery_status), "必需 view 覆盖；不等于全文 Parser", delivery_status),
```

with:

```python
("必需 View 覆盖", ui.status_label(delivery_status), "覆盖满足不等于全文 Parser 通过", delivery_status),
```

In `render_version_detail_page()`, replace this rail tuple:

```python
("Required View", required_view_status or "UNKNOWN", "必需 view 覆盖"),
```

with:

```python
("必需 View", required_view_status or "UNKNOWN", "覆盖满足不等于全文 Parser"),
```

Also replace the shell subtitle:

```python
"面向 IP 使用者展示可用性、Base 关系、使用影响、View 完整性和证据入口。"
```

with:

```python
"面向 IP 使用者展示可用性、Base 关系、使用影响、必需 View 覆盖和证据入口。"
```

- [ ] **Step 5: Replace management audit panel wording**

Replace the body of `_review_gate_summary_panel()` in `src/lib_guard/render/version_detail_report.py` with:

```python
def _review_gate_summary_panel(version: Mapping[str, Any]) -> str:
    gate = version.get("review_gate") if isinstance(version.get("review_gate"), Mapping) else {}
    impact, detail, status = _management_gate_user_impact(version)
    blocking = len((gate or {}).get("blocking_items", []) or [])
    attention = len((gate or {}).get("attention_items", []) or [])
    return ui.panel(
        "管理门禁",
        "面向 release owner 的 gate 状态；这里明确它是否影响当前版本使用判断。",
        ui.metric_grid(
            [
                ("使用影响", impact, detail, status),
                ("管理阻塞", blocking, "需要 release owner 关闭 / 接受 / 豁免", "BLOCKED" if blocking else "PASS"),
                ("管理关注", attention, "建议补充证据", "WARNING" if attention else "PASS"),
            ]
        ),
    )
```

- [ ] **Step 6: Run the targeted test**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_version_detail_top_copy_uses_ip_user_status_contract -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/lib_guard/render/version_detail_report.py src/lib_guard/test/test_version_detail_report.py
git commit -m "fix: clarify version detail usage and gate status"
```

---

### Task 2: File-Level Directory Migration Evidence

**Files:**
- Modify: `src/lib_guard/test/test_version_detail_report.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Test: `src/lib_guard/test/test_version_detail_report.py`

- [ ] **Step 1: Write the failing model test**

Append this test method inside `VersionDetailReportTest`:

```python
    def test_path_migration_evidence_is_attached_to_focus_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            diff_dir = root / "diff"
            diff_dir.mkdir()
            (diff_dir / "diff_summary.json").write_text(
                json.dumps(
                    {
                        "status": "DIFF",
                        "added_files": 1,
                        "removed_files": 1,
                        "changed_files": 0,
                        "renamed_or_moved": 1,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diff_dir / "file_diff.json").write_text(
                json.dumps(
                    {
                        "added": [{"path": "upstream_ae9a8ed9/lef/top.lef", "file_type": "lef"}],
                        "removed": [{"path": "asap7_source_package/lef/top.lef", "file_type": "lef"}],
                        "changed": [],
                        "renamed_or_moved": [
                            {
                                "old": "asap7_source_package/lef/top.lef",
                                "new": "upstream_ae9a8ed9/lef/top.lef",
                                "reason": "same basename and content signature",
                            }
                        ],
                        "counts": {"added": 1, "removed": 1, "changed": 0, "renamed_or_moved": 1},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            from lib_guard.render.version_detail_report import (
                build_version_update_detail_model,
                render_version_update_detail_panel,
            )

            model = build_version_update_detail_model(
                root / "html",
                {"library_id": "ip/asap7", "library_name": "asap7"},
                {
                    "version_id": "20260627_asap7",
                    "current_effective_ref": "20260624_asap7",
                    "diff": {"current_effective_diff_dir": str(diff_dir)},
                },
            )
            html = render_version_update_detail_panel(model)
            rows = {item["path"]: item for item in model["file_changes"]}

            self.assertEqual(rows["upstream_ae9a8ed9/lef/top.lef"]["match_status"], "MOVED_MATCH")
            self.assertEqual(rows["upstream_ae9a8ed9/lef/top.lef"]["base_candidate"], "asap7_source_package/lef/top.lef")
            self.assertEqual(rows["asap7_source_package/lef/top.lef"]["match_status"], "MOVED_MATCH")
            self.assertEqual(rows["asap7_source_package/lef/top.lef"]["target_candidate"], "upstream_ae9a8ed9/lef/top.lef")
            self.assertIn("匹配状态", html)
            self.assertIn("Base 候选", html)
            self.assertIn("Target 文件", html)
            self.assertIn("MOVED_MATCH", html)
            self.assertIn("asap7_source_package/lef/top.lef", html)
            self.assertIn("upstream_ae9a8ed9/lef/top.lef", html)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_path_migration_evidence_is_attached_to_focus_rows -q
```

Expected: FAIL because `match_status`, `base_candidate`, `target_candidate`, and the new table columns do not exist.

- [ ] **Step 3: Add deterministic path match helpers**

In `src/lib_guard/render/version_detail_report.py`, add these helpers after `_path_restructure_summary()`:

```python
def _path_match_evidence(file_diff: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    evidence: dict[str, dict[str, str]] = {}
    for item in file_diff.get("renamed_or_moved", []) or []:
        if not isinstance(item, Mapping):
            continue
        old_path = common.relative_display_path(item.get("old") or "-")
        new_path = common.relative_display_path(item.get("new") or "-")
        reason = str(item.get("reason") or item.get("match_reason") or "renamed_or_moved")
        if old_path and old_path != "-":
            evidence[old_path] = {
                "match_status": "MOVED_MATCH",
                "base_candidate": old_path,
                "target_candidate": new_path,
                "match_reason": reason,
            }
        if new_path and new_path != "-":
            evidence[new_path] = {
                "match_status": "MOVED_MATCH",
                "base_candidate": old_path,
                "target_candidate": new_path,
                "match_reason": reason,
            }
    return evidence


def _default_match_evidence(change: str, path: str) -> dict[str, str]:
    if change == "added":
        return {
            "match_status": "UNMATCHED_ADDED",
            "base_candidate": "-",
            "target_candidate": path,
            "match_reason": "no moved/renamed evidence",
        }
    if change == "removed":
        return {
            "match_status": "UNMATCHED_REMOVED",
            "base_candidate": path,
            "target_candidate": "-",
            "match_reason": "no moved/renamed evidence",
        }
    return {
        "match_status": "SAME_PATH_CHANGED",
        "base_candidate": path,
        "target_candidate": path,
        "match_reason": "same relative path changed",
    }
```

- [ ] **Step 4: Attach match evidence to file changes**

In `build_version_update_detail_model()`, after reading `file_diff`, add:

```python
    path_match_evidence = _path_match_evidence(file_diff)
```

Change the `file_changes` assignment from:

```python
    file_changes = _iter_file_changes(file_diff, raw_path=version.get("raw_path"))
```

to:

```python
    file_changes = _iter_file_changes(file_diff, raw_path=version.get("raw_path"))
    for item in file_changes:
        path = str(item.get("path") or "")
        change = str(item.get("change") or "")
        item.update(path_match_evidence.get(path) or _default_match_evidence(change, path))
```

Also add this field to the `model` dictionary:

```python
        "path_match_evidence": path_match_evidence,
```

- [ ] **Step 5: Add columns to focused and full change tables**

Replace `_file_change_rows_for()` with:

```python
def _file_change_rows_for(items: Any) -> list[str]:
    rows: list[str] = []
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td>{ui.badge(str(item.get('change') or '').upper(), _cn_change_kind(item.get('change')))}</td>"
            f"<td><code>{ui.esc(item.get('file_type') or '-')}</code></td>"
            f"<td><code>{ui.esc(item.get('path') or '-')}</code></td>"
            f"<td>{ui.badge(item.get('review_lane') or 'Review', item.get('review_lane') or 'Review')}</td>"
            f"<td><code>{ui.esc(item.get('match_status') or '-')}</code></td>"
            f"<td><code>{ui.esc(item.get('base_candidate') or '-')}</code></td>"
            f"<td><code>{ui.esc(item.get('target_candidate') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('hint') or '-')}</td>"
            "</tr>"
        )
    return rows
```

In `render_version_update_detail_panel()`, replace both table header lists:

```python
["变化", "类型", "路径", "审查级别", "建议"]
```

with:

```python
["变化", "类型", "路径", "审查级别", "匹配状态", "Base 候选", "Target 文件", "建议"]
```

- [ ] **Step 6: Update filter columns for the wider table**

In `_version_detail_styles()`, keep the existing width rules and add this CSS rule near the `.focus-change-scroll` styles:

```python
".version-scroll-table.change-scroll table,.version-scroll-table.focus-change-scroll table{min-width:1780px}"
```

If an older rule sets the same selector to `min-width:1380px`, replace that value with `1780px` instead of adding a duplicate.

- [ ] **Step 7: Run the targeted test**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_path_migration_evidence_is_attached_to_focus_rows -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/lib_guard/render/version_detail_report.py src/lib_guard/test/test_version_detail_report.py
git commit -m "feat: show path migration evidence in version detail"
```

---

### Task 3: Main Screen Density Reduction

**Files:**
- Modify: `src/lib_guard/test/test_catalog_timeline.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Test: `src/lib_guard/test/test_catalog_timeline.py`

- [ ] **Step 1: Write the failing integration test**

In `src/lib_guard/test/test_catalog_timeline.py`, find the test that checks `version_html` around the existing assertions for `"IP 版本使用事实"` and append these assertions in that same test:

```python
            main_before_raw = version_html.split("<h2>原始证据", 1)[0]
            self.assertIn("使用影响", main_before_raw)
            self.assertIn("重点变化文件", main_before_raw)
            self.assertLess(main_before_raw.count("<details"), 6)
            self.assertNotIn("完整 Diff 指标</summary>", main_before_raw)
            self.assertIn("审计证据", version_html)
            self.assertIn("完整 Diff 指标</summary>", version_html)
            self.assertIn("Parser 证据", version_html)
```

- [ ] **Step 2: Run the integration test to verify it fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_catalog_timeline.CatalogTimelineTest.test_catalog_html_uses_product_version_detail_layout -q
```

Expected: FAIL if the exact test name differs, run this fallback command and confirm a failure in the catalog timeline test file:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_catalog_timeline -q
```

- [ ] **Step 3: Extract audit evidence into one collapsed panel**

In `src/lib_guard/render/version_detail_report.py`, add this function before `render_version_update_detail_panel()`:

```python
def _audit_evidence_panel(model: Mapping[str, Any]) -> str:
    return ui.collapsible_panel(
        "审计证据",
        "完整 Diff 指标、全量变化文件、summary-only、metadata-only、release evidence 和 diff issues 默认折叠；这些是追溯证据，不是主屏结论。",
        "<div class='evidence-detail-stack'>"
        "<details><summary>完整 Diff 指标</summary>"
        + catalog._scroll_table(["指标", "数值"], _metric_rows(model), "暂无自动 Diff 结果。", "metric-scroll")
        + "</details>"
        "<details><summary>完整变化文件</summary>"
        + catalog._scroll_table(
            ["变化", "类型", "路径", "审查级别", "匹配状态", "Base 候选", "Target 文件", "建议"],
            _file_change_rows(model),
            "暂无文件变化明细。",
            "change-scroll",
        )
        + "</details>"
        "<details><summary>Summary-only / Metadata-only 明细</summary>"
        + "<h3>Summary-only Reviewed</h3>"
        + catalog._scroll_table(["file_type", "path", "summary evidence", "reason"], _summary_only_rows(model), "暂无 summary-only 审查项。", "summary-only-scroll")
        + "<h3>Metadata-only Reviewed</h3>"
        + catalog._scroll_table(["file_type", "path", "metadata evidence", "reason"], _metadata_only_rows(model), "暂无 metadata-only 审查项。", "metadata-only-scroll")
        + "</details>"
        "<details><summary>Release note 与结构变化证据</summary>"
        + "<h3>Release note</h3>"
        + ui.faceted_table("release-note-table", ["Release note", "摘要"], _release_note_rows(model), "暂无 release_note / changelog 摘要", "搜索 release note / changelog", [(0, "文件")])
        + "<h3>View Changes</h3>"
        + catalog._scroll_table(["字段", "值"], _mapping_rows(_as_mapping(model.get("view_diff"))), "暂无 view_diff.json 变化证据。", "view-change-scroll")
        + "<h3>Type Changes</h3>"
        + catalog._scroll_table(["字段", "值"], _mapping_rows(_as_mapping(model.get("type_diff"))), "暂无 type_diff.json 变化证据。", "type-change-scroll")
        + "<h3>Release Readiness Changes</h3>"
        + catalog._scroll_table(["字段", "值"], _mapping_rows(_as_mapping(model.get("release_readiness_diff"))), "暂无 release_readiness_diff.json 变化证据。", "release-readiness-change-scroll")
        + "<h3>Release Evidence Changes</h3>"
        + catalog._scroll_table(["字段", "值"], _mapping_rows(_as_mapping(model.get("release_evidence_diff"))), "暂无 release_evidence_diff.json 变化证据。", "release-evidence-change-scroll")
        + "</details>"
        "<details><summary>Diff Issues / 建议动作</summary>"
        + "<h3>Diff Issues</h3>"
        + ui.faceted_table("diff-issue-table", ["Severity", "Category", "Issue"], _diff_issue_rows(model), "暂无 diff_issues.json 问题。", "搜索 issue / category / severity", [(0, "Severity"), (1, "Category")])
        + "<h3>建议动作</h3>"
        + ui.faceted_table("recommended-action-table", ["建议动作"], _recommended_action_rows(model), "暂无建议动作", "搜索建议动作")
        + "</details>"
        "</div>",
        open=False,
    )
```

- [ ] **Step 4: Remove audit details from the main usage panel**

In `render_version_update_detail_panel()`, delete the local `detail_evidence = (...)` block. Then remove `+ detail_evidence` from the returned panel body.

The panel body should end after the focused change table:

```python
        + catalog._scroll_table(
            ["变化", "类型", "路径", "审查级别", "匹配状态", "Base 候选", "Target 文件", "建议"],
            _focus_file_change_rows(model),
            "暂无重点变化文件；可展开完整变化文件查看。",
            "focus-change-scroll",
        )
```

- [ ] **Step 5: Place audit evidence after parser/corner sections**

In `render_version_detail_page()`, after:

```python
        + _parser_panel(parser_manifest, parser_results)
```

add:

```python
        + _audit_evidence_panel(model)
```

This keeps the main `使用影响` panel focused and puts raw audit details lower in the page.

- [ ] **Step 6: Run the integration test**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_catalog_timeline -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/lib_guard/render/version_detail_report.py src/lib_guard/test/test_catalog_timeline.py
git commit -m "refactor: move audit evidence out of version detail main panel"
```

---

### Task 4: Product Copy And Release Note Prominence

**Files:**
- Modify: `src/lib_guard/test/test_version_detail_report.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Test: `src/lib_guard/test/test_version_detail_report.py`

- [ ] **Step 1: Write the failing release-note prominence test**

Append this test method inside `VersionDetailReportTest`:

```python
    def test_release_note_status_is_visible_in_top_overview(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)

            from lib_guard.render.version_detail_report import render_version_detail_page

            page = Path(render_version_detail_page(root / "html", lib, version))
            html = page.read_text(encoding="utf-8")
            overview = html.split("<h2>使用影响", 1)[0]

            self.assertIn("Release note", overview)
            self.assertIn("缺失", overview)
            self.assertIn("必需 View 覆盖", overview)
            self.assertNotIn("Unknown / RN", overview)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_release_note_status_is_visible_in_top_overview -q
```

Expected: FAIL because `Release note` is currently mostly visible in the rail/evidence side panel, not as a first-class item in the overview judgment strip.

- [ ] **Step 3: Add Release note to overview judgment**

In `_version_overview_panel()`, before building `judgment = _judgment_strip(...)`, add:

```python
    release_note_count = len(model.get("release_notes", []) or [])
    release_note_label = "已发现" if release_note_count else "缺失"
    release_note_detail = f"{release_note_count} 个 release note / changelog"
```

Replace the final judgment tuple:

```python
("待确认", str(unknown_count), "unknown / 分类待确认" if unknown_count else "无 unknown", "WARNING" if unknown_count else "PASS"),
```

with these two tuples:

```python
("Release note", release_note_label, release_note_detail, "PASS" if release_note_count else "WARNING"),
("Unknown", str(unknown_count), "分类待确认" if unknown_count else "无 unknown", "WARNING" if unknown_count else "PASS"),
```

- [ ] **Step 4: Rename task card label**

In `_review_task_summary_html()`, replace:

```python
("Unknown / RN", f"{unknown} / {release_note_status}", "分类和 release note 证据", "WARNING" if unknown or not model.get("release_notes") else "PASS"),
```

with:

```python
("Release note", release_note_status, "版本说明 / changelog 证据", "WARNING" if not model.get("release_notes") else "PASS"),
```

Then add this separate task after it:

```python
("Unknown 文件", unknown, "补分类或确认可忽略", "WARNING" if unknown else "PASS"),
```

- [ ] **Step 5: Run the targeted test**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_release_note_status_is_visible_in_top_overview -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lib_guard/render/version_detail_report.py src/lib_guard/test/test_version_detail_report.py
git commit -m "fix: surface release note status in version overview"
```

---

### Task 5: Generated HTML Regression And Product Grill

**Files:**
- Modify: no source files unless a regression is found.
- Generated output: `work/openroad_manual_review/catalog/html/...`
- Test: generated HTML grep checks and unit tests.

- [ ] **Step 1: Run focused unit tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report src.lib_guard.test.test_catalog_timeline -q
```

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p "test*.py" -q
```

Expected: `Ran ... tests` and `OK`. The expected `--mode candidate` argparse text may appear because tests intentionally verify old scan modes are rejected.

- [ ] **Step 3: Re-render representative pages**

Run:

```bash
PYTHONPATH=src python3 -m lib_guard.short_cli --config work/openroad_manual_review/lib_guard.yml cat vendor_A.openroad_platform.openroad_asap7 20260627_asap7
PYTHONPATH=src python3 -m lib_guard.short_cli --config work/openroad_manual_review/lib_guard.yml cat vendor_C.openroad_platform.openroad_sky130ram 20260626_sky130ram_update
```

Expected: each command prints JSON with `"status": "PASS"` and `"rendered_versions": 1`.

- [ ] **Step 4: Run generated HTML negative checks**

Run:

```bash
rg -l "手动两两|两两对比|文件级 Diff 命令|审查含义|<th>Detail</th>|View 完整性|Unknown / RN" \
  work/openroad_manual_review/catalog/html/libraries/ip_vendor_A.openroad_platform.openroad_asap7/versions/20260627_asap7/index.html \
  work/openroad_manual_review/catalog/html/libraries/ip_vendor_C.openroad_platform.openroad_sky130ram/versions/20260626_sky130ram_update/index.html -S
```

Expected: no output and exit code `1`.

- [ ] **Step 5: Run generated HTML positive checks**

Run:

```bash
rg -o "必需 View 覆盖|Release note|管理门禁|匹配状态|Base 候选|Target 文件|审计证据|疑似重打包 / 目录迁移" \
  work/openroad_manual_review/catalog/html/libraries/ip_vendor_A.openroad_platform.openroad_asap7/versions/20260627_asap7/index.html \
  work/openroad_manual_review/catalog/html/libraries/ip_vendor_C.openroad_platform.openroad_sky130ram/versions/20260626_sky130ram_update/index.html -S
```

Expected: output includes `必需 View 覆盖`, `Release note`, `管理门禁`, `匹配状态`, `Base 候选`, and `Target 文件`. The `疑似重打包 / 目录迁移` string is required for the asap7 page and may be absent for sky130ram if that fixture does not trigger path restructure detection.

- [ ] **Step 6: Product grill checklist**

Open the asap7 generated page manually:

```text
/home/polaris/proj/mx/ai_lib/repo/work/openroad_manual_review/catalog/html/libraries/ip_vendor_A.openroad_platform.openroad_asap7/versions/20260627_asap7/index.html
```

Check these facts:

```text
1. Top status has one user-facing usage decision.
2. Management gate says whether it affects use.
3. Required View wording does not imply all parser/content checks passed.
4. Release note missing is visible before the main change table.
5. Path migration evidence is visible as row-level match status.
6. Main panel does not contain the full audit dump by default.
7. Parser evidence remains folded and does not show "审查含义" or "Detail".
```

- [ ] **Step 7: Commit generated-independent source changes**

Do not commit generated `work/` HTML unless the team explicitly wants local preview output tracked.

```bash
git add src/lib_guard/render/version_detail_report.py src/lib_guard/test/test_version_detail_report.py src/lib_guard/test/test_catalog_timeline.py
git commit -m "test: lock version detail product UI contract"
```

---

## Self-Review

Spec coverage:
- 分阶段大改 UI: covered by Tasks 1 through 5.
- 分步骤拷打: each task starts with a failing test and ends with explicit product or generated HTML checks.
- 信息披露正确: Task 1 and Task 4 fix status, View, gate, and Release note wording.
- 算法机制合理: Task 2 makes directory migration deterministic and inspectable without inventing semantic equivalence.
- 产品 UI 合理: Task 3 reduces main-screen density and moves audit evidence out of the primary usage panel.

Placeholder scan:
- No task uses unspecified file paths.
- No task asks for generic tests without code.
- No task requires new frameworks, services, databases, or manual edits to generated HTML.

Type consistency:
- New fields are consistently named `match_status`, `base_candidate`, `target_candidate`, `match_reason`.
- Existing model fields `file_changes`, `release_notes`, `review_gate`, `lane_counts`, and `path_restructure` remain unchanged.
- Existing tests continue to use `unittest`, `tempfile`, `Path`, and JSON fixtures.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-04-version-detail-ui-staged-refactor.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.

2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
