# 运行产物与报告检查清单

Status: current

状态：本轮已落地，作为 `scan / cmp / rel` 的验收清单。

## 1. 输出边界

| 类别 | 目录/文件 | 人工含义 |
| --- | --- | --- |
| 原始输入 | `raw/` | 库交付原件，不由渲染命令修改 |
| 人工配置 | `config/` | 正式库、版本关系、策略和人工覆盖 |
| 资产快照 | `catalog/catalog.json` | 库和版本地图，不保存运行事实 |
| 运行指针 | `catalog/catalog_runtime.json` | 当前 scan、cmp、release 路径指针 |
| 扫描事实 | `work/scan_out/...` | inventory、parser、summary、日志 |
| 对比事实 | `work/diff/...` | Base 与 Target 的变化结果 |
| 文件级对比 | `work/file_diff/...` | 显式专家下钻结果，不是默认主流程 |
| 版本页面 | `catalog/html/` | 用户查看的唯一主审查投影 |
| 正式发布 | `release_area/` | 通过检查后生成的链接发布物 |

`catalog.json`、HTML 和各种索引是投影/导航，不得反向替代 scan、diff、effective 或
人工配置事实。

## 2. 单次运行必须留下的清单

每次 `scan`、`cmp`、`rel --check` 都必须在自己的事实目录留下：

```text
run_manifest.json
```

清单至少说明：

- 操作类型、状态、运行 ID；
- 库类型、库名、版本；
- 输入目录和 Catalog；
- Base 版本、Base 来源、Base scan 目录（对比时）；
- 事实文件位置；
- scan/diff/release 报告位置；
- Version Detail 页面位置；
- 阶段耗时和警告。

清单是导航，不是新事实源；生成清单不能删除或改写已有证据。

## 3. 默认路径契约

直接扫描和 Catalog 扫描使用同一默认路径：

```text
work/scan_out/<library_type>/<library_name>/<version>/runs/<mode>_<scan_id>/
```

对比事实默认位于：

```text
work/diff/<library_name>/<target_version>/<relation_or_base>/
```

当前仍兼容显式 `--out`。显式指定路径时，用户承担路径管理责任，但仍必须生成
`run_manifest.json`。

## 4. 操作验收

### 扫描

- [ ] `scan_meta.json` 存在且状态与命令返回一致。
- [ ] `file_inventory.json` 存在。
- [ ] `parser_manifest.json` 或明确记录无解析任务。
- [ ] `logs/scan_progress_latest.json` 能说明最终阶段。
- [ ] `run_manifest.json` 指向上述事实文件。
- [ ] 如果生成 HTML，清单中存在 `scan_html`。
- [ ] 扫描失败时命令返回失败，并能从 `scan_error` 或 `scan_meta.json` 定位原因。

### 对比

- [ ] Target 和 Base 都有明确的 scan 目录。
- [ ] 清单记录真实 Base，而不是只记录 compare 模式名称。
- [ ] 清单记录 `base_source`，例如 `explicit`、`current_effective` 或 `previous_effective`。
- [ ] `diff_summary.json`、`view_diff.json`、`type_diff.json` 等实际对比事实文件与对比 HTML
      位于同一个对比事实目录或由清单明确指向；不假定不存在的 `diff.json`。
- [ ] 版本详情页能从清单追溯到 Target scan、Base scan 和 diff 事实。
- [ ] 缺少 scan evidence 时不能伪装成“无变化”。

### 发布检查

- [ ] `release_check.json` 和 `release_result.json` 位于扫描结果的 `release/` 目录。
- [ ] 清单区分“发布检查结果”和 `release_area/` 正式发布物。
- [ ] release 检查不修改 scan/diff 原始事实。
- [ ] force/overwrite 仍需要现有的显式原因和审计记录。

### 页面刷新

- [ ] scan/cmp 后只刷新受影响的 Version Detail，不触发无关库的全量页面重建。
- [ ] `cat` 只刷新投影，不删除 scan、diff、release 事实。
- [ ] 页面中的路径来自运行结果/清单，不通过 renderer 重新猜测。
- [ ] Catalog 首页、库页和版本详情页的角色不混淆。

## 5. 反防御性设计检查

以下内容本轮明确不做：

- [ ] 不引入数据库、服务端、后台调度器或新状态机。
- [ ] 不新增 parallel 的主审查页面。
- [ ] 不自动为所有文件生成 file diff。
- [ ] 不把 `run_manifest.json` 变成第二套业务事实。
- [ ] 不用宽泛 `try/except` 把产物写入失败伪装成成功。
- [ ] 不因为“未来可能需要”增加配置、插件或命令。
- [ ] 不一次性迁移历史目录；先证明清单和兼容路径可靠。

## 6. 评分标准（10 分）

| 维度 | 分值 | 通过标准 |
| --- | ---: | --- |
| 输入/事实/投影边界 | 2 | 能明确回答文件属于输入、事实还是页面 |
| 路径一致性 | 2 | direct scan 与 catalog scan 默认路径一致 |
| 产物可追溯 | 2 | 每次运行有 manifest，能串起输入、Base、事实和页面 |
| 不覆盖旧事实 | 2 | 重跑生成新 run，旧 scan/diff/release 仍可读取 |
| 对比可信度 | 1 | Base、来源、两侧 scan 路径明确 |
| 命令可操作性 | 1 | 命令返回直接给出 manifest 和下一页面 |

低于 9 分不得宣称“输出管理已完成”；低于 8 分应停止继续增加 UI 或命令，先修正
事实链和路径契约。

## 7. 建议验证命令

```bash
PYTHONPATH=src python3 -m compileall -q src
PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q
git diff --check
```

模拟流程至少覆盖：

```text
scan v1
scan v2
cmp v2 --base v1
rel v2 --check-first
重跑 scan/cmp，确认旧事实仍在
删除 HTML 投影后重新 render，确认事实仍可恢复页面
```
