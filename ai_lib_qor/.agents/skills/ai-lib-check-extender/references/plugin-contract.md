# 插件契约与扩展参考（`checks/plugins/` & `plugin_modules`）

## 1. 插件函数签名与 `ctx` 上下文字典

所有检查插件均为纯函数：`def run_<name>(ctx: dict) -> dict`

`minimal_checks.py` 注入的 `ctx` 字段：

| Key | 类型 | 说明 |
| --- | --- | --- |
| `work` | `str \| Path` | 当前工作区根目录（仅允许只读读取配置/验收表，严禁写入或越界） |
| `vendor` | `str` | 供应商名称 |
| `library` | `str` | 物理来源库名称 |
| `business_ip` | `str \| None` | 多轨库当前业务 IP；单轨库为 `None` |
| `ip_type` | `str \| None` | 配置的 IP 类型（单轨库与多轨库均已透传） |
| `track_id` | `str \| None` | 多轨格式 `vendor/library::business_ip` |
| `revision` | `str` | 目标有效版本（如 `rev_0003`） |
| `baseline_revision` | `str \| None` | 对比基线版本；无基线或 `__none__` 时为 `None` |
| `target` | `dict[(view, rel_path), {'version', 'path'}]` | 目标有效版本的**全量成员路径字典**（清单级插件核心输入） |
| `baseline` | `dict[(view, rel_path), {'version', 'path'}]` | 基线版本对应成员映射 |
| `facts` | `dict[(view, rel_path), (Path, dict)]` | 本次已解析的 FileFacts（受 `skip_parse_views` 与 `liberty_parse_filter` 影响） |
| `obtain` | `callable(view, path, source) -> (Path, dict)` | 按需从内容寻址共享池读取/解析指定文件（仅限 `needs_facts=True` 插件使用） |
| `plugin_params` | `dict[str, dict]` | 已按「全局 → `ip_type` → 单库」三层合并后的参数表；读取方式：`ctx.get('plugin_params', {}).get('MY_PLUGIN') or {}` |
| `explicit_plugins` | `bool` | 用户是否显式指定了 `--plugins`（用于区分自动跳过 `NOT_APPLICABLE` 与显式要求执行） |

## 2. 返回值与 `CheckResult` Schema 约束

插件返回字典允许包含以下键（未产生项可省略或留空列表）：
- `checks`: `list[dict]` — 规则判定项
- `comparisons`: `list[dict]` — 完整内容级跨版对比项
- `partial_comparisons`: `list[dict]` — 轻量部分跨版对比项
- `changes`: `list[dict]` — 结构变更明细

每条 `checks[i]` 必须满足 `schemas/check_result_path.schema.json`：
```python
{
    'check_id': 'MY_RULE_ID',           # 必填，与注册名一致
    'scope_file_keys': ['LIB/a.lib'],   # 必填，相关相对路径列表（可为空）
    'result': 'PASS',                   # 必填：'PASS' | 'FAIL' | 'INCONCLUSIVE'
    'severity': 'INFO',                 # 可选：'ERROR' | 'WARNING' | 'INFO'
    'coverage': 'MANIFEST',             # 必填：'COMPLETE' | 'PARTIAL' | 'MANIFEST' | 'UNKNOWN'
    'facts_refs': [],                   # 必填：关联的 FileFacts 文件名列表（清单级为空）
    'detail': '可读的中文结论与边界说明', # 必填
    'findings': [                       # 可选，供 UI/Excel/Agent 精确定位问题
        {
            'view': 'DB',
            'path': 'LIB/a.lib',
            'object_type': 'LIB_DB_PAIR',
            'object_name': 'a.lib',
            'diff_type': 'MISSING_DB',
            'old_value': None,
            'new_value': None,
            'detail': '缺少对应 .db 文件',
        }
    ],
}
```

## 3. 注册元数据规范

调用 `register_path_plugin(...)`（或写入 `PATH_CHECK_PLUGIN_META`）时应完整声明：
- `version`: 语义版本字符串（规则逻辑有实质变化时递增，例如 `'1.0'` → `'1.1'`，`check_tooling_status` 会自动识别旧报告为 `STALE_TOOLING`）
- `description`: 简明中文描述（直接展示在「单库配置」抽屉与报告摘要中）
- `required_views`: 元组，如 `('LIBERTY', 'DB')`
- `requires_baseline`: 是否依赖对比基线（Diff 插件为 `True`）
- `needs_facts`: 清单级插件务必设为 `False`（不被 `skip_parse_views` 阻断）
- `category`: `'MANIFEST'` | `'FACTS'` | `'DIFF'`

## 4. 三层插件启停与参数配置（零代码切换）

在 `work/path_sources.json` 中支持三层继承（后者覆盖前者）：
1. 全局：`check_plugins` / `check_plugin_params`
2. 按 `ip_type`：`check_plugins_by_ip_type.<IP_TYPE>` / `check_plugin_params_by_ip_type.<IP_TYPE>`
3. 单库：`libraries.<vendor>.<library>.check_plugins` / `libraries.<vendor>.<library>.check_plugin_params`

也可在 Web 库详情页点击「单库配置」抽屉直接查看和编辑启停策略。

## 5. 外部插件挂载（零改动主仓库）

项目/工艺专属插件无需放进 `src/ai_lib_qor/`：
1. 在独立目录编写模块（如 `company_qor_rules/gds_layer_check.py`），文件末尾调用 `register_path_plugin('GDS_LAYER_CHECK', run_gds_layer_check, ...)`。
2. 在 `work/path_sources.json` 配置 `"plugin_modules": ["company_qor_rules.gds_layer_check"]`（或设置环境变量 `AI_LIB_QOR_PLUGIN_MODULES`）。
3. CLI 与 Web 工作台启动时自动装载。
