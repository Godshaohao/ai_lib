# versions/delivery_policy.py · 设计伪代码

> **拟议，非可执行代码。** 以下接口名、内部结构和错误策略供评审，不声称当前已实现。

- **职责**：解释交付范围和继承。
- **接口**：`apply(parent_members, delivery, selection) → CandidateChanges`
- **输入**：父版成员、交付模式、显式删除、人工选择。
- **输出**：候选成员变化和不确定项。
- **配置 / 依赖**：delivery_rules.yaml。

## 算法与处理顺序

```text
过程 apply(parent_members, delivery, selection) → CandidateChanges
    依据已确认 FULL/INCREMENTAL/PATCH 语义选择替换；显式删除单独处理；未确认覆盖不推断删除
    返回上述输出或明确失败
```

## 异常与边界

UNKNOWN 或覆盖证据不足时拒绝隐式删除；PARTIAL 不自动映射 INCREMENTAL。所有正式业务记录仅通过统一 Publisher 或其事件追加入口发布；本文件只有设计内容。

## 合成规则（伪代码）

```text
members = 父版成员映射的副本
for 本次明确选择且分类为 RESOLVED 的文件:
    按 file_key 新增或替换；保留具体 source_ref
for explicit_removed_file_keys 中经确认允许移除的 file_key:
    从 members 移除并记录 REMOVED
if package_mode == INCREMENTAL:
    未出现在本次包中的既有成员保持原引用
if package_mode == FULL:
    只有范围明确且删除语义经确认时，才应用相应范围规则
if package_mode in {UNKNOWN, PATCH} 且规则/证据不足:
    不推断隐式删除；返回需确认
根据父版与最终 members 计算 changes；返回完整 members 和 changes
```

## 对应 v3 JSON 字段与术语

下列字段是本模块**读取、贡献或校验的范围**，并不表示该模块独立写入整份 JSON。字段必需性来自 v3 文档；完整结构及示例见对应字典。

### [DeliveryRecord 字段字典与完整示例](../../../contracts/delivery.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `package_mode` | 是 | enum | FULL/INCREMENTAL/PATCH/UNKNOWN |
| `package_scope.file_keys[]` | 是 | array | 已声明的交付覆盖范围（本例用明确的逻辑文件位）；复杂真实包可由现有配置进一步限定 View/Corner/Mode |
| `package_scope.scope_confirmed` | 是 | boolean | 是否人工/来源确认覆盖范围；未知时不能推断隐式删除 |
| `explicit_removed_file_keys[]` | 是 | array | 供应商明确声明移除的文件位，默认为空；不要由“包里缺失”自动推断 |
| `files[]` | 是 | array | 本次**实际出现**的文件记录 |

### [EffectiveVersion 字段字典与完整示例](../../../contracts/effective.md)

| 字段 | 适用 / 必需性 | 类型 | 中文含义与边界 |
|---|---|---|---|
| `members[]` | 是 | array | **完整**有效文件成员集合，不只本次变更文件 |
| `changes[]` | 是 | array | 与前驱 Rev 的文件成员差异，**不是 Macro/PIN 语义差异** |
| `changes[].action` | 是 | enum | ADDED / REPLACED / REMOVED |

术语和 source_ref 的完整定义见[中英文术语表](../../../contracts/术语表.md)。
