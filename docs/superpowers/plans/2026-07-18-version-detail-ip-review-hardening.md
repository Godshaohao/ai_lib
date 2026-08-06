Status: current

# Version Detail IP Review Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正增量包变化语义，并把 Version Detail 收敛为面向 IP 使用者的单一事实审查投影，让用户在首屏直接看到可信基准、真实 View 变化、证据范围和待确认事实。

**Architecture:** 保留 `catalog`、`scan`、`diff`、`effective/window` 作为事实输入，不修改原始 diff artifact；在 `version_review_model.py` 中增加确定性的 IP 审查投影，把原始变化转换为用户可见变化。`version_review_render.py` 只渲染投影，`version_detail_report.py` 只负责组装页面和证据入口，事实源说明与管理审计下沉并默认折叠。

**Tech Stack:** Python 3.11、标准库 `unittest`/`html.parser`、静态 HTML/CSS/JavaScript、现有 `lib_guard` scan/diff/effective artifact。

## Execution Result

完成日期：2026-07-18

- 增量包使用 `out_of_scope_missing` 语义：本包未携带不再伪装为真实删除；FULL 包继续使用 `real_delete`。
- Version Detail 首屏固定为：版本使用结论、视图变化/覆盖矩阵、关联使用场景、待确认事实；正式放行和审计证据默认折叠。
- 本包 inventory 与候选有效版 inventory 分栏建模；候选未生成时不在每一行重复提示。
- 文件样例每组最多 8 条，重点变化最多 120 行，并保留完整 evidence 链接。
- 目标详情页测试 56 项通过；最终全量回归 428 项通过；`compileall` 通过。
- 真实样例单版本 render 耗时 0.56 秒，HTML 约 70 KB。
- Chromium 桌面检查：1600 x 1100，无横向溢出，11 个详情折叠项默认关闭，页面总高度 2103 px。
- 最终样例：`work/version_detail_loop_20260718/catalog/html/libraries/ip_vendor_A.openroad_platform.openroad_asap7/versions/20260627_asap7/index.html`。
- 最终截图：`work/version_detail_loop_20260718/version_detail_desktop_final.png`。

## Global Constraints

- Target user: 使用和集成 IP 的工程师；发布负责人只使用折叠审计区。
- Main judgement: 当前版本相对可信基准有哪些真实变化，这些变化关联哪些使用场景，现有证据是否足够审查。
- Allowed input: 现有 catalog version row、scan evidence、diff evidence、effective/window context 和 review gate。
- Allowed output: 一个 Version Detail HTML 主审查投影，以及指向现有 scan/diff/effective artifact 的证据链接。
- Forbidden expansions: 不新增主审查页面、不新增 CLI、不新增数据库/服务/状态机、不修改 discover/parser/release 主流程、不增加 AI 推断或风险评分。
- 原始 `file_diff.json` 和 `diff_summary.json` 保持不可变；审查投影不得回写事实源。
- `Summary-only`、`Metadata-only` 只表示证据深度，不单独触发阻塞或“需审查后使用”。
- `usage_area_for_view()` 只表示 View 与使用场景的确定性关联，UI 不得称为已证明的“影响”。
- 增量包的 `out_of_scope_missing` 不得展示为真实删除；FULL 包的 `real_delete` 保持真实删除。
- 页面中文优先；`LEF`、`GDS`、`RTL`、`STA`、`Summary-only` 等专业词汇可保留。
- 不覆盖当前工作区中与本计划无关的未提交修改。

---

## Current Baseline And Acceptance Contract

当前样例：

```text
work/library_registry_smoke/catalog/html/libraries/
  ip_vendor_C.openroad_platform.openroad_sky130ram/
  versions/20260626_sky130ram_update/index.html
```

已确认的问题：

1. `DOC_UPDATE` 使用 `out_of_scope_missing`，但页面仍显示“删除 42”。
2. “当前数量”实际是本次原始交付包数量，却容易被理解为组合后有效版数量。
3. 1600x1200 首屏被默认展开的“事实源状态”占据，真正的 View Matrix 不可见。
4. 页面 Shell、结论卡、矩阵 Panel 和内层标题重复展示状态与标题。
5. “按使用场景查看影响”只是静态关联，不是影响分析。
6. “你需要确认”包含通用教程，而不是由当前证据生成的未决事实。
7. Unknown 和聚合数字不保证有具体路径或完整证据入口。

目标页面顺序固定为：

```text
页面标题与版本元数据
-> 版本使用结论
-> View 变化/覆盖矩阵
-> 待确认事实
-> 变化文件明细（折叠）
-> 正式放行状态（折叠）
-> 事实源与审计证据（折叠）
```

目标 IP 审查投影接口：

```python
{
    "schema_version": "ip_user_view.v2",
    "review_mode": "baseline | first_version | blocked_base",
    "decision": {
        "status": "READY | USAGE_REVIEW_REQUIRED | BLOCKED",
        "label": "可接入 | 需审查后使用 | 暂不可判断",
        "reason": "由当前事实生成的单一主因",
    },
    "comparison": {
        "scope": "full | incremental",
        "delete_semantics": "real_delete | out_of_scope_missing",
        "visible_counts": {"added": 0, "removed": 0, "changed": 0},
        "baseline_only_count": 0,
        "baseline_only_label": "基准存在、本包未携带（不代表删除）",
    },
    "inventory_scope": {
        "delivery_file_count": 0,
        "delivery_view_counts": {},
        "candidate_effective_file_count": None,
        "candidate_effective_view_counts": {},
        "candidate_effective_available": False,
    },
    "view_rows": [],
    "related_usage_sections": [],
    "pending_fact_items": [],
    "evidence_links": {},
}
```

