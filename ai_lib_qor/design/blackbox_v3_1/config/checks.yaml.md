# checks.yaml · 注册与方案（示意，不是生产配置）

```yaml
plugins:
  CONTENT_COMPARE:
    entry: ai_lib_qor.checks.plugins.content_compare:run
  LEF_MACRO_DIFF:
    entry: ai_lib_qor.checks.plugins.lef_macro_diff:run
  LEF_LIBERTY_PIN_MATCH:
    entry: ai_lib_qor.checks.plugins.lef_liberty_pin_match:run
profiles:
  delivery_intake:
    - id: CONTENT_COMPARE
      enabled: true
      input_selector: raw_latest_vs_previous_same_file
      params: {}
    - id: LEF_MACRO_DIFF
      enabled: true
      input_selector: raw_latest_vs_previous_same_file
      params:
        attributes: [SIZE, PIN_NAME, PIN_DIRECTION]
    - id: LEF_LIBERTY_PIN_MATCH
      enabled: false
      input_selector: one_lef_with_related_liberty
      params:
        compare: [pin_name, direction]
  effective_revision:
    - id: LEF_MACRO_DIFF
      enabled: true
      input_selector: changed_lef_vs_parent
      params:
        attributes: [SIZE, PIN_NAME, PIN_DIRECTION]
    - id: LEF_LIBERTY_PIN_MATCH
      enabled: true
      input_selector: one_lef_with_related_liberty
      params:
        compare: [pin_name, direction]
```

入口路径只是拟议模块；只允许注册已安装、可信的本地插件。新插件实现 `PLUGIN_ID`、`PLUGIN_VERSION`、`run(context, params)`，配置选择场景；对于 v3 无法表达的新增输出，仍需先处理契约缺口，不能保证永远无需改动汇总器。
