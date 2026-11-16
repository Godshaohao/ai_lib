# project.yaml · 配置设计（示意，不是生产配置）

```yaml
project:
  id: ai_lib_qor
paths:
  work_root: /example/qor/work
  # reports_root: /example/qor/reports
sources:
  vendors:
    vendor_a:
      libraries:
        library_x:
          raw_root: /example/raw/vendor_a/library_x
  formal_nl:
    NL2.5.3:
      root: /example/formal/NL2.5.3
```

`work_root` 优先级：CLI `--work-root` > `AI_LIB_QOR_WORK_ROOT` > YAML。`reports_root` 不配置时为 `<work_root>/reports`。输入路径只读；检查规范化、链接解析后的根目录关系及可访问性。路径均为示意，实际输入/输出不得危险重叠。
