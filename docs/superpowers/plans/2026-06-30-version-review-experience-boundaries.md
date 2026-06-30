# Version Review Experience Boundaries Implementation Plan

Status: current

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the Version Review experience and engineering-boundary hardening without changing the main Catalog -> Version Review -> Release flow.

**Architecture:** Treat the current `codex/p0-flow-logic-fixes` branch as the baseline: base selection, model-driven HTML, lane constants, explicit Markdown export, and common render helper split already exist. This plan adds specification-level field aliases, lane-count semantics, clearer Version Detail table columns, tighter expert `--force-large` behavior checks, and user-facing documentation parity. All production changes stay behind `version_update_detail_model`, `short_cli` manual `fd`, and render-only helpers.

**Tech Stack:** Python 3.11 standard library, `unittest`, argparse-based short CLI, static HTML render helpers, JSON diff artifacts, Markdown docs.

---

## Scope Check

The attached spec has eight tasks, but the current branch already implements most P0/P1 behavior:

- `refresh` defaults to current/previous effective semantics.
- HTML renders from `version_update_detail_model` and does not read `current_lib_diff.md`.
- `SUMMARY_ONLY_TYPES`, `BINARY_METADATA_ONLY_TYPES`, and safe default file-diff lanes are centralized.
- Pairwise default tasks exclude summary-only and metadata-only types.
- `--force-large` exists for explicit manual `fd`.
- Version Detail already shows headline, base trust, status copy, lane groups, view/type/release/diff issue evidence, and Markdown export parity.
- `catalog_render_common.py` exists and repository cleanup tests guard private-helper drift.

Do not rewrite the main flow. This plan focuses on the remaining seams between the spec vocabulary and the shipped branch:

- Add `lane_counts`, `summary_only_changes`, and `metadata_only_changes` as first-class model fields.
- Make Version Detail lane tables use columns matching reviewer intent: priority, file type, path, evidence/reason, and command where relevant.
- Tighten `--force-large` tests around exact user copy and automatic-task non-inheritance.
- Bring `README.md` and `docs/user_guide.md` up to the same clarity level as `docs/cli_reference.md`.
- Add final fixture smoke commands that exercise the current local OpenROAD workspace when available.

## File Structure

Modify these files:

- `src/lib_guard/render/version_detail_report.py`
  - Add `lane_counts`, `summary_only_changes`, `metadata_only_changes`.
  - Add lane-specific table row helpers for clearer UI columns.
  - Keep `render_version_detail_page(..., export_markdown=False)` explicit.
- `src/lib_guard/short_cli.py`
  - Keep `--force-large` scoped to explicit manual `fd`.
  - Tighten the error message to match the user-facing spec.
- `src/lib_guard/test/test_version_detail_report.py`
  - Add spec-named tests for headline/lane counts, section columns, base warnings, release regressions, and Markdown non-input behavior.
- `src/lib_guard/test/test_pairwise_policy.py`
  - Add spec-named tests for manual `--force-large` and automatic pairwise non-inheritance.
- `src/lib_guard/test/test_scan_pipeline.py`
  - Add help/docs guard text if missing after the short CLI message change.
- `README.md`
  - Add concise current workflow and lane policy wording.
- `docs/user_guide.md`
  - Add practical summary-only / metadata-only / `--force-large` guidance.
- `docs/data_contract.md`
  - Add `lane_counts`, `summary_only_changes`, and `metadata_only_changes` to the reviewer model fields.

Do not modify generated `work/` HTML or raw OpenROAD fixtures in this plan.

## Task 1: Add Spec Vocabulary Tests For Model Fields

**Files:**
- Modify: `src/lib_guard/test/test_version_detail_report.py`
- Test: `src/lib_guard/test/test_version_detail_report.py`

- [ ] **Step 1: Write the failing model vocabulary test**

Add this test after `test_version_update_detail_model_exposes_headline_confidence_and_primary_action`:

```python
    def test_version_detail_headline_mentions_base_and_lane_counts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)

            from lib_guard.render.version_detail_report import build_version_update_detail_model

            model = build_version_update_detail_model(root / "html", lib, version)

            self.assertIn("当前版本相对 explicit", model["headline"])
            self.assertIn("2 个建议下钻", model["headline"])
            self.assertIn("5 个已按 Summary/Metadata-only 审查", model["headline"])
            self.assertEqual(
                model["lane_counts"],
                {
                    "recommended_file_diff": 2,
                    "summary_only": 3,
                    "metadata_only": 3,
                    "blocking_issues": 0,
                },
            )
            self.assertIs(model["summary_only_changes"], model["summary_only_reviewed"])
            self.assertIs(model["metadata_only_changes"], model["metadata_only_reviewed"])
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
cd /home/polaris/proj/mx/ai_lib/repo
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_version_detail_headline_mentions_base_and_lane_counts -q
```

