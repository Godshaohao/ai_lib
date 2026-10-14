Status: current

实施状态：已完成并验证。发布库索引刷新是同步的受控读取接口，故不进入后台任务动作白名单；后台白名单只新增“正式库覆盖预演”。

审查补强：正式发布库到 Catalog 的覆盖预演只允许类型库 ID 完全一致，禁止同名回退；“当前发布”只认 `current` 别名链接，`stage` 或 `approved` 仅作为发布历史展示。

# 正式发布库接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将一个包含多个已发布库的目录接入为可查询的正式发布库索引，并为同库覆盖发布提供只读预演和 CLI 联动。

**Architecture:** 新增只读取 `release_manifest.json` 的发布库索引模块。它把 manifest 摘要写入工作区配置目录，Web 从索引投影正式发布库列表；真正发布继续由既有 `rel` CLI 负责，Web 仅生成覆盖预演和最终命令。

**Tech Stack:** Python 3.11、既有 `atomic_write_json`、Flask Web Console、原生 HTML/CSS/JavaScript、unittest。

## Global Constraints

- 不把正式发布目录加入 `raw_root`、Catalog、scan 或 diff。
- 发布事实只能来自既有 `release_manifest.json` 和别名链接。
- Web 禁止真实发布、`--apply`、`--force`、`--no-verify`。
- 覆盖预演不得创建、替换或删除发布链接和历史 manifest。
- UI 中文文案，正式发布库与原始库必须明显区分。

---

### Task 1: 发布库索引读取器

**Files:**
- Create: `src/lib_guard/release/library_index.py`
- Create: `src/lib_guard/test/test_release_library_index.py`

**Interfaces:**
- Produces: `build_release_library_index(release_root, *, max_depth=8, max_manifests=2000) -> dict[str, Any]`
- Produces: `write_release_library_index(path, index) -> Path`
- Consumes: `release_manifest.json`、别名符号链接、`atomic_write_json`。

- [x] **Step 1: Write the failing test**

```python
def test_index_groups_multiple_library_manifests_and_keeps_history(self) -> None:
    index = build_release_library_index(self._fixture_release_root())
    self.assertEqual(index["summary"]["library_count"], 2)
    ucie = next(row for row in index["libraries"] if row["library_id"] == "ip/ucie")
    self.assertEqual(len(ucie["releases"]), 2)
    self.assertEqual(ucie["current"]["source"], "alias_link")
```

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_release_library_index -q`

Expected: import failure because `lib_guard.release.library_index` does not exist.

- [x] **Step 3: Write minimal implementation**

```python
def build_release_library_index(release_root: str | Path, *, max_depth: int = 8, max_manifests: int = 2000) -> dict[str, Any]:
    root = Path(release_root).expanduser().resolve()
    # Walk only release_manifest.json below root, reject escaped paths,
    # group validated rows by library_id, and separately collect invalid entries.
    return {"schema_version": "release_library_index.v1", "release_root": str(root), "libraries": []}

def write_release_library_index(path: str | Path, index: Mapping[str, Any]) -> Path:
    return atomic_write_json(path, dict(index), lock=True)
```

- [x] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_release_library_index -q`

Expected: `OK`.

### Task 2: CLI 刷新和查询入口

**Files:**
- Modify: `src/lib_guard/short_cli.py`
- Modify: `src/lib_guard/project_config.py`
- Modify: `src/lib_guard/test/test_short_cli_command_surface.py`

**Interfaces:**
- Produces: `lg release-library refresh [--root <PATH>]`
- Produces: `lg release-library list [--library <ID>]`
- Uses: `build_release_library_index()` and config key `release_library_index`.

- [x] **Step 1: Write the failing test**

```python
def test_release_library_refresh_uses_release_root_not_raw_root(self) -> None:
    command = expand_short_cli(["release-library", "refresh"], self.config)
    self.assertIn(str(self.config["release_root"]), command)
    self.assertNotIn(str(self.config["raw_root"]), command)
```

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_short_cli_command_surface -q`

Expected: parser rejects `release-library`.

- [x] **Step 3: Write minimal implementation**

Add a `release-library` command group. `refresh` writes only \${workspace}/config/release_libraries/latest.json; `list` reads it and prints a concise table. Neither command can invoke scan, discover, catalog refresh or release apply.

- [x] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_short_cli_command_surface src.lib_guard.test.test_release_library_index -q`

Expected: `OK`.

### Task 3: Web 读取模型和受控预演路由

