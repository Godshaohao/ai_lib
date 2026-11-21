# RAW 与 NL 总目录盘点

`inventory-roots` 是新的两类 JSON 生成入口，只读取 RAW 与 Formal NL，不生成或使用旧交付 ID、文件 ID、file_key、扫描证据侧车。它不会调用旧工作台的登记流程，也不会更新旧有效版本和旧索引。

```bash
PYTHONPATH=src:../src python3 -m ai_lib_qor inventory-roots \
  --raw-root /path/to/3rd_IP \
  --nl-root /path/to/lib_NL2.5_3 \
  --nl-version NL2.5.3 \
  --output /path/to/new-work
```

`--nl-version` 可以省略；此时尝试从 NL 根目录名提取版本。`--output` 不能和两处来源目录重叠，旧格式输出需先另行迁移，不能混写。默认按 `RAW/<vendor>/<library>/<version>/...` 发现版本：支持已识别的日期前缀、V/REV 等版本目录；不符合规则的目录不能当作已识别版本。扫描只记录路径和真实 Birth Time，不计算文件内容哈希。操作系统不支持 Birth Time 时填写 null，不能用 mtime 或 ctime 冒充。

可用 `--skip-raw`、`--skip-formal`、`--skip-index` 选择更新步骤；`--vendor` 与 `--library` 同时指定时只写入对应库。仅刷新索引可以不提供来源路径，例如：

```bash
PYTHONPATH=src:../src python3 -m ai_lib_qor inventory-roots --output /path/to/work --skip-raw --skip-formal --vendor SRAM22 --library sram22_256x16m8w8
```

Formal 更新仍需盘点 RAW 以匹配真实链接目标；当前 RAW 盘点并非增量算法，按库过滤只限制写入范围，不限制 RAW 总目录的扫描范围。索引不能刷新时命令返回非零并报告原因。

新路径式工作台从 `python3 -m ai_lib_qor.workbench --work /path/to/work --path-mode --port 5051` 启动，依次为来源总览、库与版本、文件索引；更新选项与 CLI 调用同一入口。来源目录和选项保存在 work 的 `path_sources.json`，页面读取不会自动扫描。旧工作台入口仍可用于旧工作目录。

输出为 `libraries/<vendor>/<library>/delivery_<library>_<YYYYMMDD>_<序号>.json` 和 `formal_<NL>_<YYYYMMDDTHHMMSSZ>_<序号>.json`；交付无法提取日期时文件名使用 `undated`，NL 文件名时间来自 `observed_at` 的 UTC 时刻，同秒快照通过序号区分。NL 对整个目录只盘点一次，将每个文件链接严格解析为真实目标，与本次 RAW 清单的绝对路径唯一匹配后分配供应商、库和 RAW 版本。快照中 `path` 是 NL 根目录的相对路径，`target` 是链接原文，`resolved` 是最终真实路径。未匹配、损坏链接、普通文件和未遍历的目录链接写入命令返回的 warnings；不会将其推断到某个库，也不能据此推断正式库齐套。

三个 JSON 中的时间点统一使用 UTC、秒精度的 `YYYY-MM-DDTHH:MM:SSZ`：Delivery 的 `directory_created_at` 是文件系统真实创建时间（可能为 null），Formal 的 `observed_at` 是观察时间，Effective 的 `created_at` 是生成时间。`version_date` 只代表供应商名称中的日历日期，格式为 `YYYY-MM-DD`，它不是一个时间点，不能与上述时间直接按字符串比较。读取旧记录时接受带时区的 ISO 8601 时间，但不改写既有历史。

每个库在可确定顺序时自动维护 `latest_delivery.json` 软链接；Formal 使用 `latest_formal_<NL>.json`，生成有效版本后使用 `latest_effective.json`。无日期版本可在 `work/scan_sources.json` 的对应 source 中用 `version_registration_times` 按版本名明确登记带时区的交付时间，例如 `{"V01":"2026-01-01T12:00:00Z"}`。日期相同且无法比较时不按目录名、目录创建时间或序号猜测，返回警告并移除可能过时的交付指针。

