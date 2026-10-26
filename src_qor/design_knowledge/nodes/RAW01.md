+++
id = "RAW01"
title = "RAW 库发现与登记"
type = "source"
status = "unknown"
origin = "../lib_guard/raw_discovery.py"
summary = "从配置的 RAW 根目录发现 Vendor、IP、版本及可识别视图，并将登记信息写入工作台清单。"

[[links]]
to = "IP_OBJECT01"
relation = "organizes"

[[links]]
to = "REVIEW_PIPE01"
relation = "supports"
+++

## 代码可见事实
- 发现实现位于 `src_qor/lib_guard/raw_discovery.py`，Web 入口位于 `src_qor/lib_guard/workbench.py`。
- RAW 文件由来源路径引用；登记/刷新更新 IP 清单，不等同于复制原始库文件。
- 布局存在多种形态，具体识别规则应以发现器和回归测试为准，不从目录名外推未实现语义。

## 待核实
- 真实供应商交付是否覆盖所有目标布局、权限边界和异常符号链接场景。
- RAW 历史目录是否在组织流程中保持不可变；代码扫描本身不能保证源内容不可变。
