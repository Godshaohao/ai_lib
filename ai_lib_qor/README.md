# ai_lib_qor · IP 库来源、有效版本、FileFacts 与 QoR 检查系统

面向多供应商（Vendor）与来源库（Source Library）的可信数据链工具：以**路径式三层架构**管理 RAW 交付、Formal NL 快照、Effective 有效版本、FileIndex 统一索引、内容寻址 FileFacts 共享池与可插拔 QoR 检查，CLI、Web 工作台、只读 JSON API 与 Excel 报告共享同一持久化数据与查询语义。

---

## 目录结构

```text
ai_lib_qor/
  AGENTS.md               # 项目工程约束与状态分离红线
  README.md               # 本说明
  setup.csh               # 安装依赖、初始化工作目录、启动 Web、运行 CLI
  docs/                   # 活跃架构文档与 ADR（核心基线：docs/architecture-steward.md）
  schemas/                # JSON Schema 契约定义
  src/ai_lib_qor/         # 源码包（CLI、三层刷新、Parser/Check 插件、Web 工作台）
  tests/                  # 活跃路径式主线自动化测试（13 文件，无需外部依赖）
  tools/                  # 活跃压测工具（tools/benchmark_scale.py）
  examples/               # 开源 PDK 样本（SkyWater130/GF180/Nangate45/ASAP7）与配置样例
  work/                   # 本地验收工作目录（只读查看或按需操作）
  archive/                # 历史旧代测试、旧脚本、早期设计草稿与历史输出归档
```

---

## 核心三层数据链

```text
L1 来源层（只读扫描外部目录）
  RAW 总目录  ──> delivery/delivery_*.json + raw_observations.tsv
  Formal NL   ──> formal/formal_*.json + formal_observations.tsv（无变化去重）
       │
       ▼
L2 有效版本层（计算版本与人工采纳指针严格分离）
  自动演进/预览发布 ──> effective/effective_<lib>_NNN.json + latest_effective.json
  显式人工采纳/回退 ──> log/acceptance_events.jsonl + accepted_effective.json
       │
       ▼
L3 统一索引与检查报告层（页面浏览仅只读消费，不触发扫描或重解析）
  file_index.json + .file_index_manifest.json（SHA-256 指纹未变跳过重建）
  facts/fact_ca_<VIEW>_<hash16>.json.gz（内容寻址 gzip 共享池，跨版本复用）
  log/check_rev_*_run_*.json（轻量指针检查结果）+ 按需懒生成缓存 .xlsx
```

---

## 快速开始

### 1. 在任意目录配置并启动工作台

需要 Linux、`csh` 和 Python 3.11 或更新版本。下面的源码目录和工作目录可以放在不同位置。

```csh
set QOR_ROOT = "/path/to/ai_lib_qor"
set QOR_WORK = "/path/to/site work"

python3 -m venv "$HOME/.venvs/ai-lib-qor"
setenv AI_LIB_QOR_PYTHON "$HOME/.venvs/ai-lib-qor/bin/python"
"$QOR_ROOT/setup.csh" install
"$QOR_ROOT/setup.csh" init --work "$QOR_WORK"
"$QOR_ROOT/setup.csh" web --work "$QOR_WORK"
```

新工作目录的配置写入 `$QOR_WORK/path_sources.json`，本机访问地址为 `http://127.0.0.1:5050`。启动前可在其中填入 RAW、Formal NL 和监听配置。来源使用绝对路径时，可以从任意目录启动或同步。

可以通过 `init --work "$QOR_WORK" --config "/path/to/site.json"` 从另一个位置导入配置。初始化会保留工作目录中的已有配置。选项及格式见 [来源配置样例](examples/path_sources.example.json)。环境已有依赖时，可直接使用该环境的 Python。离线安装可向 `install` 传入 `--no-index --find-links /path/to/wheels`。

启动命令在前台运行，通过 `Ctrl+C` 停止。服务监听使用工作目录中的 `workbench` 设置，也可通过 `web --host HOST --port PORT` 覆盖本次监听。

### 2. 运行主线测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
```

### 3. 常用 CLI 主线命令

从其他目录运行时，也可使用 `"$QOR_ROOT/setup.csh" cli refresh --work "$QOR_WORK"`。其余 CLI 子命令用法相同。

```bash
# 查看主线分组帮助
PYTHONPATH=src python3 -m ai_lib_qor --help

# 一键三层刷新（L1 -> L2 -> L3）
PYTHONPATH=src python3 -m ai_lib_qor refresh --work work

# 只读查看各库状态与采纳状态（表格视图）
PYTHONPATH=src python3 -m ai_lib_qor refresh-status --work work --format table

# 增量批量检查（仅检查最新有效版本尚无结果的库，默认懒生成 Excel）
PYTHONPATH=src python3 -m ai_lib_qor check-pending --work work --format table

# 显式人工采纳 / 回退采纳（不改写最新计算版本）
PYTHONPATH=src python3 -m ai_lib_qor accept-revision --work work --vendor V --library LIB --revision rev_0002 --reason "复核通过"

# 只读存储占用统计 & 可重建缓存安全演练/清理
PYTHONPATH=src python3 -m ai_lib_qor storage-stats --work work --format table
PYTHONPATH=src python3 -m ai_lib_qor cache-clean --work work --format table          # 默认 dry-run
PYTHONPATH=src python3 -m ai_lib_qor cache-clean --work work --apply               # 仅清理可重建缓存
```

### 4. 工作台监听与局域网访问

- 默认监听 `127.0.0.1`。可在工作目录的 `path_sources.json` 配置局域网监听地址、客户端网段与访问主机名。所有写操作强制 CSRF 校验。
- 只读 JSON API：`/api/v1/overview`、`/api/v1/storage`、`/api/v1/library`、`/api/v1/check`、`/api/v1/facts`。
- 异步后台任务接口：`POST /api/v1/jobs/refresh`、`POST /api/v1/jobs/check`、`GET /api/v1/jobs/<job_id>`。

配置示例（将主机地址和网段替换为实际环境值）：

```json
{
  "workbench": {
    "host": "0.0.0.0",
    "port": 5059,
    "allowed_clients": ["192.168.10.0/24"],
    "allowed_hosts": ["192.168.10.20", "qor.lab"]
  }
}
```

启动时读取此配置，`--host` 和 `--port` 可覆盖监听设置。客户端和请求主机名须同时符合白名单。默认保留本机访问，直连局域网时使用配置中的 IP 或 DNS 名称。

### 5. 开源 PDK 多版本规模与体积压测（隔离沙箱，不触碰 `work/`）

```bash
PYTHONPATH=src python3 tools/benchmark_scale.py --libraries 8 --versions 12 --checks-per-lib 4 --formal-repeats 5 --no-excel
```

详细架构与状态边界说明见 [docs/architecture-steward.md](file:///home/polaris/文档/ChatGPT/ai_lib/ai_lib_qor/docs/architecture-steward.md)。
