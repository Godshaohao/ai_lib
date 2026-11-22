# 存储迁移和回滚

状态：新增扁平库目录写入及旧目录读取；未迁移历史，v2 新记录写入未实施。具体规则以 [扁平库目录与 JSON 命名](2026-11-18_扁平库目录与JSON命名.md) 为准。

用户确认：新写入以 `work/libraries/<Vendor>/<来源库>/` 平铺；旧位置和规格中的精简位置均应读取。因此规格中的 `formal/<NL>/` 作为兼容读取位置，而不是新权威写入位置。Formal 仍按 NL / Vendor / 库分别维护快照历史。

| 对象 | 现有写入 | 兼容读取位置 | 迁移状态 |
|---|---|---|---|
| Delivery v1 | `libraries/<v>/<l>/delivery_<序号>.json` 和旁证 | 原深层位置及 `raw/<v>/<l>/<id>.json` | 原历史未复制 |
| Formal v1 | `libraries/<v>/<l>/formal_<NL>_<序号>.json` | 原深层位置、旧 `formal_nl/<NL>/snapshots/` 及 `formal/<NL>/<id>.json` | 原历史未复制 |
| Effective v1 | `libraries/<v>/<l>/effective_<set>_<序号>.json` | 旧 `ips/<ip>/effective/versions/` | 顶层 `effective/<set_id>` 尚未适配 |
| 采纳事件 | `libraries/<v>/<l>/effective_<set>_acceptance.jsonl` | 旧 `acceptance.jsonl` | 不迁移、不重写 |

来源 Repository 对同一来源身份的相同 v1 记录去重；不同内容报告冲突并从查询结果排除。旧 `source_evidence.json` 读取到内存，不重写旧证据。缺失旁证不能证明文件位已人工确认。另有旧版本输入归档 `_inputs/deliveries` 仍被版本防回退逻辑使用，本次没有删除或迁移。

如果以后需要物理迁移：先只读枚举来源、目标、Schema、身份和引用冲突；对每条记录校验原始字节、引用、权限及路径安全；备份、经明确授权后复制并核对；冲突一律停止。回滚通过停止新写入、恢复原工作树及配置、保留或隔离新增副本完成；不可覆盖既有历史或删除采纳事件。本次没有提供可执行迁移器。