Expected: FAIL with `KeyError: 'lane_counts'`.

- [ ] **Step 3: Add lane counts to the model**

In `src/lib_guard/render/version_detail_report.py`, inside `build_version_update_detail_model()` after `recommended_count` and `reviewed_count` are computed, add:

```python
    blocking_issues = 0
    for issue in _as_mapping(diff_issues).get("issues", []) or []:
        if isinstance(issue, Mapping) and str(issue.get("severity") or "").lower() in {"blocker", "blocking", "error"}:
            blocking_issues += 1
    lane_counts = {
        "recommended_file_diff": len(recommended_file_diff),
        "summary_only": len(summary_only_reviewed),
        "metadata_only": len(metadata_only_reviewed),
        "blocking_issues": blocking_issues,
    }
```

Then add these keys in the `model = { ... }` literal near the existing lane fields:

```python
        "lane_counts": lane_counts,
        "summary_only_changes": summary_only_reviewed,
        "metadata_only_changes": metadata_only_reviewed,
```

Keep the existing `summary_only_reviewed` and `metadata_only_reviewed` keys. Do not remove `metadata_only_changes = summary_only_reviewed + metadata_only_reviewed` unless all existing tests and Markdown export are updated in the same task; for this task, preserve backward compatibility by adding the explicit new fields.

- [ ] **Step 4: Run the new test**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_version_detail_headline_mentions_base_and_lane_counts -q
```

Expected: PASS.

- [ ] **Step 5: Run the full Version Detail test file**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lib_guard/test/test_version_detail_report.py src/lib_guard/render/version_detail_report.py
git commit -m "feat: add version detail lane counts"
```

## Task 2: Make Lane Tables Match Reviewer Meaning

**Files:**
- Modify: `src/lib_guard/test/test_version_detail_report.py`
- Modify: `src/lib_guard/render/version_detail_report.py`
- Test: `src/lib_guard/test/test_version_detail_report.py`

- [ ] **Step 1: Write the failing UI column test**

Add this test after `test_version_detail_groups_file_diff_evidence_by_review_lane`:

```python
    def test_update_detail_lane_sections_use_reviewer_columns(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib, version = _write_version_detail_lane_fixture(root)

            from lib_guard.render.version_detail_report import (
                build_version_update_detail_model,
                render_version_update_detail_panel,
            )

            model = build_version_update_detail_model(root / "html", lib, version)
            html = render_version_update_detail_panel(model)

            recommended = html.split("Recommended File Diff", 1)[1].split("Summary-only Reviewed", 1)[0]
            summary = html.split("Summary-only Reviewed", 1)[1].split("Metadata-only Reviewed", 1)[0]
            metadata = html.split("Metadata-only Reviewed", 1)[1].split("Release note", 1)[0]

            for header in ["Priority", "file_type", "path", "reason", "command"]:
                self.assertIn(header, recommended)
            for header in ["file_type", "path", "summary evidence", "reason"]:
                self.assertIn(header, summary)
            for header in ["file_type", "path", "metadata evidence", "reason"]:
                self.assertIn(header, metadata)
            self.assertIn("Run recommended File Diff", recommended)
            self.assertIn("hash/size/path/count", metadata)
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report.VersionDetailReportTest.test_update_detail_lane_sections_use_reviewer_columns -q
```

Expected: FAIL because the current lane tables use generic Chinese columns and the recommended section does not include the command inline.

- [ ] **Step 3: Add lane-specific row helpers**

In `src/lib_guard/render/version_detail_report.py`, add these helpers after `_file_change_rows_for()`:

```python
def _command_for_path(model: Mapping[str, Any], path: Any) -> str:
    target = str(path or "")
    for item in model.get("file_diff_recommendations", []) or []:
        if isinstance(item, Mapping) and str(item.get("path") or "") == target:
            return str(item.get("command") or "")
    return ""


def _recommended_file_diff_rows(model: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in model.get("recommended_file_diff", []) or []:
        if not isinstance(item, Mapping):
            continue
        command = _command_for_path(model, item.get("path"))
        rows.append(
            "<tr>"
            f"<td>{ui.badge(item.get('review_lane') or 'P1')}</td>"
            f"<td><code>{ui.esc(item.get('file_type') or '-')}</code></td>"
            f"<td><code>{ui.esc(item.get('path') or '-')}</code></td>"
            f"<td>{ui.esc(item.get('hint') or item.get('reason') or '-')}</td>"
            f"<td>{ui.command_chip(command, label='复制') if command else '-'}</td>"
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
            f"<td>{ui.esc(item.get('summary_evidence') or item.get('metadata_evidence') or item.get('hint') or '-')}</td>"
            f"<td>{ui.esc(item.get('reason') or item.get('hint') or '已完成摘要级审查')}</td>"
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
            f"<td>{ui.esc(item.get('metadata_evidence') or item.get('hint') or 'hash/size/path/count')}</td>"
            f"<td>{ui.esc(item.get('reason') or item.get('hint') or 'metadata-only 审查')}</td>"
            "</tr>"
        )
    return rows
```

- [ ] **Step 4: Use the lane-specific tables in the panel**

In `render_version_update_detail_panel()`, replace the three lane section table calls with:

```python
        + "<h3>Recommended File Diff</h3>"
        + catalog._scroll_table(
            ["Priority", "file_type", "path", "reason", "command"],
            _recommended_file_diff_rows(model),
            "暂无 P0/P1 文件级 Diff 建议。",
            "change-scroll",
        )
        + "<h3>Summary-only Reviewed</h3>"
        + "<div class='quality-note'>已完成摘要级审查；默认无需展开全文。</div>"
        + catalog._scroll_table(
            ["file_type", "path", "summary evidence", "reason"],
            _summary_only_rows(model),
            "暂无 summary-only 审查项。",
            "change-scroll",
        )
        + "<h3>Metadata-only Reviewed</h3>"
        + "<div class='quality-note'>已完成 metadata-only 审查；二进制/版图文件默认只使用 hash/size/path/count 证据。</div>"
        + catalog._scroll_table(
            ["file_type", "path", "metadata evidence", "reason"],
            _metadata_only_rows(model),
            "暂无 metadata-only 审查项。",
            "change-scroll",
        )
```

