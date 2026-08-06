
# 审计基线

我在输出前再次刷新了提交页、分支页和 PR 页。当前公开可见的 `main` 仍停在 **2026 年 7 月 10 日的 `ede5d48`**；分支页没有 7 月 11 日更新的活动分支，公开 PR 也是 0。所以下面的结论针对**当前 GitHub 公开 `main` 和其 RAW docs/source**；若最新修改位于尚未公开的 SHA，本轮不包含那部分。([GitHub][1])

# 总体结论

这轮 docs 的进步很明显：普通用户路径已经从散乱的 `scan/cmp/intake/window` 收敛成：

```text
已知库入库
  → Catalog
  → next 预演
  → next --apply
  → Version Detail 审查
  → next --accept
  → rel 预检查
  → rel --apply
```

同时明确了：

* 已知库根优先 `library add`，不扫整棵 RAW；
* `next` 是普通用户入口；
* FULL 和 FIX/HOTFIX 共用同一个接入入口；
* scan/diff/effective 是事实，Version Detail 是审查投影；
* 错误 accept 可以回退 effective pointer；
* Release 应由 manifest 驱动。([GitHub][2])

但从源码调用链看，当前流程还没有形成真正闭环。最核心的问题是：

> **Version Review、Effective Accept 和 Release 目前仍是三个“相邻但没有被硬约束绑定”的系统。**

我确认到三个 P0 级断点：

1. **Release Check 失败后，默认短命令链仍可能继续执行 apply。**
2. **普通 Release 路径发布的是 Catalog raw version，而不是已接受的 composite effective。**
3. **`next --accept` 没有验证计划完成、compare 新鲜度或 Review Gate，只验证 candidate manifest 存在。**

这三个问题叠加后，最危险的静态调用链是：

```text
FULL_A + FIX_B
      │
      ├── next --accept
      │      仅因 candidate manifest 存在而写 current pointer
      │
      └── rel LIB FIX_B --apply
             │
             ├── 检查的是 FIX_B 的 scan/diff
             ├── 即使 BLOCK，catalog release-check 仍返回 0
             ├── manifest 从 Catalog 的 FIX_B raw version 生成
             └── linker 明确不承担 gate，却可以执行文件系统写入
```

这意味着当前代码并不能严格证明：

```text
被审查的对象
  =
被接受的对象
  =
被 release-check 授权的对象
  =
最终落地的对象
```

---

# 一、P0：Release Gate 当前是 fail-open

## 文档承诺

教程写的是：

```text
lg rel LIB VERSION
```

默认先执行 release check，再生成 symlink release 规划；`--apply` 才真正落地。Force 也被描述成一个必须记录操作者和原因的显式绕过入口。([GitHub][2])

## 实际调用链

短命令 `rel` 会展开成两个顺序执行的底层命令：

```text
catalog release-check
release-batch
```

短命令主循环只有在前一个命令返回非零时才会停止。([GitHub][3])

Checker 本身能正确计算：

```text
PASS
PASS_WITH_WARNING
BLOCK
FAILED
```

例如 required view 缺失、scan status 不允许、Review Gate 未关闭、alias gate 不满足，都可能产生 blocker 并把 `release_check_status` 设成 `BLOCK`。([GitHub][4])

问题出在 Catalog 入口：

```python
def run_catalog_release_check(...):
    ...
    print_json(result)
    return 0
```

无论 `release_check_status` 是 `PASS` 还是 `BLOCK`，它都返回成功码 `0`。因此短命令不会停止，会继续执行 `release-batch`。([GitHub][5])

`release-batch` 只有在用户主动传入以下可选参数时，才按检查状态过滤：

```text
--only-checked
--only-ready
```

默认情况下这两个参数都是关闭的，所以 BLOCK 版本仍可进入 selected 集合。([GitHub][5])

随后调用的 manifest linker 自己明确声明：

> 它有意不作为 Release Gate，只负责 dry-run/apply 文件系统操作和记录证据。([GitHub][6])

## 为什么这是 P0

这不是“UI 显示不准确”，而是**阻断结论没有转化成控制流阻断**：

