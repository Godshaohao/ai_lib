# PD Vibe Guard Skill Pack

面向 PD 内部工具、dashboard、HTML review、库管理、FCT QoR、Release Monitor、Tile Timing 等场景的轻量 AI 编程约束包。

它不是完整项目管理流程，也不是平台化规范。它的目标是：

> 在 vibe coding 前，把“想做的东西”压缩成“值得做、能交付、不会被 AI 过度扩展的最小工程动作”。

## 解决的问题

本包针对四类高频工程损耗：

1. 需求过度：从一个结果页滑向平台、状态机、多角色、agent workflow。
2. 架构过度：从一个脚本滑向复杂模块、数据库、缓存、配置中心。
3. 算法过度：从规则/排序滑向自动归因、聚类、评分、预测。
4. 代码过度：AI 顺手补抽象、兼容、异常、未使用配置、无关重构。

## 核心第一性原理

PD 内部工具的价值不在于系统完整，而在于：

> 让一个具体角色，在一个具体场景下，更快完成一个具体判断或动作。

任何需求、架构、算法、代码，都必须服务这个目标。

## Skill 组成

```text
skills/
  requirement_grill/         # 拷打需求：谁用、场景、主判断、数据、动作
  requirement_ponytail/      # 砍需求：KEEP / CUT / DEFER
  architecture_grill/        # 拷打架构：状态机/数据库/多页面/配置中心是否必要
  algorithm_grill/           # 拷打算法：归因/聚类/评分/预测是否必要
  implementation_ponytail/   # 砍代码：拒绝防御性代码、抽象膨胀、未使用配置
  pd_vibe_guard/             # 总控 Skill：按任务类型调用上述 Skill

templates/
  task_header.md             # 每次任务开头 5 行约束
  ai_coding_contract.md      # 给 Codex/Claude/Cursor 的最小实现合同
  review_output_format.md    # 对抗审查输出格式

checklists/
  p0_gate.md                 # P0 是否成立
  anti_overengineering.md    # 过度设计检查
  ai_diff_review.md          # AI 代码 diff 审查

examples/
  fct_qor_dashboard.md
  lib_guard.md
  release_monitor.md
  tile_timing_detail.md

AGENTS.md                    # 项目长期负约束
```

## 推荐使用顺序

```text
需求进入前：Requirement Grill
需求判定：Requirement Ponytail -> KEEP / CUT / DEFER
涉及结构变化：Architecture Grill
涉及识别/聚类/归因/评分：Algorithm Grill
进入代码：Implementation Ponytail
长期约束：AGENTS.md 负约束
```

最短表达：

```text
先拷打需求，再砍需求。
再拷打架构/算法，最后砍代码。
```

## 每次任务只需要 5 行任务头

不要一开始写复杂 yaml。每次任务先写：

```text
目标用户：
主判断：
允许输入：
允许输出：
禁止扩展：
```

示例：

```text
目标用户：group leader
主判断：当前 run 哪个 group/corner 的 setup/hold 变差
允许输入：data/fct_qor_input.csv
允许输出：reports/index.html
禁止扩展：状态机、多角色、数据库、agent、root cause 自动归因、全 corner 趋势化
```

## 适用场景

- FCT QoR 趋势页
- Tile Timing Detail / Issue Cluster 页面
- Release Monitor
- Library Guard / catalog / scan / diff / release
- 单文件 HTML review
- PD 内部自动化脚本
- AI 辅助修改已有代码

## 不适用场景

- 已经明确进入平台化阶段的大项目
- 安全/合规要求非常严格的正式生产系统
- 必须完整覆盖所有异常的 signoff critical flow
- 需求尚未有任何目标用户和使用场景的幻想型项目

## 核心判断

一个需求能不能进入代码，不看它是否合理，而看：

```text
它是否直接降低了当前目标用户的判断成本或行动成本。
```

一个实现能不能接受，不看它是否完整，而看：

```text
它是否用最少代码完成当前合同，且没有引入未来扩展负债。
```
