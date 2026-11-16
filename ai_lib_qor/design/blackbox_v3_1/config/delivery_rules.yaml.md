# delivery_rules.yaml · 交付规则设计

库管理员维护唯一 `delivery_id`、同库已确认的 `delivery_order`、包模式和范围确认、显式删除声明与文件分类规则。`supplier_version` 可以重复，不能当事件唯一标识。`INCREMENTAL` 中未出现不表示移除；`FULL` 和 `PATCH` 的覆盖、删除语义需要具体规则，不能从文件缺失推断。具体 YAML 字段待人工确认。