## File Responsibility Map

| File | Responsibility after this change |
| --- | --- |
| `src/lib_guard/review/model_rules.py` | 只定义 package comparison/delete semantics；不渲染 HTML。 |
| `src/lib_guard/render/version_detail_context.py` | 读取 review window 与 candidate effective manifest 摘要，提供组合后文件类型数量。 |
| `src/lib_guard/render/version_review_model.py` | 将 raw scan/diff/effective facts 转换成 `ip_user_view.v2` 审查投影。 |
| `src/lib_guard/render/version_review_render.py` | 只渲染 `ip_user_view.v2`，不重新推断变化或状态。 |
| `src/lib_guard/render/version_detail_report.py` | 组装页面、链接和折叠审计区；不再维护用户判断规则。 |
| `src/lib_guard/test/test_version_detail_ui_contract.py` | 锁定语义、顺序、容量和中文文案合同。 |
| `docs/architecture.md` | 记录 raw facts 与 IP review projection 的边界。 |

---

### Task 1: Lock Incremental Versus Full Change Semantics

**Files:**
- Modify: `src/lib_guard/render/version_review_model.py:242-414`
- Modify: `src/lib_guard/render/version_review_model.py:467-598`
- Create: `src/lib_guard/test/test_version_detail_ui_contract.py`

**Interfaces:**
- Consumes: `model["delete_semantics"]`, `model["comparison_semantics"]`, `model["file_changes"]`。
- Produces: `build_ip_change_projection(model, file_changes) -> dict[str, Any]`。
- Invariant: raw `file_changes` 不修改；只有 IP review projection 改变展示分类。

- [ ] **Step 1: Write failing tests for DOC_UPDATE and FULL delete semantics**

```python
import unittest

from lib_guard.render.version_review_model import build_ip_change_projection


class VersionDetailUiContractTest(unittest.TestCase):
    def test_incremental_missing_files_are_not_real_deletes(self) -> None:
        changes = [
            {"change": "ADDED", "file_type": "doc", "path": "doc/release_note.txt"},
            {"change": "CHANGED", "file_type": "doc", "path": "SOURCE.md"},
            {"change": "REMOVED", "file_type": "lef", "path": "LEF/a.lef"},
        ]
        result = build_ip_change_projection(
            {"comparison_semantics": "incremental", "delete_semantics": "out_of_scope_missing"},
            changes,
        )

        self.assertEqual(result["visible_counts"], {"added": 1, "removed": 0, "changed": 1})
        self.assertEqual(result["baseline_only_count"], 1)
        self.assertEqual(result["baseline_only_changes"][0]["path"], "LEF/a.lef")
        self.assertNotIn("LEF/a.lef", [item["path"] for item in result["visible_changes"]])

    def test_full_package_missing_files_remain_real_deletes(self) -> None:
        changes = [{"change": "REMOVED", "file_type": "lef", "path": "LEF/a.lef"}]
        result = build_ip_change_projection(
            {"comparison_semantics": "full", "delete_semantics": "real_delete"},
            changes,
        )

        self.assertEqual(result["visible_counts"], {"added": 0, "removed": 1, "changed": 0})
        self.assertEqual(result["baseline_only_count"], 0)
        self.assertEqual(result["visible_changes"][0]["path"], "LEF/a.lef")
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_version_detail_ui_contract.VersionDetailUiContractTest.test_incremental_missing_files_are_not_real_deletes \
  src.lib_guard.test.test_version_detail_ui_contract.VersionDetailUiContractTest.test_full_package_missing_files_remain_real_deletes -v
```

Expected: `ImportError` because `build_ip_change_projection` does not exist.

- [ ] **Step 3: Implement the pure comparison projection**

Add to `version_review_model.py`:

```python
def build_ip_change_projection(
    model: Mapping[str, Any],
    file_changes: list[Mapping[str, Any]],
) -> dict[str, Any]:
    delete_semantics = str(model.get("delete_semantics") or "real_delete")
    visible_changes: list[dict[str, Any]] = []
    baseline_only_changes: list[dict[str, Any]] = []
    counts = {"added": 0, "removed": 0, "changed": 0}

    for source in file_changes:
        item = dict(source)
        kind = str(item.get("change") or item.get("status") or "").upper()
        if kind == "REMOVED" and delete_semantics == "out_of_scope_missing":
            item["display_change"] = "BASELINE_ONLY"
            baseline_only_changes.append(item)
            continue
        if kind == "ADDED":
            counts["added"] += 1
        elif kind == "REMOVED":
            counts["removed"] += 1
        elif kind in {"CHANGED", "MODIFIED"}:
            counts["changed"] += 1
        item["display_change"] = kind or "UNKNOWN"
        visible_changes.append(item)

    return {
        "schema_version": "ip_change_projection.v1",
        "comparison_semantics": str(model.get("comparison_semantics") or "full"),
        "delete_semantics": delete_semantics,
        "visible_counts": counts,
        "visible_changes": visible_changes,
        "baseline_only_count": len(baseline_only_changes),
        "baseline_only_changes": baseline_only_changes,
        "baseline_only_label": "基准存在、本包未携带（不代表删除）",
    }
```

- [ ] **Step 4: Make View rows consume projected changes**

Change `_build_view_delta_rows()` to accept the projection and expose both real delta and baseline-only counts:

```python
projection = build_ip_change_projection(model, file_changes)
visible_changes = projection["visible_changes"]
baseline_only_changes = projection["baseline_only_changes"]
delta = _change_counts_by_view(visible_changes)
baseline_only_by_view = Counter(
    _canonical_view_type(item.get("file_type")) for item in baseline_only_changes
)
```

Each row must contain:

```python
{
    "delivery_count": current_total,
    "candidate_effective_count": None,
    "added": counts["added"],
    "removed": counts["removed"],
    "changed": counts["changed"],
    "baseline_only_count": baseline_only_by_view.get(view_type, 0),
}
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_ui_contract -v
```

Expected: both tests pass.

- [ ] **Step 6: Commit the semantic projection**

```bash
git add src/lib_guard/render/version_review_model.py src/lib_guard/test/test_version_detail_ui_contract.py
git commit -m "fix: project incremental omissions separately from deletes"
```

---

### Task 2: Distinguish Delivery Package From Candidate Effective Inventory

**Files:**
- Modify: `src/lib_guard/render/version_detail_context.py:17-170`
- Modify: `src/lib_guard/render/version_detail_report.py:823-1004`
- Modify: `src/lib_guard/render/version_review_model.py:188-231`
- Test: `src/lib_guard/test/test_version_detail_ui_contract.py`

**Interfaces:**
- Consumes: `candidate_effective_manifest` with `summary.file_count`, `summary.file_type_summary`, or `effective_files`.
- Produces: `VersionDetailReviewContext.candidate_effective_file_count: int | None` and `candidate_effective_file_type_counts: dict[str, int]`.
- Fallback: missing/invalid candidate manifest returns `None` and `{}`; it never falls back to raw delivery counts.

- [ ] **Step 1: Write a failing candidate-effective inventory test**

```python
def test_candidate_effective_inventory_is_separate_from_delivery_inventory(self) -> None:
    from lib_guard.render.version_review_model import build_ip_user_view_model

    result = build_ip_user_view_model(
        {
            "status": "CHANGED",
            "base_trust_status": "PASS",
            "comparison_semantics": "incremental",
            "delete_semantics": "out_of_scope_missing",
            "scan_evidence": {"file_count": 1, "inventory": {"counts": {"doc": 1}}},
            "candidate_effective_inventory": {
                "available": True,
                "file_count": 3,
                "file_type_counts": {"doc": 1, "lef": 1, "verilog": 1},
            },
            "file_changes": [
                {"change": "CHANGED", "file_type": "doc", "path": "doc/release_note.txt"}
            ],
            "lane_counts": {},
        }
    )

    rows = {row["view_type"]: row for row in result["view_rows"]}
    self.assertEqual(rows["doc_evidence"]["delivery_count"], 1)
    self.assertEqual(rows["doc_evidence"]["candidate_effective_count"], 1)
    self.assertEqual(rows["physical_abstract"]["delivery_count"], 0)
    self.assertEqual(rows["physical_abstract"]["candidate_effective_count"], 1)
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_version_detail_ui_contract.VersionDetailUiContractTest.test_candidate_effective_inventory_is_separate_from_delivery_inventory -v
```

Expected: FAIL because `view_rows` and candidate-effective counts are not available.

- [ ] **Step 3: Extend `VersionDetailReviewContext` with manifest summary fields**

Add fields:

```python
candidate_effective_file_count: int | None
candidate_effective_file_type_counts: dict[str, int]
```

Add a safe reader:

```python
def _candidate_inventory(manifest_path: str) -> tuple[int | None, dict[str, int]]:
    if not manifest_path:
        return None, {}
    manifest = _read_mapping(Path(manifest_path))
    if not manifest:
        return None, {}
    summary = _mapping(manifest.get("summary"))
    raw_counts = _mapping(summary.get("file_type_summary"))
    counts = {str(key): int(value or 0) for key, value in raw_counts.items()}
    effective_files = _mapping(manifest.get("effective_files"))
    file_count = int(summary.get("file_count") or len(effective_files))
    if not counts:
        for item in effective_files.values():
            if isinstance(item, Mapping):
                file_type = str(item.get("file_type") or "unknown")
                counts[file_type] = counts.get(file_type, 0) + 1
    return file_count, counts
```

Populate both active-window and standalone contexts from the resolved manifest path.

- [ ] **Step 4: Pass the candidate inventory into the update-detail model**

In `build_version_update_detail_model()` add:

```python
"candidate_effective_inventory": {
    "available": review_context.get("candidate_effective_file_count") is not None,
    "file_count": review_context.get("candidate_effective_file_count"),
    "file_type_counts": review_context.get("candidate_effective_file_type_counts") or {},
},
```

- [ ] **Step 5: Aggregate candidate counts through canonical View types**

In `build_ip_user_view_model()` compute:

```python
candidate_inventory = _as_mapping(model.get("candidate_effective_inventory"))
candidate_counts = _aggregate_counts_by_view(
    _as_mapping(candidate_inventory.get("file_type_counts"))
)
```

Expose `delivery_count` and `candidate_effective_count` per View. When no manifest exists, use `None`, never `0`.

- [ ] **Step 6: Run focused context and model tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_version_detail_ui_contract \
  src.lib_guard.test.test_version_detail_report -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit inventory-scope separation**

```bash
git add src/lib_guard/render/version_detail_context.py src/lib_guard/render/version_detail_report.py src/lib_guard/render/version_review_model.py src/lib_guard/test/test_version_detail_ui_contract.py
git commit -m "feat: separate delivery and candidate effective inventory"
```

