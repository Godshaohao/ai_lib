Status: current

# 测试计划

## 文档契约

| 项 | 说明 |
| --- | --- |
| 目标读者 | 开发者、维护者、提交前自测人员 |
| 最小目标 | 证明代码可 import、单元测试通过、短命令 help 可用、关键 HTML 投影不 stale |
| 禁止做法 | 只看静态 diff 就声称完成；只测 UI 不测数据模型；只测单命令不测 scan/cmp/render 联动 |

## 基础回归

每轮代码或文档整理后至少跑：

```bash
PYTHONPATH=src python3 -m compileall -q src
PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p "test*.py" -q
PYTHONPATH=src python3 -m lib_guard.cli --help
PYTHONPATH=src python3 -m lib_guard.short_cli --help
scripts/lg.csh --help
```

## 按变更类型加测

| 修改范围 | 额外检查 |
| --- | --- |
| Renderer / HTML | 在 `work/` 下重新生成 catalog，手动检查 HTML；确认 HTML 不内嵌 raw 绝对路径和完整 JSON |
| Review Gate | 跑 `src.lib_guard.test.test_review_gate` |
| Release Gate / symlink release | 做一次 `rel --explain` 和 dry-run/preview |
| Scan/parser | 跑 scan pipeline 相关测试，并用小 fixture 重扫 |
| Diff/lane | 跑 scan diff、pairwise 和 Version Detail 相关测试 |
| 文档整理 | 跑 repository cleanup 测试，确认没有旧流程入口 |
| 命令编排 | 跑 short CLI command surface、window intake 和 render impact 测试 |

## 事实源回归

涉及 catalog、scan、diff、effective/window 或 render 的修改，必须确认单向数据流没有被破坏：

```bash
PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_catalog_timeline \
  src.lib_guard.test.test_scan_pipeline \
  src.lib_guard.test.test_window_intake \
  src.lib_guard.test.test_render_impact \
  src.lib_guard.test.test_version_detail_report -q
```

必须覆盖：

- `catalog.json` 仍是库和版本资产地图。
- scan 后生成 `review/*.tsv` 人工证据。
- cmp 后 target Version Detail 刷新。
- effective/window 不替代 scan/diff 事实。
- HTML 不作为事实源，不被 scan/diff/release 读取。
- Version Detail 不展示 raw 绝对路径、`scan_html`、`diff_html`、`file_diff.json` 等调试路径。

## Version Detail 投影回归

Version Detail 是唯一审查投影。涉及 scan、compare、intake、accept-window、
mark 或 update-detail 的修改，必须额外跑：

```bash
PYTHONPATH=src python3 -m unittest \
  src.lib_guard.test.test_version_detail_review_context \
  src.lib_guard.test.test_render_impact \
  src.lib_guard.test.test_window_intake \
  src.lib_guard.test.test_version_detail_report -q
```

这组测试锁定：

- `VersionDetailReviewContext` 是否正确识别 pending window、candidate effective、
  compare manifest 和 freshness。
- scan、batch scan、compare、batch compare、intake、accept-window、mark 是否通过
  Render Impact 刷新受影响的 Version Detail，而不是全量或裸刷新。
- Version Detail 第一屏是否仍按“接入判断、审查对象、对比上下文、View 变化、证据状态”
  五组信息展示。

复杂度边界：

- 单版本 scan / compare 只刷新当前库当前版本投影。
- batch scan / compare 按成功版本集合刷新，复杂度为 O(K)。
- intake / accept-window 按 review window 内版本集合刷新，复杂度为 O(W)。
- 全 catalog render 只作为显式 catalog 页面刷新或低频重建动作。

## 手工 Smoke 流程

在内网真实库上每轮发布前至少选一个小库和一个复杂库执行：

```csh
lg library list --plain
lg library list <LIBRARY> --versions --plain
lg next <LIBRARY>
lg scan <LIBRARY> <VERSION>
lg cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --scan-if-missing
lg cat <LIBRARY> <VERSION>
```

验收点：

| 页面/输出 | 必看项 |
| --- | --- |
| `scan` 输出 | `phase_timings`、`scan_error`、`render_summary` |
| Scan HTML | View 覆盖、文件证据表、unknown、大文件证据等级 |
| Version Detail | 接入判断、审查对象、对比上下文、View 变化、证据状态 |
| `render_summary` | `open_first` 是否指向刚刷新详情页 |

遇到慢 scan 时先跑：

```csh
lg --dry-run scan <LIBRARY> <VERSION>
lg scan <LIBRARY> <VERSION> --no-render
python3 -m json.tool <SCAN_DIR>/logs/scan_progress_latest.json
```

只有确认慢点在内容 hash 或 parser 后，才调整 scan 策略；不要把慢渲染和慢扫描混在一起。

## 文档守卫

`src/lib_guard/test/test_repository_cleanup.py` 会检查：

- 当前文档都有 `Status: current`。
- README 不再膨胀成完整教程。
- 当前文档索引只指向保留文档。
- 旧 workflow、旧命令入口、旧迁移说明不会重新出现在用户主路径。

这组测试是文档清理的防回潮护栏。

文档提交前额外检查：

```bash
python3 - <<'PY'
from pathlib import Path
bad_words = ["TB" + "D", "TO" + "DO"]
for p in sorted(Path("docs").glob("*.md")):
    text = p.read_text(encoding="utf-8")
    assert text.startswith("Status: current"), p
    assert not any(word in text for word in bad_words), p
print("docs ok")
PY
```