```text
Release Check = BLOCK
        ↓
进程退出码 = 0
        ↓
Release Batch 继续
        ↓
Linker apply
```

同时，文档把 `--force` 描述为正式的绕过和审计入口，但当前调用链存在一种**不需要 `--force` 的隐式绕过**，因此 force audit 模型也被削弱了。

值得注意的是，另一个较低层的 `run_release_check()` 实现是正确的：它会在 `BLOCK/FAILED` 时返回 `2`。所以问题不是 checker 核心不会判断，而是 **Catalog/短命令路径丢失了失败语义**。([GitHub][7])

## 必须立即修改

最低限度修复：

```python
status = result.get("release_check_status")
return 0 if status in {"PASS", "PASS_WITH_WARNING"} else 2
```

但只改退出码还不够。Release batch 应改成默认 fail-closed：

```text
显式请求某个版本发布
    + 没有 PASS/PASS_WITH_WARNING 的当前检查
    = 返回非零，零文件系统写入
```

`--only-checked` 和 `--only-ready` 不应该是安全增强选项；应该成为默认不可绕过行为。真正绕过只能走：

```text
--force
--force-reason
--force-by
```

---

# 二、P0：发布对象不是已接受的 Effective

## 文档的数据契约

数据契约明确写明：

```text
effective_manifest.json
Producer: intake/effective
Consumer: Version Detail, release
```

也就是说，接入流程构建并接受的 effective manifest，本应成为 Release 的上游对象。([GitHub][8])

## 实际普通用户入口

短命令仍然要求：

```text
lg rel LIBRARY VERSION
```

这里必须输入一个 Catalog raw version，没有“发布 current effective”的默认语义。([GitHub][9])

Catalog release 路径会：

1. 找到这个 Catalog version；
2. 从该 version 的 `scan_dir` 取扫描证据；
3. 调用 `create_manifest_template_from_catalog()`；
4. 只传入该 Catalog version 的 `version_key`；
5. 将生成的 manifest 交给 linker。

这条路径没有加载 `current_effective.json`，也没有读取被接受的 `effective_manifest.json`。([GitHub][5])

## FIX/HOTFIX 下的具体问题

假设当前有效组合是：

```text
FULL_1
  + FIX_2
  + FIX_3
  - deleted/file.lib
```

审查并接受后，业务对象应当是：

```text
EFFECTIVE_1_2_3
```

但文档又让用户执行：

```bash
lg rel LIB FIX_3
```

当前实现生成的是 `FIX_3` 这个 Catalog version 的 Release manifest，而不是：

```text
FULL_1 + FIX_2 + FIX_3 - tombstones
```

这会带来四类风险：

* FULL 中未被 FIX 重复携带的文件可能不在 manifest 中；
* 较早 FIX 添加或替换的内容可能不在 manifest 中；
* effective tombstone/delete 语义可能无法完整进入 Release；
* 最终结果可能依赖 release root 里此前遗留的文件，不再是可从 manifest 单独复现的封闭交付。

因此即使 Release Check 被修好，它检查的也仍可能是**错误的业务对象**：

```text
检查对象：raw FIX package
接受对象：composite effective
落地对象：从 raw Catalog version 生成的 manifest
```

## 正确方向

普通路径应该改成：

```bash
lg rel LIB
```

默认解析：

```text
current_effective pointer
    ↓
immutable effective manifest
    ↓
release manifest
```

raw version 发布只能是专家入口，例如：

```bash
lg rel LIB --raw-version VERSION
```

并且要明确显示：

```text
WARNING: publishing raw package, not accepted effective
```

对于 FULL，raw version 与 effective 可能恰好相同，但仍应通过同一条 effective-based 路径，以免 FULL 和 FIX 使用两套无法统一审计的语义。

---

# 三、P0：Accept 没有真正的审查门禁

## 文档承诺

教程将三步主路径描述成：

```bash
lg next LIB
lg next LIB --apply
lg next LIB --accept --by USER --note "review passed"
```

其中第三步明确说是在 Version Detail 审查通过后，写入 current effective。([GitHub][2])

## 实际代码

`cmd_accept()` 当前只验证：

