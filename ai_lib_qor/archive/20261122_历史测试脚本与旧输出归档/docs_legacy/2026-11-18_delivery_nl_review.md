# Delivery 与 Formal NL 数据构建审查

## 结论和范围

**当前结果可用于来源盘点，但尚不能称为完成了可靠的业务分类和 NL 快照构建。** Schema 验证、路径匹配、文件位归属、IP 归属和内容/质量检查是不同层次。

本次核对 2026-11-18 本地代码；对 `exports/catalog_actual_xl494asj/work` 的 10 份实际公开样本 DeliveryRecord 逐份验证 Schema、路径、文件 ID、文件位及其扫描证据。另在临时目录对本机公开 IHP、SRAM22 的 5 个来源库重新扫描登记，并以它们的 21 份交付与本机 `lib_NL2.5_3` 的链接进行只读对应测试。临时试验未修改 RAW、Formal 或正式业务历史。样本是公开测试数据，不代表全部真实供应商已验收。

## 验证结果

| 来源库 | 版本/交付 | 文件行 | RESOLVED | UNRESOLVED | 所有 RESOLVED 的依据 |
| --- | ---: | ---: | ---: | ---: | --- |
| IHP / sg13g2_stdcell | 5 | 56 | 40 | 16 | 文件名唯一候选 |
| IHP / RM_IHPSG13_1P_64x16_c2 | 1 | 7 | 4 | 3 | 文件名唯一候选 |
| SRAM22 / sram22_256x16m8w8 | 5 | 39 | 20 | 19 | 文件名唯一候选 |
| SRAM22 / sram22_512x32m4w8 | 5 | 40 | 20 | 20 | 文件名唯一候选 |
| SRAM22 / sram22_1024x32m8w8 | 5 | 40 | 20 | 20 | 文件名唯一候选 |
| 合计 | 21 | 182 | 104 | 78 | 104 条均非显式映射 |

持久保存的前两库 10 份 DeliveryRecord 均通过当前设计 Schema；95 个文件路径均存在，记录与 `source_evidence.json` 的路径集合一致，文件 ID 和非空文件位在各交付内无重复。10 份的 `package_mode=UNKNOWN`、`scope_confirmed=false`，不能作为完整交付或删除的证据。

两个现有记录示例：[IHP Delivery](../exports/catalog_actual_xl494asj/work/vendors/IHP/libraries/sg13g2_stdcell/deliveries/delivery_2ad508bc0a284555b6f3732138287fc7/delivery.json)、[SRAM22 Delivery](../exports/catalog_actual_xl494asj/work/vendors/SRAM22/libraries/sram22_256x16m8w8/deliveries/delivery_26f64ba4375c454bbd93428bcc1ac875/delivery.json)。相邻 `source_evidence.json` 保存分类依据。

| Formal NL 隔离试验 | 观察结果 |
| --- | --- |
| 只提供前述两库交付 | 39 个链接正常；18 个路径匹配 RAW，其中仅 12 个有文件位；另外 21 个来源未知；未发布快照。 |
| 纳入 NL 覆盖的 5 个来源库 | 39 个链接均正常且路径均匹配 RAW；其中 24 个有文件位、15 个无文件位；仍未发布快照。 |
| 直接调用快照 builder，在内存构造包含全部观察的部分覆盖候选 | 39 条中 `MATCHED_RAW=12`、`UNMATCHED=27`，`coverage=PARTIAL`；仅用于核验底层能力，未发布此候选。 |

最后一行使用的是**两库交付**对应的 39 条观察，因而与五库路径匹配的 39 条不能直接比较；builder 在文件位为空或未确认时不能输出匹配的 `source_ref`。

## 主要发现

### P1：文件名推断被标为 RESOLVED，且可进入有效版本

`classifier_adapter.py` 使用文件名与路径生成 `filename_unique_candidate`，随后只要存在文件位就设置 `RESOLVED`。样本中 104 条 `RESOLVED` 全部属于这种推断，并非人工映射。`source_evidence.json` 保留了依据，但 DeliveryRecord 自身只有 `classification`。Web 创建有效版本时自动选择 `RESOLVED` 文件位。因此当前“已识别”与“业务确认”在流转中容易混淆，尤其对跨版本重命名、相同文件名或 IP 归属不能单凭推断确权。

代码：[classifier_adapter.py](../src/ai_lib_qor/sources/classifier_adapter.py)、[auto_ingest.py](../src/ai_lib_qor/sources/auto_ingest.py)、[workbench/app.py](../src/ai_lib_qor/workbench/app.py)。