Keep the existing aggregate “变化文件” table for scan context. The three lane tables are the reviewer entry points.

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lib_guard/test/test_version_detail_report.py src/lib_guard/render/version_detail_report.py
git commit -m "feat: clarify version detail lane tables"
```

## Task 3: Tighten Expert `--force-large` Behavior

**Files:**
- Modify: `src/lib_guard/test/test_pairwise_policy.py`
- Modify: `src/lib_guard/test/test_scan_pipeline.py`
- Modify: `src/lib_guard/short_cli.py`
- Test: `src/lib_guard/test/test_pairwise_policy.py`, `src/lib_guard/test/test_scan_pipeline.py`

- [ ] **Step 1: Add spec-named rejection and opt-in tests**

In `src/lib_guard/test/test_pairwise_policy.py`, add these tests after the existing `test_fd_summary_only_without_force_large_fails_with_clear_message`:

```python
    def test_fd_summary_only_with_force_large_generates_command(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._fd_workspace(Path(td), "top.v")
            commands = build_cli_commands(
                ["fd", "ucie", "patch", "top.v", "--type", "verilog", "--force-large"],
                cwd=workspace,
            )

        self.assertEqual(commands[0][0], "file-diff")
        self.assertEqual(commands[0][1], "verilog")
        self.assertIn("--manual-large-file-opt-in", commands[0])

    def test_fd_binary_metadata_only_without_force_large_fails_with_clear_message(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._fd_workspace(Path(td), "top.db")
            with self.assertRaisesRegex(ValueError, "db is metadata-only; pass --force-large only for expert manual review\\."):
                build_cli_commands(["fd", "ucie", "patch", "top.db", "--type", "db"], cwd=workspace)

    def test_fd_binary_metadata_only_with_force_large_generates_command(self) -> None:
        from lib_guard.short_cli import build_cli_commands

        with tempfile.TemporaryDirectory() as td:
            workspace = self._fd_workspace(Path(td), "top.db")
            commands = build_cli_commands(
                ["fd", "ucie", "patch", "top.db", "--type", "db", "--force-large"],
                cwd=workspace,
            )

        self.assertEqual(commands[0][0], "file-diff")
        self.assertEqual(commands[0][1], "db")
        self.assertIn("--manual-large-file-opt-in", commands[0])
```

Update `test_fd_summary_only_without_force_large_fails_with_clear_message` to assert the exact message:

```python
            with self.assertRaisesRegex(ValueError, "verilog is summary-only; pass --force-large only for expert manual review\\."):
                build_cli_commands(["fd", "ucie", "patch", "top.v", "--type", "verilog"], cwd=workspace)
```

- [ ] **Step 2: Add the automatic-task non-inheritance test**

In `src/lib_guard/test/test_pairwise_policy.py`, add:

```python
    def test_pairwise_still_never_generates_force_large_tasks(self) -> None:
        from lib_guard.diff.pairwise import recommend_pairwise_file_diffs

        diff = {
            "changed": [
                {"path": "rtl/top.v", "file_type": "verilog"},
                {"path": "timing/top.lib", "file_type": "liberty"},
                {"path": "db/top.db", "file_type": "db"},
                {"path": "layout/top.gds", "file_type": "gds"},
                {"path": "lef/top.lef", "file_type": "lef"},
            ],
            "added": [],
            "removed": [],
        }
        tasks = recommend_pairwise_file_diffs(diff, library="ucie", version="patch", base="base")

        self.assertEqual([task["file_type"] for task in tasks], ["lef"])
        for task in tasks:
            self.assertNotIn("--force-large", task.get("command", ""))
            self.assertNotIn("--manual-large-file-opt-in", task.get("command", ""))
```

- [ ] **Step 3: Run the failing tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_pairwise_policy.PairwisePolicyTest.test_fd_summary_only_without_force_large_fails_with_clear_message \
  src.lib_guard.test.test_pairwise_policy.PairwisePolicyTest.test_fd_summary_only_with_force_large_generates_command \
  src.lib_guard.test.test_pairwise_policy.PairwisePolicyTest.test_fd_binary_metadata_only_without_force_large_fails_with_clear_message \
  src.lib_guard.test.test_pairwise_policy.PairwisePolicyTest.test_fd_binary_metadata_only_with_force_large_generates_command \
  src.lib_guard.test.test_pairwise_policy.PairwisePolicyTest.test_pairwise_still_never_generates_force_large_tasks \
  -q
```

Expected: at least the exact-message tests FAIL because current copy includes `file type 'verilog' is ...`.

- [ ] **Step 4: Tighten the user-facing error message**

In `src/lib_guard/short_cli.py`, change `_validate_manual_file_diff_type()` from:

```python
        raise ValueError(
            f"file type {file_type!r} is {lane}; pass --force-large only for expert manual review."
        )
```

to:

```python
        raise ValueError(
            f"{file_type} is {lane}; pass --force-large only for expert manual review."
        )
```

Do not add `--force-large` to `cmp`, `refresh`, or pairwise task generation.

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_pairwise_policy -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lib_guard/test/test_pairwise_policy.py src/lib_guard/test/test_scan_pipeline.py src/lib_guard/short_cli.py
git commit -m "test: lock expert file diff opt in"
```

## Task 4: Update User-Facing Docs For Lane Policy

**Files:**
- Modify: `README.md`
- Modify: `docs/user_guide.md`
- Modify: `docs/data_contract.md`
- Test: `src/lib_guard/test/test_repository_cleanup.py`

- [ ] **Step 1: Add documentation guard test**

In `src/lib_guard/test/test_repository_cleanup.py`, add this test near the existing documentation cleanup tests:

```python
    def test_current_docs_explain_refresh_cmp_fd_lanes_and_force_large(self) -> None:
        docs = {
            "README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
            "docs/user_guide.md": (ROOT / "docs" / "user_guide.md").read_text(encoding="utf-8"),
            "docs/cli_reference.md": (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8"),
            "docs/data_contract.md": (ROOT / "docs" / "data_contract.md").read_text(encoding="utf-8"),
        }
        required = [
            "refresh",
            "current_effective",
            "cmp",
            "summary-only",
            "metadata-only",
            "--force-large",
            "Version Review",
        ]
        for name, text in docs.items():
            with self.subTest(doc=name):
                for token in required:
                    self.assertIn(token, text)
```

- [ ] **Step 2: Run the failing documentation guard**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_repository_cleanup.RepositoryCleanupTest.test_current_docs_explain_refresh_cmp_fd_lanes_and_force_large -q
```

Expected: FAIL because `README.md` and `docs/user_guide.md` do not yet include all lane-policy tokens.

- [ ] **Step 3: Update `README.md`**

In `README.md`, after the paragraph that starts with `` `refresh` 用于刷新 Version Review``, add:

```markdown

### Version Review 更新详情与 File Diff lane

`refresh` 是普通 reviewer 刷新 Version Review 更新详情的入口，默认使用
`current_effective`，没有当前有效库时使用 `previous_effective`。`cmp` 保留为手动
compare/debug；只有需要显式 base、adjacent 或 cumulative 对比时才使用。

Version Review 默认只对 `DEFAULT_FILE_DIFF_TYPES` 生成推荐 `fd` 命令。Verilog /
SystemVerilog、Liberty / Lib、SPEF 属于 summary-only；DB、GDS、OAS、Layout、
Milkyway、NDM 属于 metadata-only。summary-only / metadata-only 已经有摘要、
hash、size、path、count 等证据，不表示系统没有检查。

专家确实需要手动下钻大文件或二进制 metadata lane 时，使用显式 opt-in：

```csh
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> rtl/top.v --type verilog --force-large
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> db/top.db --type db --force-large
```

`--force-large` 只影响这一次手动 `fd`，不会被 `refresh`、`cmp` 或 pairwise 自动任务继承。
```

- [ ] **Step 4: Update `docs/user_guide.md`**

In `docs/user_guide.md`, after the File Diff command block, add:

```markdown

默认情况下，Version Review 只推荐适合人工阅读的 `DEFAULT_FILE_DIFF_TYPES`。
Verilog / SystemVerilog、Liberty / Lib、SPEF 是 summary-only；DB、GDS、OAS、
Layout、Milkyway、NDM 是 metadata-only。页面中的 Summary-only Reviewed 和
Metadata-only Reviewed 表示系统已经完成摘要级或 metadata 级审查，不是漏跑。

专家手动确认需要展开这些大文件或 metadata lane 时，可以显式 opt-in：

```csh
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> rtl/top.v --type verilog --force-large
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> db/top.db --type db --force-large
```

`--force-large` 只用于这一次手动 `fd`。日常 `refresh`、手动 `cmp`、pairwise 自动推荐
都不会继承这个选项。
```

- [ ] **Step 5: Update `docs/data_contract.md`**

In the `Version Update Detail Reviewer Fields` table, add these rows after `primary_next_action`:

```markdown
| `lane_counts` | Counts for `recommended_file_diff`, `summary_only`, `metadata_only`, and `blocking_issues` |
| `summary_only_changes` | Alias for summary-only reviewed rows; kept for spec vocabulary and downstream readers |
| `metadata_only_changes` | Alias for metadata-only reviewed rows; kept for spec vocabulary and downstream readers |
```

- [ ] **Step 6: Run docs tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_repository_cleanup -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/user_guide.md docs/data_contract.md src/lib_guard/test/test_repository_cleanup.py
git commit -m "docs: clarify version review lane policy"
```

## Task 5: Final Validation And PR Update

**Files:**
- No production file changes unless validation reveals a defect.
- Test: full test suite and current fixture smoke.

- [ ] **Step 1: Run compile and targeted tests**

Run:

```bash
cd /home/polaris/proj/mx/ai_lib/repo
PYTHONPATH=src python3 -m compileall -q src
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_version_detail_report -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_pairwise_policy -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_repository_cleanup -q
PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_scan_pipeline -q
```

Expected: all commands exit 0.

- [ ] **Step 2: Run full discovery**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p "test*.py" -q
```

Expected: all tests pass.

- [ ] **Step 3: Run help and whitespace checks**

Run:

```bash
PYTHONPATH=src python3 -m lib_guard.short_cli --help
git diff --check
```

Expected:

- Help includes `--force-large`.
- Help shows summary-only and metadata-only only under expert manual fd, not as default file-diff recommendations.
- `git diff --check` exits 0.

- [ ] **Step 4: Run local OpenROAD fixture smoke if config exists**

Run:

```bash
if [ -f /home/polaris/proj/mx/ai_lib/repo/lib_guard.yml ]; then
  cd /home/polaris/proj/mx/ai_lib/repo
  PYTHONPATH=src python3 -m lib_guard.short_cli --dry-run refresh vendor_A.openroad_platform.openroad_asap7
  PYTHONPATH=src python3 -m lib_guard.short_cli --dry-run fd vendor_A.openroad_platform.openroad_asap7 20260627_asap7 yoSys/cells_adders_L.v --type verilog --force-large
else
  echo "config absent"
fi
```

Expected:

- `refresh --dry-run` prints a lower-level `python -m lib_guard.cli compare ...` command.
- `fd --force-large --dry-run` prints a lower-level `python -m lib_guard.cli file-diff ...` command.
- Neither command executes scan/diff work.

- [ ] **Step 5: Inspect Version Detail output manually if work HTML exists**

Open this local file if it exists:

```text
/home/polaris/proj/mx/ai_lib/repo/work/openroad_manual_review/catalog/html/libraries/ip_vendor_A.openroad_platform.openroad_asap7/versions/20260627_asap7/index.html
```

Expected first-screen checks:

- Headline visible.
- Base source/version/target/comparison/delete semantics visible.
- Summary-only Reviewed and Metadata-only Reviewed are separate sections.
- Diff Issues appears before recommended actions.
- Markdown export link is described as explicit export evidence, not an HTML input.

- [ ] **Step 6: Commit final validation note only if needed**

If validation required test/doc tweaks, commit them:

```bash
git add <changed-files>
git commit -m "test: add version review experience guardrails"
```

If no files changed, do not create an empty commit.

- [ ] **Step 7: Push and update PR**

Run:

```bash
git push
gh api -X PATCH repos/Godshaohao/ai_lib/issues/2 -f body=$'## Summary\n- Added Version Detail lane counts and spec vocabulary fields for summary-only / metadata-only evidence.\n- Clarified Version Detail lane tables so recommended File Diff, Summary-only Reviewed, and Metadata-only Reviewed show reviewer-specific columns.\n- Tightened expert `fd --force-large` behavior and tests while keeping automatic pairwise defaults safe.\n- Updated README, user guide, CLI reference, and data contract wording around refresh/cmp/fd lanes.\n\n## Validation\n- PYTHONPATH=src python3 -m compileall -q src\n- PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p \"test*.py\" -q\n- PYTHONPATH=src python3 -m lib_guard.short_cli --help\n- PYTHONPATH=src python3 -m lib_guard.short_cli --dry-run refresh vendor_A.openroad_platform.openroad_asap7\n- PYTHONPATH=src python3 -m lib_guard.short_cli --dry-run fd vendor_A.openroad_platform.openroad_asap7 20260627_asap7 yoSys/cells_adders_L.v --type verilog --force-large\n- git diff --check\n\n## Notes\n- Main flow remains Catalog -> Version Review -> Release.\n- `--force-large` is still an explicit manual fd opt-in only.\n- Generated work HTML and large raw fixtures were not pushed.'
```

Expected: branch pushes and PR #2 body updates.

## Self-Review

**Spec coverage:**

- Task 1 covers `headline`, `lane_counts`, `summary_only_changes`, and `metadata_only_changes`.
- Task 2 covers the requested Recommended File Diff, Summary-only Reviewed, and Metadata-only Reviewed UI columns and wording.
- Task 3 covers default rejection, expert opt-in, metadata-only opt-in, and pairwise non-inheritance for `--force-large`.
- Task 4 covers README, CLI reference parity through existing docs, data contract fields, and user guide wording for `refresh`, `cmp`, `fd`, summary-only, metadata-only, and `--force-large`.
- Task 5 covers compile, unit tests, help, whitespace, local fixture smoke, and PR update.
- Existing branch tests already cover base trust warning/blocking, diff issues visibility before recommended actions, release readiness evidence visibility, HTML not reading Markdown, and render helper boundary guards.

**Placeholder scan:**

- No placeholder markers or vague “add tests later” instructions remain.
- Every code-changing step includes concrete snippets and exact commands.

**Type consistency:**

- `lane_counts`, `summary_only_changes`, `metadata_only_changes`, `summary_only_reviewed`, `metadata_only_reviewed`, `recommended_file_diff`, and `file_diff_recommendations` are used consistently across tests, model, docs, and renderer snippets.
- `--force-large` remains a short CLI option; `--manual-large-file-opt-in` remains an internal lower CLI marker stripped from dry-run output.