```text
pending window 文件存在
package_type 没有 UNKNOWN
candidate_effective.manifest 字段存在
manifest 文件存在
```

随后直接执行：

```text
write_current_pointer(...)
window.state = ACCEPTED
```

它没有读取或验证：

* `current_plan.json` 是否为 `DONE`；
* 是否仍存在 `FAILED/PENDING` task；
* candidate effective build 是否成功；
* effective compare 是否存在；
* compare 是否对应当前 candidate；
* scan/diff/effective freshness；
* Review Gate 是否还有 blocking item；
* Version Detail `usage_decision` 是否为 `BLOCKED`；
* base trust 是否满足接受要求；
* candidate manifest 是否在审查后被修改；
* current pointer 是否在审查期间被其他人改变。([GitHub][10])

所以：

```bash
--by USER --note "review passed"
```

当前只是写入审计文字，不是一个由系统验证过的 Review Approval。

## 可能出现的错误接受

### 场景 A：计划执行到一半

```text
scan A       DONE
scan B       FAILED
effective    旧文件残留
compare      旧文件残留
```

只要 pending window 仍指向一个存在的 candidate manifest，accept 并不会主动检查计划状态。

### 场景 B：审查后 candidate 被重建

Reviewer 看的是 candidate hash A，但之后 intake 重建了同一路径的 candidate hash B。Accept 只检查路径存在，没有验证 reviewer 批准的是哪一份内容。

### 场景 C：Review Gate 仍有 blocker

`rv check/list/accept/waive` 与 `next --accept` 是并列入口；accept 没有强制消费 gate 的关闭状态。

### 场景 D：并发接受

两名 reviewer 同时基于旧 current effective 做审查，最后写 pointer 的人覆盖前一个结果。原子写只能避免半个 JSON，不能避免 lost update。

## 正确的 Accept Gate

Accept 前必须满足：

```text
plan.state == DONE
candidate manifest 存在且 hash 不变
effective compare 存在且 input hash 匹配
所有 required scan evidence fresh
base trust 可接受
effective conflicts == 0
review_gate.blocking_open == 0
review approval 绑定 candidate hash
current pointer revision == 审查时 revision
```

然后使用 compare-and-swap 语义：

```text
expected current = E_OLD
new current      = E_NEW

实际 current 不是 E_OLD
    → 拒绝，要求重新审查
```

---

# 四、逐阶段流程拷打

| 阶段              | 文档意图                                      | 当前实现情况                    | 结论               |
| --------------- | ----------------------------------------- | ------------------------- | ---------------- |
| 初始化             | 创建 workspace 和统一配置                        | 主路径清楚                     | 基本通过             |
| 新库入库            | 已知根直接 add；未知才 discover                    | 文档边界清楚，避免全 RAW 重扫         | 通过               |
| Catalog         | registry/catalog YAML 是输入，JSON/HTML 是投影   | 已增加 refresh 和 shrink 防护叙事 | 基本通过，但状态目录混杂     |
| `next` 预演       | 只读判断 FULL/FIX、Base、candidate              | 副作用边界写得清楚                 | 通过               |
| `next --apply`  | scan → effective build → compare → render | 有可恢复 plan DAG             | 有 stale reuse 风险 |
| Version Detail  | 唯一主要审查投影                                  | 证据分层较完整                   | 投影通过，门禁未闭环       |
| Review Gate     | blocker 和 owner 决策                        | checker 能消费 gate          | 与 accept 没绑定     |
| `next --accept` | 审查通过后接受 candidate                         | 仅检查 manifest 存在           | **P0**           |
| Release 目标生成    | 从已接受 effective 生成 manifest                | 从 Catalog raw version 生成  | **P0**           |
| Release Check   | BLOCK 应阻断后续                               | Catalog 入口 BLOCK 仍返回 0    | **P0**           |
| Link/Copy       | 只执行已授权 manifest                           | linker 明确不是 gate          | 依赖上游，但上游失效       |
| Postcheck       | 验证落地结果                                    | 位于文件系统写入之后                | 只能发现，不能预防        |
| Rollback        | 错误 accept 回退 pointer                      | 确实只重写 current pointer     | 不能回退已落地 Release  |