### P1：正式链接观察成功，但自动快照全局发布条件过严

`sync_formal()` 要求观察中所有文件都能对应非空且全局不重复的文件位，才进入快照生成。实际五库试验中，15 条 GDS/CDL/SPICE/Verilog 无文件位，导致 39 条链接全部观察完成且路径都可匹配 RAW，仍然没有 `snapshot.json`。这不是说应把未知项伪装成已确认；应明确区分观察、部分快照与完整覆盖，并按 v3 契约和范围规则处理。

代码：[formal_sync.py](../src/ai_lib_qor/sources/formal_sync.py)、[snapshot_builder.py](../src/ai_lib_qor/sources/snapshot_builder.py)。

### P1：无快照时，首页未展示已经观察到的来源分类

隔离试验的 Formal 观察有 39 条 `MATCHED_RAW`，但 `LibraryCatalog.overview()` 的分组从快照推导；因为没有生成快照，首页显示 **0 组**。页面同时显示观察已完成和“没有满足发布条件”，仍会让用户难以查找已匹配来源。需分别展示“最近观察分类”和“已发布快照分类”，不能把观察直接当快照。

代码：[library_catalog.py](../src/ai_lib_qor/application/library_catalog.py)、[global_overview.html](../src/ai_lib_qor/workbench/templates/global_overview.html)。

### P2：View 有分类，文件位和角信息不完整

自动文件位规则只对 LEF/Liberty 推断；样本中的 GDS、CDL/SPICE、Verilog 均是 `UNRESOLVED`，不能据此说文件不存在。IHP 两库的 33 条 Liberty 的 `corner` 均为空：如 `fast_1p32V_m40C.lib` 的电压、温度仅作为 `corner_hint` 留在旁证，`fast/slow/typ` 未成为 `corner`。SRAM 三库 45 条 Liberty 有 `ff/ss/tt` 的 process 值，但电压未进入 `corner`。所有 78 条 Liberty 的 `mode` 都为空；是否适用、应如何表示需根据库约定确认，不能凭空补齐。此处的分类只是目录/文件名元数据，不是解析文件内容的结论。

### P2：FormalSnapshot 本身不包含完整的展示分类

`linked_files` 保存 `file_key`、链接路径和 RAW 来源引用，不直接包含 Vendor、IP、View、Corner；自动构建的 `scope.views` 目前为空。Vendor/View 等可以在来源引用唯一且有对应 Delivery 时经查询层关联，IP 还需要有可信业务归属。没有关联依据时应显示未知，不能按路径猜测。形式上的 Schema 合法不证明分类完整。

### P2：历史补录可能被当作最新交付顺序

未显式配置顺序时，新增交付使用当前最大 `delivery_order + 1`。如果先登记新版本，之后才发现旧版本，旧版本会获得更大的登记顺序。文件矩阵按这个顺序显示最新/次新；它代表已记录的交付/登记顺序，不能保证是供应商版本的时间顺序。需要显式顺序来源，或在 UI 标记顺序依据和不确定性，不应改写已有历史来伪造顺序。

代码：[auto_ingest.py](../src/ai_lib_qor/sources/auto_ingest.py)、[catalog.py](../src/ai_lib_qor/application/catalog.py)。

## 示例快照和限制

`examples/work`、`examples/legacy_scale_demo/work` 和 `examples/overall_demo/dataset/work` 各有两份示例快照，均通过 Schema，示例每份只有 3 个链接；它们不是本次 39 条公开 NL 链接的正式快照。未对文件内容做 SHA-256 等完整性比较，也未核验真实项目生产数据、全部 Corner 语义或业务 IP 归属。

## 建议整改顺序

1. 明确 `自动候选 / 显式映射 / 已确认` 的 UI 和流转边界；候选可盘点，进入有效版本前保留明确选择及依据，避免篡改既有历史。
2. 为 GDS、CDL/SPICE、Verilog 等建立可审查的文件位映射途径，并补充每库 Corner/Mode 规则与未知状态。
3. 设计并验证部分 NL 快照如何保存未知来源、覆盖范围和链接证据；不要把未确认项当成匹配成功，也不要让一个未知项使所有已知来源不可查询。
4. 首页分离观察分类和已发布快照；展示匹配、未知、歧义和未发布原因。
5. 明确交付排序依据和历史补录规则；对现有结果先审计、保持历史不可变。