从 Formal 的真实链接初始化有效版本：

```bash
PYTHONPATH=src:../src python3 -m ai_lib_qor minimal-effective-init \
  --work /path/to/new-work --vendor SRAM22 --library sram22_256x16m8w8 \
  --formal /path/to/new-work/libraries/SRAM22/sram22_256x16m8w8/formal_NL2.5.3_20261120T123456Z_001.json \
  --include LEF=LEF/sram22_256x16m8w8.lef
```

`--include` 可重复，限定初始有效集；省略时使用同库快照中全部已匹配链接，应先确认其属于有效集。`minimal-effective-update --work ... --vendor ... --library ... --operations ops.json` 使用 `{"set":[{"view":"LEF","version":"V06","path":"LEF/a.lef"}],"remove":[]}` 明确更新；未提及成员继承，只有显式 remove 才删除。同一 View 和相对路径视作同一文件位，不自动处理改名或模糊匹配。Effective 是完整文件组合，不表示内容对比或质量检查通过。

重复运行时，相同版本的相同清单和相同链接快照不重写；同一 RAW 版本的路径清单或目录时间发生变化时报告并保留原文件。七字段 Delivery 没有文件大小和修改时间，**无法发现文件路径不变的内容原地修改**；需要独立的扫描状态机制才能安全增加该能力。编号用于文件存放，不代表用户确认过的业务顺序。

## 路径索引与四类 JSON 联动

`file_index.json` 是从同库 Delivery、Formal 和 Effective 构建的派生查询文件，包含示例中的 `vendor`、`library`、`deliveries`、`nl_snapshots`、`revisions`、`views`。每个 View 的相对路径下面按旧到新列出 `raw`、`nl` 和 `effective` 历史，并保存完整路径。交付顺序优先使用版本日期，无日期使用用户登记时间；同一日无法判定先后时不生成有序索引。目录序号和目录创建时间不是业务顺序。

扫描登记、Formal 更新和 Effective 发布后尝试自动刷新同库索引。刷新只读取本地 JSON，不扫描 RAW，不计算 SHA；目前会重建整个库的内存投影，结果不变时不重写文件，尚未实现真正的增量索引计算。已发布索引中的旧历史如果发生改变或删除，拒绝覆盖并报告；Effective 已保存但索引刷新失败时返回 `PUBLISHED_INDEX_STALE`。

`source_match=MATCHED_RAW` 表示快照中保存的链接文本、解析路径和 Delivery 记录在字符串和路径上吻合；**不会重新读取现场软链接，也不证明文件内容相同**。文本目标与记录的最终路径不一致时标记 `UNVERIFIED`，其中可能包括多级软链接，需要另行实地核验。

手动刷新和查询（查询前完整重新核对归档，过期时拒绝返回旧结果）：

```bash
PYTHONPATH=src:../src python3 -m ai_lib_qor minimal-index-refresh --work /path/to/new-work --vendor SRAM22 --library sram22_256x16m8w8
PYTHONPATH=src:../src python3 -m ai_lib_qor minimal-index-query --work /path/to/new-work --vendor SRAM22 --library sram22_256x16m8w8 --view LEF --path LEF/sram22_256x16m8w8.lef --revision rev_0002
```

查询可改用 `--version <交付版本>` 返回该交付及之前最后一次出现的文件来源；这只表示已记录来源，缺席不能推断文件删除或实际内容未变。

旧 `work/`、旧 `evidence_delivery` 及旧消费代码仍存在，旧 Effective 和 Web 仍依赖其中的历史身份。本入口产物不含旧身份，但还没有替换现有 `scan`、`formal-sync`、Effective、Web 和报告的消费链。未经完整迁移，不应将本入口的输出直接覆盖旧 `work/` 或声称旧标识已全局删除。