---

### Task 3: Make The IP Decision And Pending Facts Data-Driven

**Files:**
- Modify: `src/lib_guard/render/version_review_model.py:417-598`
- Test: `src/lib_guard/test/test_version_detail_ui_contract.py`
- Test: `src/lib_guard/test/test_version_detail_report.py:614-860`

**Interfaces:**
- Consumes: `ip_change_projection`, View rows, unknown count, base/diff trust state.
- Produces: `ip_user_view.v2.decision`, `related_usage_sections`, `pending_fact_items`.
- Decision rule: evidence lane alone cannot change `READY` to `REVIEW_REQUIRED`.

- [ ] **Step 1: Write failing decision and wording tests**

```python
def test_lightweight_evidence_without_delta_does_not_force_review(self) -> None:
    from lib_guard.render.version_review_model import build_ip_user_view_model

    result = build_ip_user_view_model(
        {
            "status": "SAME",
            "base_trust_status": "PASS",
            "comparison_semantics": "full",
            "delete_semantics": "real_delete",
            "file_changes": [],
            "lane_counts": {"summary_only": 12, "metadata_only": 4},
            "scan_evidence": {"file_count": 16},
        }
    )

    self.assertEqual(result["decision"]["status"], "READY")
    self.assertNotIn("Summary-only", result["decision"]["reason"])

def test_usage_sections_are_labeled_as_association_not_proven_impact(self) -> None:
    from lib_guard.render.version_review_model import build_ip_user_view_model

    result = build_ip_user_view_model(
        {
            "status": "CHANGED",
            "base_trust_status": "PASS",
            "comparison_semantics": "full",
            "delete_semantics": "real_delete",
            "file_changes": [{"change": "CHANGED", "file_type": "lef", "path": "LEF/a.lef"}],
            "lane_counts": {"recommended_file_diff": 1},
        }
    )

    self.assertEqual(result["related_usage_sections"][0]["relation_kind"], "VIEW_ASSOCIATION")
    self.assertNotIn("已确认影响", str(result))
```

- [ ] **Step 2: Verify focused tests fail**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_version_detail_ui_contract.VersionDetailUiContractTest.test_lightweight_evidence_without_delta_does_not_force_review \
  src.lib_guard.test.test_version_detail_ui_contract.VersionDetailUiContractTest.test_usage_sections_are_labeled_as_association_not_proven_impact -v
```

Expected: FAIL because the current model uses lane counts in the decision and exposes `usage_area_sections`.

- [ ] **Step 3: Replace the decision rule**

Use this exact priority:

```python
if first_version:
    decision = {"status": "USAGE_REVIEW_REQUIRED", "label": "首版需审查", "reason": first_version_reason}
elif base_blocked or diff_missing:
    decision = {"status": "BLOCKED", "label": "暂不可判断", "reason": evidence_reason}
elif visible_delta_total or unknown_file_count:
    decision = {"status": "USAGE_REVIEW_REQUIRED", "label": "需审查后使用", "reason": delta_reason}
else:
    decision = {"status": "READY", "label": "可接入", "reason": no_delta_reason}
```

`summary_only`、`metadata_only` 和 `P0/P1` 只进入 evidence copy，不参与 `BLOCKED` 判断。

- [ ] **Step 4: Replace generic instructions with pending facts**

Generate only evidence-backed rows:

```python
pending_facts = []
for row in changed_view_rows:
    pending_facts.append(
        {
            "kind": "VIEW_DELTA",
            "view_type": row["view_type"],
            "label": row["view"],
            "summary": (
                f"新增 {row['added']} / 删除 {row['removed']} / 修改 {row['changed']}；"
                f"证据：{row['evidence_level']}"
            ),
            "file_count": row["delta_total"],
        }
    )
if unknown_file_count:
    pending_facts.append(
        {
            "kind": "UNKNOWN_FILES",
            "label": "待分类文件",
            "summary": f"当前交付包存在 {unknown_file_count} 个 Unknown 文件。",
            "file_count": unknown_file_count,
        }
    )
```

Remove fixed tutorial strings such as “按使用场景筛选……” from the model.

- [ ] **Step 5: Rename usage groups**

Rename `_build_usage_area_sections()` to `_build_related_usage_sections()` and return:

```python
{
    "area": area,
    "relation_kind": "VIEW_ASSOCIATION",
    "summary": f"关联 {types}；本次可见变化 {delta_total} 个。",
    "evidence": evidence_text,
}
```

- [ ] **Step 6: Bump the internal projection schema**

Return `schema_version="ip_user_view.v2"`. Remove `must_check_items` and `usage_area_sections`; use only `pending_fact_items` and `related_usage_sections` because repository search confirms there are no external consumers.

- [ ] **Step 7: Run model tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_version_detail_ui_contract \
  src.lib_guard.test.test_version_detail_report -q
```

Expected: all tests pass after updating old assertions to the v2 contract.

- [ ] **Step 8: Commit the v2 IP review contract**

```bash
git add src/lib_guard/render/version_review_model.py src/lib_guard/test/test_version_detail_ui_contract.py src/lib_guard/test/test_version_detail_report.py
git commit -m "refactor: make version review decision evidence driven"
```

---

### Task 4: Reorder The Page And Remove Duplicate Information