**Files:**
- Modify: `src/lib_guard/web/read_model.py`
- Modify: `src/lib_guard/web/app.py`
- Modify: `src/lib_guard/test/test_web_read_model.py`
- Modify: `src/lib_guard/test/test_web_app.py`

**Interfaces:**
- Produces: `list_release_library_rows(state) -> dict[str, Any]`
- Produces: `POST /api/release-libraries/refresh`
- Produces: `POST /api/release-libraries/<library>/preview-overwrite`

- [x] **Step 1: Write failing tests**

```python
def test_release_library_rows_do_not_merge_into_raw_catalog(self) -> None:
    rows = list_release_library_rows(state)
    self.assertEqual(rows["libraries"][0]["source_type"], "正式发布库")
    self.assertNotIn(rows["libraries"][0]["library_id"], raw_catalog_library_ids)

def test_web_overwrite_preview_rejects_apply_and_force(self) -> None:
    response = client.post(url, json={"alias": "current", "apply": True, "force": True})
    self.assertEqual(response.status_code, 400)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_web_read_model src.lib_guard.test.test_web_app -q`

Expected: missing reader and routes.

- [x] **Step 3: Write minimal implementation**

The refresh route calls the indexer only. The preview route constructs existing `rel` arguments with `--no-render --overwrite` and explicitly rejects `apply`, `force`, and `no_verify`. It returns plan paths, selected prior release and an escaped CLI command including `--apply --overwrite` for terminal execution.

- [x] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_web_read_model src.lib_guard.test.test_web_app -q`

Expected: `OK`.

### Task 4: Web 查询与覆盖预演界面

**Files:**
- Modify: `src/lib_guard/web/templates/index.html`
- Modify: `src/lib_guard/web/static/app.js`
- Modify: `src/lib_guard/web/static/styles.css`
- Modify: `src/lib_guard/test/test_web_ui_contract.py`

**Interfaces:**
- Consumes: 发布库索引、刷新和覆盖预演 API。
- Produces: 发布库路径输入、来源筛选、正式发布库表和覆盖预演结果卡。

- [x] **Step 1: Write failing UI contract test**

```python
def test_formal_release_library_controls_are_present(self) -> None:
    self.assertIn('id="release-library-root"', template)
    self.assertIn('id="refresh-release-libraries"', template)
    self.assertIn('id="release-library-source-filter"', template)
    self.assertIn('id="release-library-table-body"', template)
    self.assertIn('id="release-overwrite-preview"', template)
```

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_web_ui_contract -q`

Expected: assertion failure for missing control IDs.

- [x] **Step 3: Write minimal implementation**

Render a compact table only after a release index exists. Keep original/raw and formal/release libraries in separate rows and filters. The overwrite preview card labels target release, current link, candidate, planned effect, manifest artifacts and CLI-only apply command. It must not add an apply button.

- [x] **Step 4: Run browser verification**

1. 使用 smoke 工作区启动本地 Web 服务，按 1440px 桌面视口验证管理区、正式发布库表头、空索引提示和无发布按钮。
2. 多库、多历史和 `alias_link` 选择由 `test_release_library_index.py` 与 `test_web_app.py` 的临时目录集成测试验证，避免浏览器验收写入真实发布根目录。
3. 覆盖预演接口验证只生成 `rel ... --overwrite --no-render` 预演任务，返回给终端的命令才含 `--apply --overwrite`；索引、别名链接和历史 manifest 未被写入。

### Task 5: 全量回归和架构约束

**Files:**
- Modify: `src/lib_guard/test/test_architecture_invariants.py`

**Interfaces:**
- Enforces: release-library code never invokes scan/discover/catalog mutation and Web never offers release apply.

- [x] **Step 1: Write failing invariant test**

```python
def test_release_library_web_surface_is_read_or_preview_only(self) -> None:
    # refresh 是同步索引读取接口；覆盖预演才是后台动作。
    self.assertIn("release-overwrite-preview", WEB_ACTION_SPECS)
    self.assertNotIn("release-library-apply", WEB_ACTION_SPECS)
    self.assertNotIn("--apply", release_library_route_source)
```

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest src.lib_guard.test.test_architecture_invariants -q`

Expected: missing release-library Web action declarations.

- [x] **Step 3: Implement narrow allowlist and run full validation**

保持 `POST /api/release-libraries/refresh` 为同步、受限的索引读取接口；后台动作白名单只新增 `release-overwrite-preview`，然后运行：

```bash
PYTHONPATH=src python3 -m compileall -q src
PYTHONPATH=src python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q
git diff --check
```

Expected: all tests pass, no compile errors, no whitespace errors.
