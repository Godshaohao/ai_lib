Status: current

# Review Gate

Review Gate 是轻量 release 风险门禁，不是多部门审批系统。

它把审查项分成三类：

| 输出 | 含义 |
| --- | --- |
| `blocking_items` | 会阻塞当前 gate 的真实问题，例如 catalog 关系不可信、release fatal issue、metadata-only 二进制变化需要 owner 接受 |
| `attention_items` | 建议关注的证据，例如重点 File Diff；默认不阻塞 `current` |
| `accepted_items` / `waived_items` | 通过 CLI 写入的 owner 人工决策 |

主要文件：

```text
$WORK/catalog/html/catalog_state.json
$WORK/catalog/html/manager_tasks.json
$WORK/review/<library>/<version>/review_gate.json
$WORK/review/<library>/<version>/review_overrides.json
```

常用命令：

```csh
$PROJ/scripts/lg.csh rv check  <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rv list   <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rv accept <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
$PROJ/scripts/lg.csh rv waive  <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
```

`lg.csh action` 是 action 文件执行入口；Review Gate 的人工决策只使用
`rv` 子命令。

每个 `blocking_items` 和 `attention_items` 条目都会带解释字段：

| 字段 | 含义 |
| --- | --- |
| `rule_id` | 触发该条目的稳定规则名 |
| `rule_source` | 规则来源，默认 `review_gate.v1` |
| `why` | 为什么这个证据需要处理 |
| `next_action` | reviewer 下一步可执行动作 |

这些字段只解释 gate 判断，不新增审批流、owner 分配或状态机。

Release policy 默认规则：

- `current` 要求 `review_gate.blocking_open == 0`。
- `current` 默认不要求所有 File Diff recommendation 都完成。
- `approved` 可以由 policy 要求更严格的 deep diff 或 pairwise completion。
- release 默认使用 manifest-driven file-level symlink 模式，正式落盘为扁平大写
  View 目录，例如 `LEF/`、`LIB/`、`RTL/`、`GDS/`。`--overwrite` 只替换
  manifest 中列出的目标；只有完整组合 release 显式设置 `mirror_release_root=true`
  时才删除未列出的旧文件。

人工确认和 action 文件详见
[人工确认与 Action 流程](manual_confirmation_action.md)。