**Files:**
- Modify: `src/lib_guard/render/version_review_render.py:72-185`
- Modify: `src/lib_guard/render/version_detail_report.py:1289-1660`
- Modify: `src/lib_guard/render/version_detail_report.py:2037-2072`
- Modify: `src/lib_guard/render/version_detail_report.py:2183-2222`
- Test: `src/lib_guard/test/test_version_detail_ui_contract.py`

**Interfaces:**
- Consumes: only `ip_user_view.v2` for the default user section.
- Produces: exactly one primary status, one View Matrix heading, and the fixed page order from this plan.
- Fact-source and management panels remain available but default closed.

- [ ] **Step 1: Write failing DOM-order tests using the standard library**

```python
import tempfile
from pathlib import Path
from unittest.mock import patch

from lib_guard.render.version_detail_report import render_version_detail_page


def _render_doc_update_page(self) -> str:
    ip_model = {
        "schema_version": "ip_user_view.v2",
        "decision": {
            "status": "USAGE_REVIEW_REQUIRED",
            "label": "需审查后使用",
            "reason": "文档视图存在 2 个真实变化。",
        },
        "comparison": {
            "scope": "incremental",
            "delete_semantics": "out_of_scope_missing",
            "visible_counts": {"added": 1, "removed": 0, "changed": 1},
            "baseline_only_count": 1,
            "baseline_only_label": "基准存在、本包未携带（不代表删除）",
        },
        "inventory_scope": {
            "delivery_file_count": 2,
            "delivery_view_counts": {"doc_evidence": 2},
            "candidate_effective_file_count": None,
            "candidate_effective_view_counts": {},
            "candidate_effective_available": False,
        },
        "view_rows": [
            {
                "view_type": "doc_evidence",
                "view": "文档与发布证据",
                "delivery_count": 2,
                "candidate_effective_count": None,
                "added": 1,
                "removed": 0,
                "changed": 1,
                "baseline_only_count": 0,
                "delta_total": 2,
                "evidence_level": "人工审查",
                "usage_area": "证据与豁免",
                "changed_examples": ["doc/release_note.txt", "SOURCE.md"],
                "current_examples": ["doc/release_note.txt", "SOURCE.md"],
                "full_evidence_href": "/tmp/file_diff.json",
            }
        ],
        "related_usage_sections": [],
        "pending_fact_items": [],
        "evidence_links": {"diff_file_changes": "/tmp/file_diff.json"},
    }
    model = {
        "version_id": "doc_update",
        "target_version": "doc_update",
        "base_ref": "previous_effective",
        "base_version": "full_v1",
        "base_trust_status": "PASS",
        "review_mode": "baseline",
        "headline": "新增 1 / 删除 0 / 修改 1。",
        "confidence_note": "增量对比；本包未携带不代表删除。",
        "ip_user_view_model": ip_model,
        "version_review_model": {"ip_user_view": ip_model},
        "scan_context": {},
        "file_changes": [],
        "evidence_state": {
            "principle": "HTML 是事实投影。",
            "sources": [{"name": "diff", "role": "变化事实", "status": "PRESENT", "artifacts": [], "message": "已生成"}],
        },
    }
    lib = {"library_id": "ip/demo", "library_name": "demo", "display_name": "demo"}
    version = {"version_id": "doc_update", "review_gate": {}}
    with tempfile.TemporaryDirectory() as td:
        with patch("lib_guard.render.version_detail_report.build_version_update_detail_model", return_value=model):
            page = Path(render_version_detail_page(Path(td) / "html", lib, version))
        return page.read_text(encoding="utf-8")


def test_view_matrix_precedes_fact_source_audit(self) -> None:
    html = self._render_doc_update_page()
    self.assertLess(html.index("视图变化矩阵"), html.index("事实源与审计证据"))
    self.assertNotIn("<details class='panel collapsible' open><summary class='panel-head'><div><h2>事实源", html)

def test_page_has_one_primary_decision_and_one_matrix_heading(self) -> None:
    html = self._render_doc_update_page()
    self.assertEqual(html.count("需审查后使用"), 1)
    self.assertEqual(html.count(">视图变化矩阵<"), 1)
    self.assertNotIn("版本详情是唯一审查投影", html)
```

Attach `_render_doc_update_page` as a private method on `VersionDetailUiContractTest`. It patches only the completed update-detail model, calls the real page renderer, and never reads `work/` artifacts.

- [ ] **Step 2: Verify DOM-order tests fail**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_version_detail_ui_contract.VersionDetailUiContractTest.test_view_matrix_precedes_fact_source_audit \
  src.lib_guard.test.test_version_detail_ui_contract.VersionDetailUiContractTest.test_page_has_one_primary_decision_and_one_matrix_heading -v
