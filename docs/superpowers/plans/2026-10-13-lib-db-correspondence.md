Status: current

# Liberty / DB 人工配套清单

目标：列出实际对应情况，由用户判断，不自动阻塞。输入仅为扫描文件清单；不解析 DB、不计算额外 hash、不猜测命名规则、不新增发布要求。

- [x] 测试同名两侧均有、仅 Liberty、仅 DB、同名多文件；gzip 和 NDM 边界；不改变扫描状态或 issues。
- [x] 在现有 integrity 中记录配套清单；Markdown 摘要和扫描 HTML 展示绝对路径。
- [x] 工作台文件结构中复用已有扫描清单，支持对应情况/路径筛选和分页；旧扫描无需重扫。
- [x] 全量回归、真实扫描模拟、浏览器展示和截图。

验收：796 项 unittest 通过（12.772 秒）；JS 语法、compileall、git diff --check 通过。日志 /tmp/lib_db_verified.log。
真实文件模拟：2 个 Liberty + 1 个 DB；扫描 PASS、issues 空、额外 hash 为 0。macro_a 两侧均有，macro_b 仅 Liberty；Markdown、扫描 HTML 与 Web 来源一致。删除旧 integrity 后仍可直接从扫描清单展示。
浏览器实际展开清单、筛选“仅 Liberty”得到 1 组、恢复全部得到 2 组；无控制台错误。截图 /tmp/ai_lib_lib_db_correspondence_20261013.png。
服务：模拟 5068，真实工作台 5067。未修改真实原始库、有效组合或发布链接。

范围：scan/artifacts.py、evidence_export.py、render/html_report.py、Web read_model 与模板/JS/CSS；不改分类器、解析器、scan/diff 算法、发布或有效库门禁。
展示范围：Web 每页 100 组；扫描 HTML 前 200 组，完整清单在已有 review/scan_review.md，不再新增散落报告。
