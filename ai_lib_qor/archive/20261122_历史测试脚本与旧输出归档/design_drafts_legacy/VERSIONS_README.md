# 有效版本与采纳：最小可运行模块

本模块读取已有的 v3 `delivery_record.v1` 或 `formal_snapshot.v1` 中间产物，生成 `effective_version.v1`、`acceptance_event.v1` 和 `effective_index.v1`。它不扫描 RAW、不生成交付 JSON、不进行 LEF 内容检查，也不修改输入 RAW 文件。

## 依赖与启动

- Python 3.10+、`jsonschema`（支持 Draft 2020-12）、POSIX `fcntl` 文件锁。
- 在项目根执行以下命令。确保使用的 Python 已安装 `jsonschema`；`schemas/` 需要保留在项目根。

```bash
cd /path/to/ai_lib/ai_lib_qor
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
python3 -m ai_lib_qor.versions --help
```

以下路径均是示例。`--effective-dir` 应指向指定 IP 的 `.../ips/<ip>/effective/`，应由使用者先确认目录和有效集归属。

## 用交付建立初始版本

```bash
python3 -m ai_lib_qor.versions init \
  --effective-dir /example/work/vendors/vendor_a/libraries/library_x/ips/rtavfs/effective \
  --delivery /example/work/vendors/vendor_a/libraries/library_x/deliveries/delivery_v07.json \
  --set-id rtavfs_primary --owner-type BUSINESS_IP --owner-id rtavfs --home-library library_x
```

也可以将 `--delivery` 替换为 `--snapshot /example/work/formal_nl/NL2.5.3/snapshots/snap_0001/snapshot.json`。初始来源必须包含已确认的文件身份，快照必须是 `COMPLETE_IN_SCOPE`。默认根据已保存 JSON 计算，不检查 `source_root` 或底层文件；需要验证实体 RAW 时显式增加 `--verify-files`。

## 增量交付、文件选择和跨库

```bash
python3 -m ai_lib_qor.versions apply \
  --effective-dir /example/work/vendors/vendor_a/libraries/library_x/ips/rtavfs/effective \
  --delivery /example/work/vendors/vendor_a/libraries/library_x/deliveries/delivery_v08.json \
  --file-key library_x:lef:core
```

- `--file-key` 可重复；省略时会应用交付记录中的**全部已确认文件和显式删除**。如果只想采用部分文件，请指定该参数。
- 未指定 `--file-key` 时，身份未解析的文件会阻止整包应用；指定后只检查所选文件位。默认不验证实体文件；`--verify-files` 仅检查所选文件。来源旁证表明文件位仅来自文件名候选时，不允许整包自动采用；需明确选择。旧记录缺失旁证时仍无法确认该身份的由来。
- 默认只接受 `home_source_library_id` 的交付。跨库时需由使用者先确认归属，并在该次命令增加 `--allow-source-library <library_id>`；该参数可重复，不会保存长期授权配置。
- 无论 FULL / INCREMENTAL / PATCH / UNKNOWN，缺席文件一律不自动删除；只应用显式声明的 `explicit_removed_file_keys`。本模块不推断交付包范围和文件身份。
- 默认根据已消费并归档的交付记录，对每个 SourceLibrary 检查 `delivery_order` 严格递增且唯一；重复消费完全相同的记录可用于幂等或选择其余文件。相同 `delivery_id` 的记录发生任何变化会被拒绝。以正式快照或外部历史初始化时，该模块无法自动知道未归档交付的先后，需要用户预先核对。
- 无成员变化不产生新 Rev；新 Rev 的 `members` 是完整集合，`changes` 是相对父版的差异。交付记录和引用身份由上游负责真实性；相同 ID 的外部文件被原地改写不会自动被版本模块发现。

## 人工采纳、回退和恢复

```bash
python3 -m ai_lib_qor.versions accept --effective-dir /example/work/effective \
  --revision rev_0001 --actor engineer --reason '已核对'
python3 -m ai_lib_qor.versions rollback --effective-dir /example/work/effective \
  --revision rev_0001 --actor engineer --reason '回退'
python3 -m ai_lib_qor.versions revoke --effective-dir /example/work/effective \
  --revision rev_0001 --actor engineer --reason '撤销'
python3 -m ai_lib_qor.versions rebuild-index --effective-dir /example/work/effective
```

本实现约定：ACCEPT 可选已存在的任一 Rev；ROLLBACK 要求目标早于当前已采纳 Rev；REVOKE 只撤销当前已采纳 Rev。事件按 JSONL 文件顺序重放，最新计算与已采纳版本独立。**命令接收 actor 字符串，不实现身份认证或授权；生产接入需要上层负责权限和审批。** 这些回退语义属于本模块实现约定，需与实际业务规则确认。

版本文件使用独占发布，索引采用临时文件与原子替换；Linux 本机上使用 `flock` 协调本模块的并发调用。网络文件系统的锁和原子语义需部署方验证。事件追加与索引更新不是跨文件事务：若事件已追加而索引更新失败，检查事件后运行 `rebuild-index`；若 JSONL 末尾损坏，命令会拒绝重放，需人工检查修复，不能盲目删除历史。消费输入副本归档于 effective 目录的 `_inputs/deliveries/`，只作为身份和顺序核验依据，并非第二套独立业务真相。

## 模拟测试

```bash
python3 -m unittest discover -s tests -v
```

测试在临时目录创建 V07/V08 RAW 文件、基于 v3 合成交付记录运行完整命令，不写真实 RAW；覆盖增量继承、部分选择、正式快照基线、显式删除、跨库确认、旧交付和同 ID 修改拒绝、采纳回退、索引重建及原 v3 历史兼容。此测试不代表真实企业 RAW/正式 NL 的端到端验收。
