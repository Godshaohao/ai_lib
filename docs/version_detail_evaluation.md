Status: current

# Version Detail 真实数据验收记录

评估日期：2026-08-07

结论：**本轮复核 P0、P1、P2 全部通过，真实数据渲染、浏览器截图和交互验收均已完成。**

本轮修复并用真实 OpenROAD 数据复核了三类问题：首版本自引用 Base、必需 View 未进入 IP 接入判断、扫描证据聚合字段为空。另补齐了一个真实组合：`FULL_PACKAGE + update_scope` 必须仍按完整包处理，不能被误判为增量包。

## 评估对象

真实工作区：`work/library_registry_smoke`

事实源 catalog：`work/library_registry_smoke/catalog/catalog.json`

数据规模：9 个库、18 个版本、18 个实际扫描目录、9 个增量版本有实际 diff 目录。

正式渲染结果：

- 输出：`work/real_data_grill_20260807/rerun_render/index.html`
- render_status：`PASS`
- 9 个库、18 个版本详情页全部生成
- 本轮复核渲染耗时：4.679 秒
- 页面合计约 2.28 MB；最大单页 380,553 bytes

## P0 结果

| 编号 | 结果 | 真实证据 | 判断 |
| --- | --- | --- | --- |
| VD-P0-01 主判断唯一 | PASS | 18 个页面均有 IP 接入主状态；正式放行仍与 IP 接入判断分开 | 满足要求 |
| VD-P0-02 基准可信 | PASS | 9/9 首版本均进入 `first_version`；没有页面把自身版本作为 Base | 自引用 Base 不再产生比较结论 |
| VD-P0-03 数量自洽 | PASS | 18 个版本 `scan_evidence.file_total` 均非零；真实统计与 inventory/summary 一致 | 模型和页面不再依赖偶然 fallback |
| VD-P0-04 单版本可读 | PASS | 9 个首版本显示“首版交付”、自身文件总量和视图覆盖，不再显示自身基线 | 首版没有虚构空对比 |
| VD-P0-05 页面入口唯一 | PASS | 18 个详情页均为 `index.html`；没有重新生成独立 `file-evidence.html` | 文件结构留在详情页 |
| VD-P0-06 事实源边界 | PASS | 页面由 catalog/scan/diff evidence 渲染；未把 HTML 作为输入事实源 | 投影边界保持清晰 |
| VD-P0-07 必需 View 联动 | PASS | sky130ram 更新版缺少 RTL 模型时，主判断为“不可接入”，并显示缺失原因 | 必需 View 缺失进入 IP 使用决策 |

## P0 根因与修复

### 首版本 Base

真实目录中首版本仍保留 `base_version=<自身版本>`、`base_full_version=<自身版本>`、`compare_default=none`。`resolve_review_base()` 现在把这种无真实 diff 基准的自引用解析为 `NEEDS_BASE_CONFIRM`。同时，明确的 `FULL_PACKAGE/FULL` 优先于 `update_scope`，因此完整包不会因为携带视图范围元数据而被当成增量包。

### 必需 View

`build_ip_user_view_model()` 现在先计算交付完整度，再生成 IP 接入判断。`delivery_completeness.status == MISSING` 时主状态为“不可接入”，待确认事实中列出缺失 View。真实 sky130ram 更新版结果为：缺失 `RTL 模型`，主状态“不可接入”。

### 扫描证据统计

扫描统计读取顺序固定为：`file_inventory.file_type_counts`、`scan_summary.json`、`manifest.json`，最后才从 `file_inventory.files` 派生。18 个真实版本的 `file_total` 均非零，最大版本 605 个文件，Unknown 数量也进入模型。

## P1 结果

| 编号 | 结果 | 真实证据 | 判断 |
| --- | --- | --- | --- |
| VD-P1-01 影响范围 | PASS | 9 个首版本展示自身视图覆盖，9 个增量版本展示视图变化矩阵 | 首版和增量语义分开 |
| VD-P1-02 重点变化文件 | PASS | 重点文件表保留变化、类型、路径、审查级别和匹配证据，并限制行数 | 可定位下钻对象 |
| VD-P1-03 文件结构可核对 | PASS | 真实 inventory 文件进入详情页文件树，状态和滚动边界保留 | 文件可追溯 |
| VD-P1-04 版本关系和交付完整度 | PASS | 首版显示首版交付；增量显示 Base；缺 View 与主判断一致 | 证据与结论一致 |
| VD-P1-05 证据分层 | PASS | Parser、raw JSON、release gate 和调试证据不进入首屏；轻量证据不自动 blocker | 信息密度可控 |
| VD-P1-06 Unknown 可追溯 | PASS | 18 个版本 Unknown 计数由真实扫描事实提供，并可回到文件结构/证据入口 | 数量不再只停留在摘要 |
| VD-P1-07 扫描聚合来源 | PASS | 18 个 `scan_evidence.file_total` 均非零，统计来源与真实产物结构兼容 | 模型事实完整 |