---

# 五、P1：Plan 的“输入指纹”实际只是命令字符串指纹

文档说，同一输入指纹下已经 `DONE` 的 task 会被复用，从失败点继续。([GitHub][2])

但源码中的 fingerprint 是：

```python
payload = json.dumps(command)
sha256(payload)
```

也就是说，它只 hash CLI command list。旧 task 只要 task ID 和这个 command hash 一致且状态为 `DONE`，就会继续保持 `DONE`。([GitHub][11])

下面这些业务输入变化不一定会改变命令字符串：

* 同一 raw path 下文件内容被供应商覆盖；
* registry/base 关系内容变化，但生成的命令参数没变；
* release/catalog policy 文件内容变化；
* parser 代码或 parser 版本变化；
* evidence schema 变化；
* base effective manifest 在同一路径下被重建；
* hash policy 的默认实现变化。

因此所谓 `input_fingerprint` 更准确的名称应是：

```text
command_fingerprint
```

不是：

```text
business_input_fingerprint
```

## 后果

计划可能显示：

```text
scan: DONE
effective_build: DONE
effective_compare: DONE
```

但这些 DONE 对应的是旧 RAW、旧 policy 或旧 parser 结果。

而且因为 plan engine 已经跳过 task，scan 内部自身的 freshness 判断没有机会执行。

## 应纳入语义指纹的内容

至少包括：

```text
raw inventory/root snapshot digest
catalog relationship digest
package/base override digest
scan policy digest
parser/tool build version
base effective manifest digest
candidate component list digest
command options
```

可采用：

```json
{
  "command_sha256": "...",
  "raw_snapshot_sha256": "...",
  "catalog_relation_sha256": "...",
  "policy_sha256": "...",
  "tool_version": "...",
  "base_manifest_sha256": "..."
}
```

任一变化都应使相关 task 回到 `PENDING`。

---

# 六、P1：检查结论没有绑定到精确 Release Manifest

当前顺序是：

```text
检查 scan/diff/gate
    ↓
把检查状态写入 Catalog
    ↓
之后再从 Catalog 生成 release_manifest.json
    ↓
交给 linker
```

检查结果没有记录或验证：

```text
release_manifest_sha256
effective_manifest_sha256
catalog snapshot digest
policy digest
review gate digest
```

因此，即使把 Catalog check 的退出码修好，仍然存在 TOCTOU 问题：

```text
检查时的对象 A
    ↓
Catalog/RAW/manifest 变化
    ↓
实际落地对象 B
```

`--only-checked` 目前验证的是 Catalog 中保存的状态值，而不是“这个精确 manifest 已被授权”。([GitHub][5])

## 推荐引入 Release Authorization

Checker 应输出：

```json
{
  "schema": "release_authorization.v1",
  "release_manifest_sha256": "...",
  "effective_manifest_sha256": "...",
  "policy_sha256": "...",
  "review_gate_sha256": "...",
  "status": "AUTHORIZED",
  "authorized_by": "...",
  "authorized_at": "...",
  "force": false
}
```

Linker 在 `apply=true` 时必须验证：

```text
authorization 存在
status == AUTHORIZED
manifest hash 完全相同
effective hash 完全相同
授权未被撤销
```

Dry-run 可以不要求授权，但 apply 必须要求。

---

# 七、P1：业务状态被放进了 HTML 投影目录

数据契约把以下内容放在：

```text
catalog/html/**/effective/*/effective_manifest.json
catalog/html/**/window/pending_window.json
catalog/html/**/current_effective.json
```

其中 `current_effective.json` 是由 accept/rollback 写入的当前有效版指针，不是单纯的页面样式或导航缓存。([GitHub][8])

但 README 又把：

```text
work/
```

描述为 generated local output、not source of truth；配置文档也强调 HTML 和本地产物应重新生成、不能作为源码或上游事实。([GitHub][12])

这里形成了物理边界上的矛盾：

```text
逻辑上：current effective 是业务状态
物理上：它位于 catalog/html 投影树
运维上：work/HTML 被描述为可重建生成物
```

