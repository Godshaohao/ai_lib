# RAW 与 Formal NL 总目录盘点

配置存放在 `work/path_sources.json`，仓库提供 [配置样例](../examples/path_sources.example.json)。RAW 按 `<root>/<vendor>/<library>/<version>/` 组织，每个根可以包含不同库，也可以包含同一库的历史版本。

```bash
PYTHONPATH=src python3 -m ai_lib_qor refresh \
  --work /path/to/work \
  --raw-root /path/to/RAW_A \
  --raw-root /path/to/RAW_B \
  --nl-root /path/to/lib_NL2.5_3 \
  --nl-version NL2.5.3
```

CLI 可重复指定 `--raw-root`。保存配置时使用 `raw_roots` 数组，兼容旧的 `raw_root` 单路径。工作台的 RAW 根目录输入每行一个。指定 `--vendor` 和 `--library` 后，RAW 只盘点对应库。未提供 `--nl-version` 时可从符合命名规则的正式目录推断阶段。

## RAW 交付与软链

- 同一供应商、库和版本对应多个不同物理目录时，记录冲突并跳过该版本。
- 有日期的版本按名称中的日期排序，同日带日期的记录可用用户登记时间或目录修改时间区分。无日期时优先使用登记时间，其次用归档目录修改时间，最后用自然版本顺序。没有时间依据的交付排在有时间依据的交付之前。
- 文件链接和目录链接允许指向已配置的 RAW 根。额外可信目录可列在 `raw_link_roots` 中。所有来源目录须与工作目录分离。系统会报告越界、断链和回环，受影响的交付留待处理。
- Delivery 保留 RAW 的逻辑相对路径与目录修改时间 `directory_mtime`。`raw_observations.tsv` 为软链成员保存首次观察的真实目标。FileFacts 和检查读取时核验目标与文件元数据。普通已归档版本可增量复用，含软链的版本会重查链接，盘点只读取路径和元数据。

## Formal NL 快照与独立条目

- 正式目录每轮单次盘点。`path` 保存 NL 相对路径，`target` 保存链接原文，`resolved` 保存真实目标。穿过 RAW 软链时额外写入 `raw_path`，使索引和 Effective 能定位对应的 RAW 逻辑路径。
- NL 普通文件以及独立于 RAW 的有效文件链接或目录链接，分别记为 `NL_ONLY:FILE`、`NL_ONLY:LINK`、`NL_ONLY:DIRECTORY_LINK`，可在 `work/formal_observations.tsv` 查看。独立目录链接记录目标目录。已匹配的库可照常生成快照。
- 断链、无法唯一归属的 RAW 目标及改指向的归档链接仍记为未解析。只盘点独立 NL 时，可关闭 RAW 同步并设置空的 `raw_roots`。

Delivery 在库目录的 `delivery/` 内归档，名称为 `delivery_<library>__<version>.json`。Formal 快照在 `formal/` 内按 NL 阶段和观察时间归档，同秒使用序号区分。
