Status: current

# 架构说明

`lib_guard` 围绕审查证据组织，而不是围绕页面或命令组织。所有模块必须遵守单向数据流：

```text
配置/人工确认 -> 事实采集 -> 派生审查模型 -> HTML/TSV/JSON 投影
```

HTML、`catalog_state.json`、`manager_tasks.json` 和 `report_index.json` 是投影或索引，
不能反向驱动 scan、diff、release 或有效版判断。

命令行查询当前有效版时，优先读取 `current_effective.json` 和对应
`effective_manifest.json`。`report_index.json` 只能作为报告导航索引和兼容回退，不能作为
有效版事实来源。

![Lib Guard 架构与主流程](lib_guard_architecture_flow.svg)

```text
raw delivery
  -> catalog
  -> scan
  -> parser results
  -> summary/readiness
  -> diff
  -> review gate / owner override
  -> manifest-driven symlink release
```

## 源码边界

| 责任 | 路径 |
| --- | --- |
| Catalog 状态和库清单 | `src/lib_guard/catalog/` |
| Scan inventory 和 parser | `src/lib_guard/scan/` |
| Summary/readiness 构建 | `src/lib_guard/summary/` |
| 结构化对比 | `src/lib_guard/diff/` |
| Package/effective 组合 | `src/lib_guard/package/`, `src/lib_guard/effective/` |
| Release evidence 和 link/verify | `src/lib_guard/release/` |
| Review Gate 聚合 | `src/lib_guard/review/` |
| HTML 渲染 | `src/lib_guard/render/` |
| CLI 入口 | `src/lib_guard/cli.py`, `src/lib_guard/short_cli.py`, `src/lib_guard/cli_commands/` |

## 事实源边界

系统当前有五类关键事实或投影。它们必须按下面的职责使用：

| 层级 | Artifact | 职责 | 允许写入者 | 允许读取者 | 禁止事项 |
| --- | --- | --- | --- | --- | --- |
| 人工确认 | `config/library_registry.tsv`, `config/library_catalog.yml`, overrides | 正式库根、人工确认关系、包类型/Base 修正 | `library add/accept/apply/override`, `mark` | catalog、short CLI、intake | 不允许 scan/render 自动覆盖人工确认 |
| 资产地图 | `catalog/catalog.json` | 库、版本、raw path 和合并后的运行时指针 | catalog refresh、scan/cmp 状态更新 | list、scan、cmp、render、intake | 不手改 scan/diff/release 字段 |
| 单版本事实 | `scan_out/**` | 文件清单、parser 任务、scan review TSV、release readiness | scan pipeline | diff、Version Detail、release check | 不把 raw JSON 直接作为人工主页面 |
| 变化事实 | `diff/**`, `file_diff/**` | 相对可信 base 的 view/file/release 差异 | compare、fd | Version Detail、Comparison Review | 缺 diff 不能显示成“无变化” |
| 有效版/窗口 | `catalog/html/libraries/**/effective`, `window`, `current_effective.json` | 候选组合、当前 effective 指针、接入窗口 | intake、accept-window、effective rollback | Version Detail、library workspace、release | 不替代 scan/diff 事实 |
| 用户投影 | HTML、`catalog_state.json`、`manager_tasks.json`、`report_index.json` | 浏览和导航、聚合状态、证据入口 | renderer | 浏览器、人工审查 | 不作为上游事实源；不决定 current effective |

`version_evidence_state` 只是 Version Detail 的事实源索引。它解释页面当前引用了哪些输入，
但不创建新的事实，也不写回 catalog runtime state。

## Render 边界

| 页面 / 边界 | Owner |
| --- | --- |
| Catalog 渲染编排 | `src/lib_guard/render/catalog_report.py::render_catalog_html` |
| Catalog Browser / Library Workspace | `src/lib_guard/render/catalog_workspace_report.py` |
| Version Detail / update detail model | `src/lib_guard/render/version_detail_report.py` |
| Version Detail 审查上下文 | `src/lib_guard/render/version_detail_context.py` |
| 局部渲染影响模型 | `src/lib_guard/render/impact.py` |
| 共享视觉组件 | `src/lib_guard/render/product_theme.py` |

`catalog_report.py` 是 catalog render facade 和 state/task adapter，不应继续吸收
Version Detail、manual compare 或 release 逻辑。

Version Detail 是唯一审查投影。`window`、`effective`、`compare` 只是它的证据来源
和上下文，不应新增平行主审查页面。页面第一屏只回答：

- IP 使用判断。
- 当前审查对象。
- 对比上下文。
- View 变化。
- 证据 freshness。

Version Detail 使用 `version_evidence_state` 解释五类输入的边界：

- Catalog：库和版本资产地图。
- Scan：单版本目录事实。
- Diff/Compare：相对基准的变化事实。
- Effective/Window：当前有效版和接入窗口。
- HTML Render：用户看到的投影，不是事实源。

`RenderImpact` 只负责避免投影 stale。scan、batch scan、compare、batch compare、
intake、accept-window、mark 会声明受影响的库/版本，再由 finalizer 局部刷新对应
Version Detail、库工作台和目录索引。它不负责重新发现库，也不改变 scan、diff、
release 的业务规则。

复杂度约束：

| 操作 | 刷新范围 | 复杂度目标 |
| --- | --- | --- |
| 单版本 scan/cmp | 当前版本详情页 | O(1) |
| batch scan/cmp | 成功版本集合 | O(K) |
| intake/accept-window | 当前 review window 内版本集合 | O(W) |
| cat --refresh-catalog | 显式 catalog 重建 | O(库数 + 版本数)，低频 |

任何日常命令如果为了刷新一个版本而全量重建所有库页面，都应视为架构回归。

## 生成物边界

`work/` 下的 HTML 和 JSON 是审查产物，可以从源码、RAW、策略和 evidence 重新生成。
它们不是 source of truth。

Catalog HTML 会写出：

- `catalog_state.json`
- `manager_tasks.json`
- `report_index.json`

版本级 `review_gate` 会嵌入 `catalog_state.json`，也可以写到：

```text
review/<library>/<version>/review_gate.json
```

## 阻塞口径

File Diff 推荐默认只是 attention item，不等同 blocker。

常见 blocker 来源是：

- metadata-only 二进制变化需要 owner 决策。
- catalog 信任问题。
- release fatal issue。
- review gate 中未 accept/waive 的真实 blocking item。

页面和 release 逻辑不能把“算法匹配推断”直接当成事实结论；路径迁移、matched/moved
一类信息必须保留 match reason 和 confidence。

## 工程修改规则

| 修改目标 | 应改位置 | 不应改位置 |
| --- | --- | --- |
| 文件识别/扫描速度 | `scan/`, `view_types.py`, `project_config.py` | HTML renderer |
| View Delta / IP 使用判断 | review model、`version_detail_report.py` model builder | scan parser |
| 页面布局和中文文案 | `render/` | scan/diff/release 规则 |
| Base/effective/window 关系 | `effective/`, `window_intake`, review context | HTML 字符串拼接 |
| release link/verify | `release/` | catalog renderer |
| 短命令展开 | `short_cli.py`, `cli_commands/` | 底层数据模型 |

每次修改必须同时回答：

1. 修改的是事实采集、派生模型，还是投影？
2. 是否引入了新的事实源？如果是，为什么不能复用已有 artifact？
3. 是否会让单版本热路径退化成全量 catalog render？
4. 是否有测试覆盖 stale render、错误 base、缺 scan/diff、unknown 文件和大文件 lane？