```

Expected: FAIL because fact sources are currently prepended and open.

- [ ] **Step 3: Reduce the overview to four non-duplicated facts**

Render these cells only:

```text
判断依据
对比基准
交付范围
可见变化
```

The Shell badge remains the only place that displays the short decision label such as “需审查后使用”. “判断依据” displays only the evidence-backed reason. Remove “审查对象” because the page title already identifies the version. Replace “版本详情是唯一审查投影” with no copy. Keep `库工作台` and rename `扫描目录` to `扫描证据`.

Read the v2 model explicitly; do not retain fallback inference in the renderer:

```python
decision_model = _as_mapping(ip_model.get("decision"))
comparison = _as_mapping(ip_model.get("comparison"))
inventory_scope = _as_mapping(ip_model.get("inventory_scope"))
decision = str(decision_model.get("status") or "BLOCKED")
decision_reason = str(decision_model.get("reason") or "缺少 IP 审查投影。")
visible_counts = _as_mapping(comparison.get("visible_counts"))
```

- [ ] **Step 4: Keep only one primary decision badge**

Keep `ui.review_page_shell(..., decision=usage_decision)` as the single decision badge. Set `usage_decision` from `_as_mapping(ip_model.get("decision")).get("status")`, remove `ui.badge(decision, review_text)` from `_version_overview_panel()`, and do not repeat the short decision label inside the overview cells.

- [ ] **Step 5: Render the matrix before all audit material**

Change `render_version_update_detail_panel()` so it returns only the primary review and bounded file details:

```python
main_review = render_ip_user_view(ip_model)
secondary = lead + callouts + focus_changes
return ui.panel(panel_title, panel_subtitle, main_review + secondary)
```

Then assemble the lower sections in `render_version_detail_page()`, where the real `version` record is already available:

```python
body = (
    _version_detail_styles()
    + _version_overview_panel(...)
    + "<main class='version-main'>"
    + render_version_update_detail_panel(model)
    + _review_gate_summary_panel(version)
    + _evidence_state_panel(model)
    + "</main>"
)
```

- [ ] **Step 6: Rename and close the fact-source panel**

Change:

```python
return ui.collapsible_panel(
    "事实源与审计证据",
    "供排查页面新鲜度和证据来源；不参与默认 IP 使用判断。",
    body,
    open=False,
)
```

- [ ] **Step 7: Remove duplicate matrix and instructional copy**

`render_ip_user_view()` must not render a second `<h3>视图变化矩阵</h3>` when the outer panel already owns that title. Remove “IP 使用者默认视图”和“管理门禁、包根匹配算法……”说明框。Change `_view_delta_items()` to consume `ip_model["view_rows"]` and keep rows when any of `delivery_count`, `candidate_effective_count`, `delta_total`, or `baseline_only_count` is non-zero. Render `related_usage_sections` under “关联使用场景” and `pending_fact_items` under “待确认事实”.

- [ ] **Step 8: Run render contract tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_version_detail_ui_contract \
  src.lib_guard.test.test_version_detail_report -q
```

Expected: all tests pass.

- [ ] **Step 9: Commit page ordering**

```bash
git add src/lib_guard/render/version_review_render.py src/lib_guard/render/version_detail_report.py src/lib_guard/test/test_version_detail_ui_contract.py
git commit -m "refactor: put IP view facts first on version detail"
```

---

### Task 5: Make Every Count Traceable Without Bloated HTML

**Files:**
- Modify: `src/lib_guard/render/version_review_model.py:280-414`
- Modify: `src/lib_guard/render/version_review_render.py:72-185`
- Modify: `src/lib_guard/render/version_detail_report.py:340-377`
- Modify: `src/lib_guard/render/version_detail_report.py:1104-1136`
- Test: `src/lib_guard/test/test_version_detail_ui_contract.py`

**Interfaces:**
- Consumes: current scan review artifacts, diff trace links, projected visible/baseline-only changes.
- Produces: each View row includes samples, total count and an existing full-evidence link.
- Capacity: inline path samples are capped at 8 per View; the shared detail table remains capped at 120 rows.

- [ ] **Step 1: Write failing traceability and capacity tests**

```python
def test_unknown_count_always_has_path_or_full_evidence_link(self) -> None:
    from lib_guard.render.version_review_model import build_ip_user_view_model

    result = build_ip_user_view_model(
        {
            "status": "CHANGED",
            "base_trust_status": "PASS",
            "comparison_semantics": "full",
            "delete_semantics": "real_delete",
            "scan_evidence": {
                "file_count": 2,
                "counts": {"unknown": 2},
                "inventory": {
                    "files": [
                        {"path": "misc/a.foo", "file_type": "unknown"},
                        {"path": "misc/b.foo", "file_type": "unknown"},
                    ]
                },
                "review_links": {"unknown_files": "/tmp/unknown_files.tsv"},
            },
            "file_changes": [],
            "lane_counts": {},
            "trace_links": {},
        }
    )
    unknown = next(row for row in result["view_rows"] if row["view_type"] == "unknown")
    self.assertEqual(unknown["delivery_count"], 2)
    self.assertTrue(unknown["current_examples"] or unknown["full_evidence_href"])

def test_large_diff_caps_inline_rows_and_keeps_full_evidence_link(self) -> None:
    from lib_guard.render.version_detail_report import render_version_update_detail_panel
    from lib_guard.render.version_review_model import build_ip_user_view_model

    changes = [
        {
            "change": "changed",
            "file_type": "lef",
            "path": f"LEF/macro_{index:04d}.lef",
            "review_lane": "P0",
        }
        for index in range(1000)
    ]
    model = {
        "status": "CHANGED",
        "base_trust_status": "PASS",
        "base_ref": "previous_effective",
        "base_version": "full_v1",
        "comparison_semantics": "full",
        "delete_semantics": "real_delete",
        "file_changes": changes,
        "lane_counts": {"recommended_file_diff": 1000},
        "trace_links": {
            "file_diff": "/tmp/file_diff.json",
            "diff_report": "/tmp/diff_html/index.html",
        },
        "headline": "修改 1000 个文件。",
        "confidence_note": "全量对比。",
    }
    model["ip_user_view_model"] = build_ip_user_view_model(model)
    model["version_review_model"] = {"ip_user_view": model["ip_user_view_model"]}
    html = render_version_update_detail_panel(model)
    self.assertLessEqual(html.count("<tr>"), 160)
    self.assertIn("完整变化证据", html)
    self.assertIn("file_diff.json", html)
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_version_detail_ui_contract.VersionDetailUiContractTest.test_unknown_count_always_has_path_or_full_evidence_link \
  src.lib_guard.test.test_version_detail_ui_contract.VersionDetailUiContractTest.test_large_diff_caps_inline_rows_and_keeps_full_evidence_link -v
```

