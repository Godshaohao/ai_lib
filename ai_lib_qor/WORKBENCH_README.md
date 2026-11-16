# ai_lib_qor 本地检查工作台

当前工作台迁移的是「选择已有检查计划 → 检查 → 生成报告 → 下载产物」这一条链路，并非旧工作台的全部功能。每次运行独立保存，不执行采纳和版本修改。

## 安装与启动

在项目根目录执行：

```bash
python3 -m pip install -r requirements-pipeline.txt
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p workbench_runs
python3 -m ai_lib_qor.workbench --plans examples/pipeline --work examples/work --runs workbench_runs --port 5050
```

打开 `http://127.0.0.1:5050`。左侧是 v3 已登记的 IP；点击“检查与报告”，选择 `check_effective.example.json`，点击运行。该示例和计划中的相对路径按**项目根目录**解析，因此必须从项目根目录启动。示例使用合成数据。

`--plans` 应指向可信计划目录。计划中的路径由现有检查服务读取，可以指向计划目录以外的文件；不要运行不可信计划。`--runs` 指向独立的工作目录，不应放入 RAW、Formal NL、计划目录或项目示例目录。工作台只监听本机，不提供多用户登录或远程访问能力。

## 输入、输出与状态

- 输入：现有检查计划 JSON。计划的 `target_revision` / `baseline_revision` 或 `target_delivery` / `baseline_delivery`、事实文件及可选正式快照需事先准备；格式见 `examples/pipeline/` 和 `PIPELINE_README.md`。
- 输出：`<runs>/run_<uuid>/status.json`、`check.json`、`report.html`、`report.xlsx`。报告只包含计划中提供的上下文；不会自动查找未列出的交付、采纳版本或事实。
- 状态：`RUNNING`、`SUCCEEDED`、`FAILED`。失败信息保存在 `status.json`；已有部分产物会显示供排查，不代表成功。当前请求同步执行，浏览器需等待；服务中断可能留下 `RUNNING`，需要人工核查，系统不会自动重试。
- 证据边界：现有检查是对指定事实及其引用的判断，不能证明事实文件未遭修改或 RAW 当前字节未变化；报告不是版本采纳证明。

## 迁移状态

| 旧版能力 | 新版状态 |
|---|---|
| 运行指定检查、查看记录、下载 JSON/HTML/Excel | 已接入已有 v3 检查及报告服务；按计划中列出的范围执行 |
| 原始库发现与登记、配置 IP | 未迁移；暂由 CLI 和人工准备交付记录 |
| 最新/次新文件矩阵、版本选择 | 未迁移；不能通过工作台自动推断或组装计划 |
| Formal NL 浏览和快照管理 | 未迁移；检查计划可显式引用已有快照 |
| 可配置检查项目和自动事实提取 | 未迁移；计划需提供事实与配对 |
| 后台任务队列、进度与中断恢复 | 未迁移；当前为同步请求和持久状态 |
| 单 IP 全版本汇总和每版本报告 | 已支持每版存在唯一匹配计划时依次执行并生成汇总；覆盖范围由各计划决定，真实 RAW 与旧版 Excel 等价尚未验收 |
| 采纳、回滚、权限管理 | 未迁移到 UI；现有版本 CLI 独立使用 |

详细接口与模块职责见 [工作台架构设计](design/blackbox_v3_1/workbench.md)。

## 工作台浏览

`--work` 指向已存在的 v3 work 目录；不提供则无 IP 清单。左侧按有效集索引列出 IP；文件定位展示所选源库的交付记录，尚不按 IP 文件归属过滤；交付对比与正式快照需手动选择。所有这些视图只读取记录，不扫描 RAW 或正式目录。计划和运行记录目前也没有与所选 IP 自动绑定。

在“检查与报告”中可对单个有效版本运行匹配计划；每个版本各有唯一匹配计划时可运行整体 IP 检查。运行详情展示输出目录、打开文件夹和下载链接；整体报告分别提供每版 Excel 与汇总 Excel。详见 [版本和报告说明](docs/library_versions_and_reports.md)。