即使 renderer 当前承诺不删除 effective，后续 cleanup、迁移、重新生成或用户清理 HTML 时仍容易误删业务状态。

## 建议目录

```text
$WORK/state/<LIBRARY>/
    current_plan.json
    pending_window.json
    review_approval.json
    current_effective.json
    effective/
        <DIGEST>/effective_manifest.json

$WORK/catalog/html/
    只保存 HTML、导航 JSON 和到 state/evidence 的相对引用
```

这样可以真正落实：

```text
state/evidence → renderer → HTML
```

而不是让状态与投影共享一个生命周期。

---

# 八、P1：Rollback 只回退 Effective Pointer

当前 rollback 做的事情是：

1. 找到旧 effective manifest；
2. 重写 `current_effective.json`；
3. 刷新页面。([GitHub][10])

这对“错误 accept、尚未发布”的场景是合理的。

但它不会：

* 删除或恢复 Release 目录中的 symlink/copy；
* 恢复 alias；
* 反向执行 mirror 删除；
* 检查当前 Release 是否来自被回退的 effective；
* 生成 Release rollback manifest。

因此文档必须始终明确区分：

```text
effective pointer rollback
```

和：

```text
deployed release rollback
```

建议命令和页面直接显示：

```text
该操作只回退 current effective，不修改已落地 Release。
```

如果产品需要 Release 回滚，应生成一个新的、可检查的 rollback manifest，而不是直接恢复目录快照。

---

# 九、Docs 本身的冲突和漂移

## 1. README 与主教程仍有两套主路径

README 的“最短入口”仍然是：

```text
intake --plan-only
intake
accept-window
rel
```

而基础教程和 CLI Reference 已经把普通用户入口定义成：

```text
next
next --apply
next --accept
```

`intake/window/accept-window` 被降级为专家入口。([GitHub][12])

这会导致两类用户使用两套术语：

```text
用户 A：next / candidate / accept
用户 B：intake / window / accept-window
```

README 应只保留 `next` 三步，专家入口只链接到 CLI Reference。

源码里的 `library add --apply --refresh-catalog` 后续提示也还在推荐：

```text
lg intake LIB --plan-only
```

而不是 `lg next LIB`，这也是同一类漂移。([GitHub][3])

## 2. Action 文件示例无法被当前 parser 接受

教程给出的示例是：

```text
@diff VERSION base=BASE scan_if_missing=true
```

但 `_parse_review_actions()` 要求 `@diff` 后必须恰好有三个位置参数：

```text
@diff OLD NEW NAME
```

否则直接报错。([GitHub][2])

因此当前文档的可复制示例会失败。

这类错误应通过“文档命令可执行测试”锁住，而不是靠人工同步。

## 3. “可接受”这个状态名称会误导 reviewer

多库 worklist 将下面状态称为“可接受”：

```text
candidate 已生成
没有待执行 task
```

然后建议运行 `next --accept`。([GitHub][2])

但这并不代表：

```text
Version Detail 已审查
Review Gate 已关闭
owner 已批准
```

建议拆成两个状态：

```text
执行产物已就绪（EVIDENCE_READY）
审查已批准（REVIEW_APPROVED）
```

只有第二个才能显示“可接受”。

## 4. Current 文档混入未来设计

`scan_evidence_review.md` 顶部标记为 `Status: current`，但后半部分同时包含：

```text
待收敛
P2
后续如果移动
增加配置
```

其中还给出嵌套 YAML：

```yaml
scan_output_policy:
  debug_json: false
  write_raw_parser_results: false
```

而当前 workspace 配置解析器实际上只是逐行解析一层 `key: value`，不支持嵌套 YAML。([GitHub][13])

建议每份文档把内容明确拆成：

```text
Current Contract
Implemented Behavior
Known Limitations
Proposed / Not Implemented
```

否则 `Status: current` 容易被理解为整份内容都已落地。

## 5. Evidence Level 术语尚未统一

不同文档同时使用：

```text
parsed
count-only
summary-only
metadata-only
unknown
```

但 Data Contract 的核心 lane 又主要定义：

```text
DEFAULT_FILE_DIFF
SUMMARY_ONLY
BINARY_METADATA_ONLY
```

