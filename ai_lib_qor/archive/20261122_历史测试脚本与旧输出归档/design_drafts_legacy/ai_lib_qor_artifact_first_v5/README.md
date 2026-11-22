# ai_lib_qor 七类契约 · 多脚本汇总产物架构 v5

这是基于用户已确认的 7 类 JSON 契约重新设计的**讨论/验证包**，不是另起一套生产 JSON。

- `docs/Architecture_Artifact_First_v5.md`：完整分析、七类产物、脚本职责、运行/增量发布策略、源码结构、旧脚本映射和验收。
- `diagrams/01_seven_products.*`：输入→7 类 JSON→Web/HTML/Excel。
- `diagrams/02_multi_scripts_one_json.*`：多个独立检查插件合并到一个 Run JSON。
- `diagrams/03_one_file_multiple_parsers.*`：同一文件实例的多个提取器合并到一个 FileFacts。
- `diagrams/04_incremental_generations.*`：追加新检查/修改参数时复用结果，历史不可变。
- `diagrams/05_script_to_products.*`：旧脚本可提取能力→新的单 Writer→七类产物。
- `tools/assemble_checks.py`：可执行的一份检查结果汇总示例。
- `tools/test_assembly.py`：测试双 Run 聚合、错误输入/重复贡献/误判/不可变。
- `examples/plugin_fragments/*.json`：插件的**临时贡献片段**，不是第 8 类权威 JSON。
- `examples/published_runs/*.json`：单一统一 Check Run 的最终示例。

运行：

```bash
python tools/assemble_checks.py
(cd tools && python -m unittest test_assembly -v)
```

当前演示基于合成数据，未连接真实企业 RAW/正式 NL/EDA。