Expected: FAIL because rows do not expose a full-evidence link and Unknown may show no samples.

- [ ] **Step 3: Add evidence links to the IP projection**

Map existing artifacts only:

```python
scan_review_links = _as_mapping(scan_evidence.get("review_links"))
trace_links = _as_mapping(model.get("trace_links"))
evidence_links = {
    "scan_files_by_view": scan_review_links.get("files_by_view") or "",
    "scan_unknown_files": scan_review_links.get("unknown_files") or "",
    "diff_file_changes": trace_links.get("file_diff") or "",
    "diff_report": trace_links.get("diff_report") or "",
}
```

Extend `_build_scan_evidence_model()` with links to existing `review/files_by_view.tsv` and `review/unknown_files.tsv`. Extend `trace_links` with `diff_dir / "diff_html" / "index.html"` when it exists. For each View row, select the relevant `full_evidence_href`; do not create a new fact artifact in the render path.

- [ ] **Step 4: Increase useful samples but cap them deterministically**

Use eight sorted paths:

```python
def _short_examples(values: list[str], *, limit: int = 8) -> list[str]:
    return sorted(dict.fromkeys(value for value in values if value))[:limit]
```

The row must also expose `sample_count` and `total_evidence_count` so UI can say “显示 8 / 42”。

- [ ] **Step 5: Reduce the matrix to five columns**

Render:

```text
View
本包 / 候选有效版
真实变化
证据与关联场景
文件
```

The “文件” cell displays samples and, when truncated, an existing full-evidence link. Remove the redundant status column and generic explanation column.

- [ ] **Step 6: Render baseline-only omissions explicitly**

For incremental packages, the change cell must use:

```text
新增 1 / 删除 0 / 修改 1
基准存在、本包未携带 42（不代表删除）
```

Do not use warning/red styling for baseline-only counts.

- [ ] **Step 7: Run capacity tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_ui_contract -q
```

Expected: all tests pass; the synthetic 1000-change HTML has at most 160 table rows and contains a full evidence link.

- [ ] **Step 8: Commit traceability changes**

```bash
git add src/lib_guard/render/version_review_model.py src/lib_guard/render/version_review_render.py src/lib_guard/render/version_detail_report.py src/lib_guard/test/test_version_detail_ui_contract.py
git commit -m "feat: link version detail counts to bounded file evidence"
```

---

### Task 6: Add Scenario, DOM And Desktop Visual Regression Coverage

**Files:**
- Modify: `src/lib_guard/test/test_version_detail_ui_contract.py`
- Modify: `src/lib_guard/test/test_version_detail_report.py`
- Modify: `docs/test_plan.md`

**Interfaces:**
- Consumes: `render_version_detail_page()` and pure `build_ip_user_view_model()`.
- Produces: regression coverage for eight required review scenarios without Playwright dependency in CI.

- [ ] **Step 1: Add a reusable fixture builder**

Implement helpers in the new test module:

```python
def _version_model(
    *,
    package_type: str,
    comparison_semantics: str,
    delete_semantics: str,
    changes: list[dict[str, object]],
    status: str = "CHANGED",
    base_status: str = "PASS",
) -> dict[str, object]:
    return {
        "status": status,
        "base_trust_status": base_status,
        "package_type": package_type,
        "comparison_semantics": comparison_semantics,
        "delete_semantics": delete_semantics,
        "file_changes": changes,
        "lane_counts": {},
        "scan_evidence": {"file_count": len(changes), "unknown_file_count": 0},
        "trace_links": {"file_diff": "/tmp/file_diff.json"},
    }
```

- [ ] **Step 2: Cover all required semantic scenarios**

Add tests named exactly:

```text
test_first_full_version_uses_coverage_not_empty_diff
test_doc_update_omissions_are_not_deletes
test_full_package_real_delete_is_visible
test_repackage_match_does_not_become_content_change
test_missing_scan_or_diff_never_renders_no_change
test_unknown_files_are_traceable
test_large_change_set_has_bounded_dom
test_stale_compare_context_blocks_decision
```

- [ ] **Step 3: Add DOM hierarchy assertions**

Use string positions or `html.parser.HTMLParser` to assert:

```text
版本使用结论 < 视图变化矩阵 < 待确认事实 < 变化文件明细 < 事实源与审计证据
```

Also assert that the fact-source `<details>` has no `open` attribute.

- [ ] **Step 4: Update desktop visual smoke instructions**

Add to `docs/test_plan.md`:

```bash
PAGE="$WORK/catalog/html/libraries/ip_vendor_C.openroad_platform.openroad_sky130ram/versions/20260626_sky130ram_update/index.html"
google-chrome --headless=new --disable-gpu --no-sandbox \
  --window-size=1600,1200 --screenshot=/tmp/version_detail_1600.png "file://$PAGE"
google-chrome --headless=new --disable-gpu --no-sandbox \
  --window-size=1920,1080 --screenshot=/tmp/version_detail_1920.png "file://$PAGE"