配置文档还把 `.lib/.db/.spef/layout` 混合描述为 count-only、summary-only 或 metadata-only。([GitHub][13])

建议固定两个正交维度，不要混在一个枚举里：

```text
content capability:
  parsed
  summarized
  metadata
  unknown

review lane:
  focused_file_diff
  summary_review
  metadata_review
  blocked
```

例如 Liberty 可以是：

```text
content capability = summarized
review lane = summary_review
```

这样不会把 parser 能力、证据深度和 review 动作混为一谈。

## 6. Release 文档营造了比代码更强的安全感

文档说：

```text
rel 默认先 release-check，再生成规划
force 是显式绕过入口
```

但没有说明：

* 当前 Catalog check 即使 BLOCK 也返回成功；
* `--only-checked` 和 `--only-ready` 默认关闭；
* check 没有绑定之后生成的 manifest；
* raw version 与 current effective 可能不是同一对象。

因此这部分不是简单“少写参数”，而是文档描述的安全契约尚未由代码实现。

---

# 十、测试计划还没有锁住真正的业务闭环

测试计划明确说，禁止只测单个命令而不测联动；但它列出的手工 smoke 是：

```text
library list
next 预演
scan
cmp
cat
```

没有覆盖：

```text
next --apply
Version Review decision
rv gate
next --accept
rel check BLOCK
rel --apply
postcheck
effective rollback
```

所以当前测试计划没有要求完整验证：

```text
candidate
  → evidence ready
  → review approved
  → accepted effective
  → authorized release
  → applied
  → verified
```

也没有要求验证最重要的负向属性：

```text
Release Check = BLOCK
    → 必须零文件系统写入
```

([GitHub][14])

这不代表仓库中一定没有任何相关单元测试，但**测试计划作为产品流程契约，没有锁住端到端不变量**。

---

# 十一、建议重构成明确的状态机

当前比较像：

```text
Window
  → Candidate Manifest Exists
  → Accepted

Raw Catalog Version
  → Check Status Recorded
  → Linked
```

建议改成以下九态：

```text
REGISTERED
    ↓
CATALOGED
    ↓
WINDOW_PLANNED
    ↓
EVIDENCE_READY
    ↓
REVIEW_APPROVED
    ↓
EFFECTIVE_ACCEPTED
    ↓
RELEASE_AUTHORIZED
    ↓
RELEASE_APPLIED
    ↓
VERIFIED
```

## 每个状态的硬不变量

### `WINDOW_PLANNED`

```text
package type 已确认
base relation 已确认
candidate component list 已冻结
```

### `EVIDENCE_READY`

```text
plan == DONE
required scans fresh
effective manifest immutable
effective compare fresh
zero unresolved effective conflicts
```

### `REVIEW_APPROVED`

```text
review approval 绑定：
  candidate manifest hash
  compare hash
  policy hash
  reviewer
  timestamp
  owner note
```

### `EFFECTIVE_ACCEPTED`

```text
current pointer 通过 CAS 写入
accepted candidate hash == reviewed candidate hash
```

### `RELEASE_AUTHORIZED`

```text
release manifest 来自 accepted effective
release check == PASS/PASS_WITH_WARNING
authorization 绑定 release manifest hash
force 情况有完整 owner evidence
```

### `RELEASE_APPLIED`

```text
linker 消费同一个已授权 manifest
manifest hash 不匹配则拒绝
```

### `VERIFIED`

```text
expected files == actual files
hash/link target/source identity 均匹配
postcheck PASS
```

---

# 十二、修复优先级

## P0：先堵住可能发布错误内容的路径

### 1. 修正 Catalog release-check 退出码

```text
BLOCK/FAILED → 非零
PASS/PASS_WITH_WARNING → 0
```

### 2. Release batch 默认 fail-closed

删除“安全过滤需要用户显式开启”的语义：

```text
--only-checked
--only-ready
```

应该成为默认规则；只有 `--force` 能覆盖。

### 3. Release 默认从 current effective 生成

```text
current_effective.json
  → effective_manifest.json
  → release_manifest.json
```

不再默认从 `LIB VERSION` raw package 生成。

