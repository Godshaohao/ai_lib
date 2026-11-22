# CLI 与工作台共同数据流

CLI 和 Web 使用同一个 `work` 目录保存交付、正式快照和有效版本，使用同一个 `runs` 目录保存扫描记录、运行状态及报告。Web 页面读取这些记录；Web 的操作按钮也调用共享应用服务。

```text
RAW / Formal NL → 扫描与登记 → work 中的交付 / 快照
                                     ↓
                        版本 CLI → 有效版本 / 采纳
                                     ↓
                文件事实 + 明确的检查计划 → 检查 JSON
                                     ↓
                      单版本报告 / 整体 IP 报告
                                     ↓
                        Web 读取 work 和 runs
```

## 准备环境

在 `ai_lib_qor` 目录安装 `requirements-pipeline.txt` 中的依赖；来源自动分类和 Formal 同步还需使用同级 `../src` 中的 `lib_guard`。下列命令在该目录执行：

```bash
export PYTHONPATH="$PWD/src:$PWD/../src${PYTHONPATH:+:$PYTHONPATH}"
python -m ai_lib_qor --help
python -m ai_lib_qor.versions --help
```

## 扫描和登记

在工作目录的 `scan_sources.json` 配置 RAW 来源。无过滤参数时扫描所有已配置库；也可用 `--vendor` 和 `--library` 筛选。

```bash
python -m ai_lib_qor scan --work /path/to/work --runs /path/to/runs
python -m ai_lib_qor scan --work /path/to/work --runs /path/to/runs --vendor vendor_a --library library_x
```

扫描比较文件大小和修改时间，保存扫描和分类记录，满足条件的版本自动登记交付。原地修改、未识别文件等结果以扫描/登记记录中的状态为准；不代表文件内容相同或版本已经采纳。

需要显式映射时，可通过 `register --help` 查看手动登记的来源、扫描记录、元数据和文件映射参数。较低层的 `delivery` 命令可按明确的配置生成单份交付记录。

## 正式来源与版本

```bash
python -m ai_lib_qor formal-sync --work /path/to/work --runs /path/to/runs
python -m ai_lib_qor.versions init --help
python -m ai_lib_qor.versions apply --help
python -m ai_lib_qor.versions accept --help
```

正式来源使用 `work/formal_sources.json` 配置。`versions` 命令还支持 `rollback`、`revoke` 和 `rebuild-index`。当前 `apply` 使用最新计算版本作为父版本，不自动等同于最新采纳版本。

## 检查与报告

`facts`、`check` 和 `report` 为明确输入的底层命令。以下命令为一次运行保存 `input_plan.json`、`status.json`、`check.json`、`report.html` 和 `report.xlsx`：

```bash
python -m ai_lib_qor run-plan --plan /path/to/plans/rev_0002.json --runs /path/to/runs \
  --work /path/to/work --vendor vendor_a --library library_x --ip ip_a --revision rev_0002

python -m ai_lib_qor run-ip --work /path/to/work --runs /path/to/runs --plans /path/to/plans \
  --vendor vendor_a --library library_x --ip ip_a
```

文件解析证据也可以作为带状态的运行生成：

```bash
python -m ai_lib_qor run-evidence --delivery /path/to/delivery.json --file-id file_id --runs /path/to/runs
```

`run-ip` 为已保存的每个有效版本寻找**恰好一份**匹配计划，执行每份计划并保存各版本结果，再输出 `overall.json` 和 `overall.xlsx`；计划缺失或重复时不会执行。单次运行的状态为失败、或整体运行部分失败时，CLI 返回非零退出码，并保留可检查的状态。

当前计划和文件事实仍需事先准备；这些命令不会自动为任意新交付生成完整检查计划，也不会声称实现了全部文件类型或检查规则的自动增量复用。

## 打开工作台

```bash
python -m ai_lib_qor.workbench --work /path/to/work --runs /path/to/runs --plans /path/to/plans --port 5051
```

工作台必须使用与 CLI 相同的目录，才能显示 CLI 生成的交付、版本和运行记录。`run-plan` 如果省略归属参数，产生的是未绑定 IP 的运行；需要在 IP 工作区中识别时应填写完整的 `--work`、`--vendor`、`--library`、`--ip` 和 `--revision`。
