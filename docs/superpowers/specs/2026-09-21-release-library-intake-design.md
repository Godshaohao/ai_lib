Status: current

# 正式发布库接入设计

## 目标

让库管理员输入一个正式发布根目录后，系统能读取目录中已有的发布清单，将其中的多个发布库作为可查询的“正式发布库”展示；同一库再次发布时支持受控覆盖预演与历史保留。

## 非目标

- 不把发布目录当作 RAW，不对它运行候选发现、扫描或版本对比。
- 不从 Web 直接执行真实发布或覆盖。
- 不复制 scan、diff、Catalog 或有效组合事实。
- 不引入数据库或常驻服务。

## 事实边界

| 事实 | 唯一来源 | 读写者 |
| --- | --- | --- |
| 原始库、版本和扫描 | `catalog.json`、scan/diff 证据 | 既有库管理和扫描流程 |
| 正式发布结果 | `release_manifest.json`、`release_result.json`、链接目录 | Release CLI |
| 发布库目录快照 | `config/release_libraries/latest.json` | 新的发布库读取器 |
| Web 页面 | 上述事实的只读投影 | Web read model |

发布库目录快照不是第二个发布真相：它只保存读取到的 manifest 摘要和发现时间，供查询、筛选和历史回看。每条记录必须保留 manifest 的绝对路径、SHA-256、库名、版本、别名、交付模式和发现来源。

## 数据模型

新增 `release_library_index.v1`：

```json
{
  "schema_version": "release_library_index.v1",
  "release_root": "/release/root",
  "refreshed_at": "2026-09-21T00:00:00Z",
  "libraries": [{
    "library_id": "vendor_A.ucie",
    "source_type": "正式发布库",
    "releases": [{
      "release_id": "R_20260921",
      "version_id": "20260921_full",
      "alias": "current",
      "link_mode": "symlink",
      "manifest": "/release/root/releases/R_20260921/release_manifest.json",
      "manifest_sha256": "...",
      "status": "READY",
      "published_at": "..."
    }],
    "current": {"release_id": "R_20260921", "source": "alias_link"}
  }]
}
```

同一 `library_id + alias` 的多份 manifest 是历史发布记录，按 `published_at` 再按 manifest 路径稳定排序。当前记录只优先解析 `current` 别名链接；`stage`、`approved` 等其他别名仅保留为历史，不能覆盖“当前发布”。若没有 `current` 链接，则回退到最新 `current` 历史；仅在完全没有 `current` 记录时才回退到最近发布。页面必须显示来源为“别名链接”或“清单回退”。

正式发布库关联 Catalog 时必须以类型库 ID 完全一致为准，例如 `ip/ucie` 只能关联 `ip/ucie`。不得按尾部库名回退到 `stdcell/ucie` 等同名不同类型库。页面显示可读库名，但覆盖预演及其 CLI 任务始终传递稳定类型库 ID。

## 正式发布库接入

1. 管理员在 Web 或 CLI 输入发布根目录。
2. 读取器以受限递归寻找 `release_manifest.json`；忽略 `.staging`、`release_runs`、工作区报告目录，默认深度 8、最大 2,000 份 manifest。
3. 每份 manifest 做结构校验：必须有 `library_name` 或 `library_id`，且 manifest 所在路径不能逃逸出输入根目录。
4. 读取器聚合为发布库目录快照；无效 manifest 单独报告，不阻塞其他库。
5. Web 的库查询增加来源筛选：`全部 / 原始库 / 正式发布库`。正式发布库只提供查看、刷新发布目录和覆盖预演，不能进入 scan/cmp/intake。

## 覆盖发布

覆盖不修改历史 manifest。固定流程是：

1. 用户选择正式发布库、目标别名和候选版本。
2. Web 调用既有 `rel --no-render` 生成覆盖预演，传入 `--overwrite` 仅用于预演。
3. 页面展示现有目标、候选发布清单、库级差异摘要、预计替换文件数与最终 CLI 命令。
4. 真正执行仍只能由 CLI 使用 `rel ... --apply --overwrite`，并要求既有审查/门禁与审计原因。
5. CLI 返回后重新读取发布根目录，新 manifest 成为历史新记录；旧 manifest 保留。

## UI

在“入库 / 候选”阶段新增折叠区“正式发布库接入”：发布根路径、刷新按钮、来源筛选和紧凑表格。表格列为：正式库、当前发布、别名、交付方式、发布时间、来源、操作。

在“扫描 / 对比 / 放行”阶段的发布卡仅在选中原始库时显示“发布预演”；选中正式发布库时显示“查看发布清单 / 生成覆盖预演 / 复制 CLI 覆盖命令”。

## 验收标准

1. 一个根目录包含多个库、多个历史 manifest 时，能读出所有库且不产生 RAW 候选。
2. 同库同别名多个历史发布被保留，当前记录按真实别名链接优先。
3. 覆盖预演不创建/替换交付链接，不删除历史 manifest。
4. Web 只暴露发布目录读取和覆盖预演，拒绝 `--apply`、`--force`、`--no-verify`。
5. `release_manifest.json` 缺字段或损坏时，其他发布库仍可显示，并在读取结果中报告无效条目。