### 4. Accept 增加硬门禁

至少检查：

```text
plan DONE
compare fresh
review gate closed
candidate digest matches
base trusted
zero unresolved conflicts
current pointer revision unchanged
```

## P1：建立对象身份和新鲜度

### 5. 引入 manifest digest 绑定

```text
review approval
effective accept
release authorization
link result
postcheck
```

全部引用同一组 digest。

### 6. Plan 使用业务输入指纹

不能只 hash 命令字符串。

### 7. 将业务状态移出 HTML 树

将 window/effective/current pointer 放到 `$WORK/state`。

### 8. Accept 使用 CAS

避免并发 reviewer 最后写入者静默覆盖。

## P2：收敛 docs 和 UX

### 9. README 只保留 `next` 主路径

### 10. 自动验证所有文档命令

包括 action 文件语法。

### 11. 文档区分 implemented 与 proposed

### 12. 统一 evidence capability 和 review lane 术语

---

# 十三、必须补上的端到端测试

| 场景               | 操作                                 | 必须结果                                   |
| ---------------- | ---------------------------------- | -------------------------------------- |
| Release blocker  | checker 返回 BLOCK 后执行 `rel --apply` | 非零退出，release root 零变化                  |
| Manifest 变更      | Check manifest A，随后修改成 B           | apply 拒绝 hash mismatch                 |
| FIX effective    | FULL + FIX1 + FIX2 后发布             | manifest 包含完整 base、所有 overlay 和 delete |
| Raw FIX 误发布      | 尝试普通入口发布 FIX raw package           | 默认拒绝或要求专家 flag                         |
| Plan 未完成         | task 为 PENDING/FAILED 时 accept     | 拒绝                                     |
| Compare 缺失       | candidate 有 manifest 但 compare 不存在 | 拒绝 accept                              |
| Compare stale    | candidate 重建后复用旧 compare           | 拒绝 accept                              |
| Review Gate 打开   | blocking item 未关闭                  | 拒绝 accept 和 release                    |
| RAW 原地变化         | 相同路径内容变更后重跑 intake                 | scan task 失效并重跑                        |
| Policy 变化        | release/scan policy 内容改变           | 相关 evidence 和授权失效                      |
| 并发 accept        | 两人基于相同旧 pointer 接受不同 candidate     | 一个成功，另一个 CAS conflict                  |
| HTML 清理          | 删除/重建 catalog HTML                 | current effective 和 review state 不丢    |
| Pointer rollback | 回退 effective 后检查 release root      | 明确报告“未回退已部署 Release”                   |
| Action 示例        | 执行文档中的每条 action                    | parser 全部接受                            |
| Postcheck        | 修改一个 link target/hash              | VERIFIED 失败并精确报告文件                     |

最关键的测试应直接表达：

```python
assert release_check_status == "BLOCK"
assert exit_code != 0
assert filesystem_snapshot_before == filesystem_snapshot_after
```

---

# 十四、修复合入前的临时操作规程

在代码改成 fail-closed 之前，不建议把默认 `lg rel ... --apply` 当作受门禁保护的发布命令。

临时至少执行：

```bash
lg rel LIB VERSION --check-only
```

人工检查 JSON 中：

```text
release_check_status == PASS 或 PASS_WITH_WARNING
allowed_to_apply == true
blocking issue count == 0
review gate blocking_open == 0
```

之后先做 dry-run，并显式加：

```bash
lg rel LIB VERSION --only-checked --only-ready
```

FIX/HOTFIX 场景还必须检查生成的 Release manifest 是否包含完整 accepted effective 文件集合；不能假定 `rel LIB FIX_VERSION` 自动包含 FULL 和之前的 overlays。

Accept 前人工核对：

```text
current_plan.state == DONE
candidate manifest 是本次审查对象
effective compare 是最新的
Review Gate 无 blocker
candidate manifest hash 已记录
```

任何 RAW、policy、parser、package/base override 变化后，都不应继续相信旧计划的 command fingerprint，应显式重建相关 scan/compare evidence。

同时应把：

```text
catalog/html/libraries/*/effective
catalog/html/libraries/*/window
```

