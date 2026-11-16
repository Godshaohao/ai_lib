> 目前为开发中的本地工作台；扫描、交付登记与检查自动编排尚未形成完整闭环。快速扫描使用文件大小和修改时间，不证明内容一致。请勿将模拟报告视为生产验收。

可复现模拟数据：在本目录设置 `PYTHONPATH=src` 后运行 `python3 examples/overall_demo/build_demo.py`；多供应商样例可运行 `python3 examples/build_scale_synthetic.py examples/scale_synthetic_v1`，目标目录须不存在。运行产物不纳入仓库。

# ai_lib_qor · Vendor/Library/IP/Version 统一目录与 JSON 契约 v3.0

**这是面向 Codex 与人工字段确认的完整设计示例，并非已运行生产系统的文件。**

## 从哪里读起

1. `docs/01_文件架构与JSON契约.md`：统一目录、四类业务记录 + 三类支撑、**逐字段定义**、增量逻辑、单文件/Macro 历史、旧流程迁移映射。
2. `docs/02_每份JSON内容审查.md`：13 份具体示例逐文件审查（**12 JSON + 1 JSONL**），说明之前的重复数据如何合并。
3. `docs/03_中英文专业名词附录.md`：中英文名称、业务 UI 说法、技术 ID 统一规则。
4. `docs/04_所有示例JSON完整正文.md`：13 份 JSON/JSONL 的全文（不省略）。
5. `docs/05_逐字段确认表.csv`：116 个逐字段核对项，Excel 可直接打开，末两列留给人工审查。
6. `docs/06_Codex迁移与增量实现.md`：从旧产物映射为 v3.0 的最小迭代路线。
7. `examples/`：与 Vendor → Library → BusinessIP → Version 对应的真实目录结构的**合成实例**。
8. `schemas/`：7 个 JSON Schema（包括 JSONL 的单行事件 Schema）。
9. `tools/validate_examples.py` 和 `docs/validation_results.json`：Schema、跨记录校验、故意篡改测试。

## 术语统一

- `delivery.json`：供应商一次交付有哪些文件。
- `snap_0001.json`：正式 NL 在某个时刻实际链接哪些文件。
- `rev_0002.json`：IP 的某个完整有效文件组合，与上一 Rev 的采用差异。
- `run_001.json`：针对交付或某个 Rev 的检查结果，包含文件、Macro、Pin 的变化事实和质量规则结果。
- `file_facts/`：复用现有 LEF/Liberty Parser 结果。
- `effective/index.json`：最新计算和已采纳 Rev 的两个入口。
- `acceptance.jsonl`：仅在实际发生采纳/回退时追加记录。

## 核心不变式

1. `DeliveryRecord`、`FormalSnapshot`、`EffectiveVersion` 是不可变历史。
2. `EffectiveVersion.members` 是当前 Rev 的**全集**，`changes` 是**相对父 Rev 的采用差异**；两个字段必须自动验证一致。
3. `source_ref` 指向固定的交付行或正式快照行；不指向 `latest.json`。
4. 单文件来源变化、解析内容变化、工程检查通过、人工采纳是四件不同的事情。
5. 增量更新只处理变化文件与依赖它们的检查，其他旧事实原样复用。

## 如何验证示例

在安装了 Python `jsonschema` 的开发环境下执行：

```bash
python tools/validate_examples.py
```

演示数据、路径、名称和检查数值均为虚构，不能当成真实库管理分析结论。

验证器还包含 **16 个故意出错样例**（坏来源、重复成员、假 Macro SIZE、假 Pin PRESENCE、假 Pin Match PASS 等）和 **2 个内存边界场景**（RAW-only、跨 SourceLibrary），它们不是新增的持久 JSON 类型。
