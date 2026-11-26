# EDA 脚本模板适配与扩展指南（`reporting/eda_scripts.py`）

## 1. 模板发现与优先级

- **工作区覆写 / 私有模板（推荐，0 源码改动）**：`<work>/script_templates/<template_name>.csh.j2`（或 `.csh`）
- **内置通用模板**：`src/ai_lib_qor/reporting/script_templates/<template_name>.csh.j2`
  - 已内置：`pt_check`（PrimeTime）、`innovus_check`（Innovus）

当工作区目录存在同名文件时，自动覆写内置模板；新增不同名文件（如 `tempus_check.csh.j2`、`calibre_drc.csh.j2`）会被 `list_script_templates(work)`、`export-script --template <name>` 和 `GET /api/v1/scripts/export?template=<name>` 自动识别。

## 2. 模板可用变量（Jinja2 `StrictUndefined`）

| 变量名 | 类型 | 说明 |
| --- | --- | --- |
| `vendor` / `library` | `str` | 供应商与库名 |
| `business_ip` / `ip_type` | `str \| None` | 多轨当前业务 IP 与 IP 类型 |
| `revision` | `str` | 当前有效版本（如 `rev_0003`） |
| `generated_at` | `str` | UTC 生成时间 |
| `template` / `template_source` | `str` | 模板名与来源标识 |
| `output_dir` | `str` | 建议运行输出目录 |
| `deliveries_used` | `list[str]` | 本有效版本引用到的交付版本列表（用于溯源） |
| `lef_files` / `db_files` / `lib_files` | `list[dict]` | 按 View 分类的有效成员，每项含 `view`、`path`（相对路径）、`version`、`absolute_path` |
| `verilog_files` / `gds_files` / `cdl_files` | `list[dict]` | 其他常见 View 成员列表 |
| `members_by_view` | `dict[str, list[dict]]` | 全部 View（含扩展自定义 View）的成员字典 |
| `members` | `list[dict]` | 全部有效版本成员平铺列表 |
| `counts` | `dict[str, int]` | `LEF` / `DB` / `LIBERTY` / `VERILOG` / `GDS` / `CDL` / `TOTAL` 计数 |

## 3. 适配用户真实脚本的 5 个注意项

1. **只替换文件列表与元数据，尽量保留用户原命令流**：不要擅自重写用户的 `pt_shell` / `innovus` / `bsub` 选项或 Tcl 检查逻辑。
2. **保护 Tcl 花括号**：单层 `{` / `}` 与 Jinja2 无冲突；若原脚本出现 `{{`、`}}`、`{%`、`%}`，必须用 `{% raw %}...{% endraw %}` 包裹，否则 Jinja2 会报错。
3. **空 View 防护**：在模板中用 `{% if not db_files %}` / `if {[llength $db_files] == 0}` 给出明确提示与非零退出码，防止工具空跑。
4. **可执行权限与输出路径**：`export_eda_script` 原子落盘并自动赋予 `0o755`；脚本内部避免写死绝对临时目录，优先使用 `setenv RUN_DIR "{{ output_dir }}"`。
5. **需要 Web 按钮快捷入口时**：仅当某模板成为高频内置通用工具时，才在 `BUILTIN_TEMPLATE_META` 与 `path_library.html` TAB 2 工具栏补充快捷按钮；其余模板通过 `/api/v1/scripts/export?template=<name>&download=1` 与 CLI `export-script --template <name>` 即可零改动调用。