暂时视作需要备份和保护的业务状态目录，而不是普通可删除 HTML。

---

# 最终判断

目前 docs 已经把用户心智模型整理得比较好：

```text
next 预演
  → apply 生成证据
  → Version Detail 审查
  → accept effective
  → release
```

但源码中的真实控制链更接近：

```text
生成了 candidate
  ≠ 证据已完成
  ≠ 人工已批准
  ≠ 可以接受

接受了 effective
  ≠ Release 使用该 effective

Release Check 显示 BLOCK
  ≠ 控制流真的停止
```

因此，下一轮不应该继续优先打磨页面或增加更多状态文案，而应先建立两个不可绕过的绑定：

```text
Review Approval
  ↔ Candidate Effective Digest
```

以及：

```text
Release Authorization
  ↔ Accepted Effective Digest
  ↔ Release Manifest Digest
```

只有这两个绑定落地，`Version Detail → Accept → Release` 才是一条可证明、可复现、可审计的生产流程，而不是依赖用户严格遵守 SOP 的松耦合命令集合。

本轮是针对当前公开源码和文档的静态调用链审计，不代表完整测试套件或真实 RAW Library 场景已经执行通过。

[1]: https://github.com/Godshaohao/ai_lib/commits/main/ "https://github.com/Godshaohao/ai_lib/commits/main/"
[2]: https://raw.githubusercontent.com/Godshaohao/ai_lib/main/docs/basic_tutorial.md "https://raw.githubusercontent.com/Godshaohao/ai_lib/main/docs/basic_tutorial.md"
[3]: https://raw.githubusercontent.com/Godshaohao/ai_lib/main/src/lib_guard/short_cli.py "https://raw.githubusercontent.com/Godshaohao/ai_lib/main/src/lib_guard/short_cli.py"
[4]: https://github.com/Godshaohao/ai_lib/blob/main/src/lib_guard/release/checker.py "https://github.com/Godshaohao/ai_lib/blob/main/src/lib_guard/release/checker.py"
[5]: https://github.com/Godshaohao/ai_lib/blob/main/src/lib_guard/cli_commands/catalog.py "https://github.com/Godshaohao/ai_lib/blob/main/src/lib_guard/cli_commands/catalog.py"
[6]: https://github.com/Godshaohao/ai_lib/blob/main/src/lib_guard/release/linker.py "https://github.com/Godshaohao/ai_lib/blob/main/src/lib_guard/release/linker.py"
[7]: https://github.com/Godshaohao/ai_lib/blob/main/src/lib_guard/cli_commands/release.py "https://github.com/Godshaohao/ai_lib/blob/main/src/lib_guard/cli_commands/release.py"
[8]: https://raw.githubusercontent.com/Godshaohao/ai_lib/main/docs/data_contract.md "https://raw.githubusercontent.com/Godshaohao/ai_lib/main/docs/data_contract.md"
[9]: https://github.com/Godshaohao/ai_lib/blob/main/src/lib_guard/short_cli.py "https://github.com/Godshaohao/ai_lib/blob/main/src/lib_guard/short_cli.py"
[10]: https://github.com/Godshaohao/ai_lib/blob/main/src/lib_guard/window/cli.py "https://github.com/Godshaohao/ai_lib/blob/main/src/lib_guard/window/cli.py"
[11]: https://github.com/Godshaohao/ai_lib/blob/main/src/lib_guard/plan/engine.py "https://github.com/Godshaohao/ai_lib/blob/main/src/lib_guard/plan/engine.py"
[12]: https://raw.githubusercontent.com/Godshaohao/ai_lib/main/README.md "https://raw.githubusercontent.com/Godshaohao/ai_lib/main/README.md"
[13]: https://raw.githubusercontent.com/Godshaohao/ai_lib/main/docs/scan_evidence_review.md "https://raw.githubusercontent.com/Godshaohao/ai_lib/main/docs/scan_evidence_review.md"
[14]: https://raw.githubusercontent.com/Godshaohao/ai_lib/main/docs/test_plan.md "https://raw.githubusercontent.com/Godshaohao/ai_lib/main/docs/test_plan.md"