```

Acceptance:

```text
1600x1200 首屏必须出现 View Matrix 表头和至少一行。
1920x1080 不得出现横向页面级滚动条。
事实源与审计证据默认折叠。
长路径只能在表格内部滚动或换行，不能撑宽页面。
```

- [ ] **Step 5: Run all Version Detail tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_version_detail_ui_contract \
  src.lib_guard.test.test_version_detail_report \
  src.lib_guard.test.test_review_state_fast_render \
  src.lib_guard.test.test_render_impact -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the regression suite**

```bash
git add src/lib_guard/test/test_version_detail_ui_contract.py src/lib_guard/test/test_version_detail_report.py docs/test_plan.md
git commit -m "test: lock version detail review and layout contracts"
```

---

### Task 7: Document The Projection Boundary And Run End-To-End Verification

**Files:**
- Modify: `docs/architecture.md:126-176`
- Modify: `docs/basic_tutorial.md`
- Verify: generated HTML under a new `work/version_detail_ui_hardening/` workspace

**Interfaces:**
- Documents: raw facts -> review projection -> HTML.
- No new CLI command or user workflow is introduced.

- [ ] **Step 1: Document raw facts versus user-visible projection**

Add this contract to `docs/architecture.md`:

```text
Raw diff 记录扫描快照之间的机械差异。
IP review projection 按 package comparison semantics 解释这些差异。

FULL + real_delete:
  REMOVED -> 页面“删除”

PARTIAL/HOTFIX/DOC_UPDATE + out_of_scope_missing:
  REMOVED -> 页面“基准存在、本包未携带（不代表删除）”

HTML 只渲染 projection，不回写 raw diff，也不重新推断 package type。
```

- [ ] **Step 2: Update the tutorial’s page-reading order**

In `docs/basic_tutorial.md`, keep only:

```text
1. 看版本使用结论与可信基准。
2. 看 View Matrix 的本包数量、候选有效版数量和真实变化。
3. 展开待确认事实和相关文件。
4. 只有排查证据新鲜度时才展开事实源与审计证据。
```

Do not add new operational commands.

- [ ] **Step 3: Run compile and the complete unit suite**

Run:

```bash
PYTHONPATH=src python3 -m compileall -q src
PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q
PYTHONPATH=src python3 -m lib_guard.short_cli --help
PYTHONPATH=src python3 -m lib_guard.cli --help
```

Expected: compile succeeds, all tests pass, both help commands exit 0.

- [ ] **Step 4: Regenerate representative pages**

Use an isolated work directory and the existing fixture catalog; do not overwrite prior manual-review reports:

```bash
setenv PROJ /home/polaris/proj/mx/ai_lib/repo
setenv WORK $PROJ/work/version_detail_ui_hardening
setenv RAW $PROJ/tests/fixtures/raw

$PROJ/scripts/lg.csh init "$WORK" --raw-root "$RAW" --library-type ip
$PROJ/scripts/lg.csh library apply
$PROJ/scripts/lg.csh cat --with-evidence
$PROJ/scripts/lg.csh scan vendor_C.openroad_platform.openroad_sky130ram 20260626_sky130ram_update
$PROJ/scripts/lg.csh cmp vendor_C.openroad_platform.openroad_sky130ram 20260626_sky130ram_update \
  --base 20260619_sky130ram --scan-if-missing
```

Expected:

```text
Version Detail reports DOC_UPDATE as incremental.
The page does not say “删除 42”.
The page says “基准存在、本包未携带 42（不代表删除）”.
View Matrix is visible in the 1600x1200 first viewport.
```

- [ ] **Step 5: Measure the generated page**

Run:

```bash
setenv PAGE "$WORK/catalog/html/libraries/ip_vendor_C.openroad_platform.openroad_sky130ram/versions/20260626_sky130ram_update/index.html"
wc -c "$PAGE"
grep -o '<tr' "$PAGE" | wc -l
grep -o '<details' "$PAGE" | wc -l
```

Acceptance:

```text
The representative page remains below 500000 bytes.
The 1000-change synthetic test remains at or below 160 table rows.
No raw JSON body is embedded in the main HTML.
```

- [ ] **Step 6: Inspect the final diff for scope violations**

Run:

```bash
git diff --check
git diff --stat
git status --short
```

Expected: no whitespace errors; no changes under discover/parser/release/CLI modules; unrelated pre-existing worktree changes remain untouched.

- [ ] **Step 7: Commit documentation and final integration**

```bash
git add docs/architecture.md docs/basic_tutorial.md
git commit -m "docs: explain version detail review projection semantics"
```

---

## Final Review Checklist

- [ ] DOC/FIX/PARTIAL package omissions are never labeled as real deletes.
- [ ] FULL package real deletes remain visible.
- [ ] Delivery package counts and candidate-effective counts are separately labeled.
- [ ] Summary-only/Metadata-only do not independently force review or blocking.
- [ ] “使用场景影响” is replaced by deterministic “关联使用场景”.
- [ ] The first viewport shows the View Matrix before fact-source audit information.
- [ ] Only one primary decision and one matrix heading are rendered.
- [ ] Pending facts are generated from current evidence; generic tutorial instructions are removed.
- [ ] Every non-zero View/Unknown count has file samples or an existing full-evidence link.
- [ ] Large diffs keep bounded DOM size and link to full evidence.
- [ ] Fact-source and management audit sections remain available but default closed.
- [ ] No new page, CLI, dependency, state machine, database, scoring or AI inference was introduced.
- [ ] Full compile, unit tests and CLI help smoke tests pass.