## P2 结果

| 编号 | 结果 | 真实证据 |
| --- | --- | --- |
| VD-P2-01 信息顺序 | PASS | 判断摘要、影响范围、视图变化矩阵、文件结构和折叠证据均可生成 |
| VD-P2-02 中文和专业词 | PASS | 中文为主，保留 LEF、Liberty、SPEF、GDS、RTL 等必要术语 |
| VD-P2-03 长列表 | PASS（静态） | 最大页面 380,553 bytes；重点表和文件树有固定高度滚动 |
| VD-P2-04 静态页面 | PASS | 18 页生成成功，未发现自引用 Base 页面或空扫描统计 |
| VD-P2-05 浏览器检查 | PASS | 18 个真实 Version Detail 页面完成截图和交互验收；脚本结果为 243/243 PASS |

## 浏览器验证

浏览器问题根因不是 Version Detail 页面：沙箱内直接启动 Chrome 会被 Crashpad 的
`setsockopt: Operation not permitted` 拦截，Firefox Snap 也无法创建受限的 XDG 运行目录。
本轮使用 `/opt/google/chrome/chrome`，临时 `HOME`/`XDG_RUNTIME_DIR`，以及仓库脚本
`scripts/validate_version_detail_browser.cjs` 完成宿主环境验收。脚本先展开重点变化面板，
再操作表格搜索，不把默认折叠误判成不可交互。

输出目录：`work/real_data_grill_20260807/browser_validation/all_18/`

- 首版截图：[ip_vendor_A.openroad_platform.openroad_asap7__20260624_asap7.png](../work/real_data_grill_20260807/browser_validation/all_18/ip_vendor_A.openroad_platform.openroad_asap7__20260624_asap7.png)
- 增量版截图：[ip_vendor_A.openroad_platform.openroad_asap7__20260627_asap7.png](../work/real_data_grill_20260807/browser_validation/all_18/ip_vendor_A.openroad_platform.openroad_asap7__20260627_asap7.png)
- 全量机器结果：[browser_validation.json](../work/real_data_grill_20260807/browser_validation/all_18/browser_validation.json)

实际交互结果：18 个页面、`243/243 PASS`。每个页面均验证：页面标题和首屏判断摘要、View
Matrix、文件树、状态过滤、文件名搜索、全部展开/收起、重点变化表检索、侧栏折叠以及
视图变化矩阵支持横向滚动。

## 自动化验证

```text
定向回归：3/3 PASS
全量测试：463/463 PASS
compileall：PASS
真实 render：9 libraries / 18 versions / 18 detail pages / 4.679 s
浏览器验收：18 pages / 243 assertions PASS
```

静态页面复核：18/18 页面包含 `判断摘要`、`文件结构` 和视图变化矩阵；18/18 页面不包含
绝对开发机路径、独立 `file-evidence.html`、旧“文件证据清单”或 `scan_empty`。

全量测试输出中的 `--mode candidate` 是既有负向 argparse 测试，最终测试状态为 `OK`，不是本轮回归失败。

## 严格评分

评分按 P0 7 项、P1 7 项、P2 5 项，共 19 项。

- P0：7.0 / 7
- P1：7.0 / 7
- P2：5.0 / 5
- 总计：19 / 19 = 10.0 / 10

工程结论：**P0/P1/P2 全部达到本轮验收标准。** 浏览器脚本解决了临时 HOME、XDG
运行目录和受限沙箱下的启动问题；页面截图与交互结果均已留存，后续可直接复用同一命令。

## 剩余风险

1. 现有真实数据中仍有 Unknown 文件；系统已正确呈现数量和路径，但文件分类本身仍需业务规则或人工确认。
2. 详情页最大约 380 KB，当前静态渲染和本轮桌面浏览器验收可接受；大量更大库仍需在目标内网环境做一次浏览器性能验证。
