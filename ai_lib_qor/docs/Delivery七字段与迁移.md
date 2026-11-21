# Delivery 七字段结构

新扫描和显式登记在 `work/libraries/<vendor>/<library>/delivery_NNN.json` 写入七个字段：`vendor`、`library`、`version`、`version_date`、`directory_created_at`、`root`、`views`。`views` 的值是按类型分类的版本根目录相对路径数组。`.sp` 和 `.spice` 在新清单中归为 `SPICE`；其他类型沿用已识别 View，未知文件仍保留。

`version_date` 只从版本名称开头可解析的 `YYYYMMDD` 提取，无法提取为 null；它是查询字段而不是第二个版本身份。新扫描仅在系统提供文件系统 Birth Time 时记录带时区的 `directory_created_at`，否则为 null；不使用 ctime、mtime 或登记时间代替。旧记录迁移时没有记录实际创建时间，因此保持 null。版本排序仍遵循已有配置：优先版本日期，缺失时使用用户登记的交付时间，不使用目录创建时间冒充交付顺序。

## 历史引用与迁移

已归档 Effective、Formal、Facts 和报告仍引用旧交付及文件标识。`evidence_delivery_NNN.json` 中的 `legacy_compatibility` 保存这些既有映射及必要的扫描元信息；它不是第二份 Delivery 文件。查询层将两个文件组合为旧消费者使用的内存记录，不从文件名猜测身份。移动或删除证据文件会使引用无法安全解析，系统会阻止自动登记；请保留同库的这对文件。

已明确授权的旧库迁移：

```bash
PYTHONPATH=src:../src python3 -m ai_lib_qor delivery-simplify \
  --work work --vendor SRAM22 --library sram22_256x16m8w8
```

迁移逐库加锁，先校验该库全部记录和可逆性，再先写来源映射、原子替换旧 Delivery。重复执行不再改写；旧 Delivery 本体不另存副本，保留原文件名及现有 latest 软链接。迁移不是全库事务，执行失败应先检查返回错误；扫描和索引的已有安全检查仍然有效。

本次覆盖工作目录内按当前布局登记的 `delivery_NNN.json`；`archive/`、`exports/`、契约示例和独立历史备份不是当前工作目录，不作为本次删除或迁移范围。老式独立 `build-delivery` 命令仍产生原始契约，用于兼容旧工作流，不等同于新扫描结果。
