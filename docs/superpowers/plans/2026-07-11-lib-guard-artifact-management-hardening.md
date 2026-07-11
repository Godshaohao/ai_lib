Status: current

# Lib Guard Artifact Management Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `lib_guard` 用稳定身份、不可变证据、可复现有效组合和原子发布管理大型 IP 库，同时保持现有文件式架构、短命令和 Version Detail 主审查页。

**Architecture:** 保留 `library_registry.tsv -> library_catalog.yml -> catalog -> scan -> diff -> effective -> release` 主线。新增规范化摘要层，把目录名与证据身份分开；把 Catalog 的静态资产快照与运行状态分开；scan/diff/effective/release 通过摘要关联，不通过 HTML 或易变路径反向推断。

**Tech Stack:** Python 3.11 标准库、JSON/TSV/YAML 配置、静态 HTML、`unittest`、C shell 包装脚本、POSIX symlink/`os.replace()`。

## Global Constraints

- 不增加数据库、常驻服务、远程 Registry、通用插件系统或依赖求解器。
- 不增加新的日常短命令；继续使用 `library/cat/scan/cmp/next/rel`。
- `library_registry.tsv` 是人工确认库根事实源；discover 只能生成候选。
- `library_catalog.yml` 是正式库 map；HTML、`report_index.json` 和 `catalog_state.json` 仍然只是投影。
- Version Detail 仍是唯一版本审查投影，不新增身份页、缓存页或发布主页面。
- 大型 LEF/Liberty/SPEF/DB/GDS/OAS 默认不做全内容 hash；证据必须显式标记 `full/mixed/metadata` 强度，不能把 metadata 摘要称为内容摘要。
- 所有运行状态写入必须原子化；失败不得改变当前有效版或已发布 alias。
- 保持现有 `catalog.json`、scan artifact 和 release manifest 的读取兼容；迁移期采用新字段优先、旧字段回退。
- 页面用户文案使用中文，专业字段名和 JSON schema 字段保持英文。

---

## External Research Summary

| 项目 | 可借鉴机制 | 本计划采用方式 |
| --- | --- | --- |
| [Bender](https://github.com/pulp-platform/bender) | `Bender.yml` 表达人类意图，`Bender.lock` 固定精确 Git revision；不要求中央 Registry | `library_catalog.yml` 保持人工意图，`effective_manifest.json` 升级为具体化 lock artifact |
| [FuseSoC](https://fusesoc.readthedocs.io/en/latest/user/build_system/core_files.html) | VLNV、fileset、文件类型、依赖和有序 source list 显式描述 | 复用 canonical `view_type`，不再从 UI 猜类型；显式 metadata 仅作为后续可选项 |
| [SiliconCompiler](https://docs.siliconcompiler.com/en/stable/development_guide/libraries.html) | Hard/soft IP 分型，physical/timing fileset 和 corner 显式建模 | scan evidence 按 view/fileset/corner 聚合，Version Detail 只消费统一模型 |
| [Volare/OpenLane](https://openlane2.readthedocs.io/en/latest/usage/about_pdks.html) | 版本绑定确切 revision；installed 与 enabled 分离；一个 family 一个 active 版本 | 区分 `delivery_label`、`snapshot_digest`、`current_effective` |
| [Conan lockfiles](https://docs.conan.io/2/tutorial/versioning/lockfiles.html) / [Spack environments](https://spack.readthedocs.io/en/latest/environments.html) | 人工 manifest 与具体 lockfile 分离；旧具体化结果默认不变 | effective digest 绑定 FULL、overlay 顺序、组件证据和 resolver 版本 |
| [Pulp](https://pulpproject.org/pulpcore/docs/user/guides/replication/) | 内容未变化时跳过同步；全部成功后才切换 distribution；失败保持旧版本 | scan/diff 按稳定 key 复用；release 完整 staging、verify 后再切 alias |
| [DVC](https://treeverse-dvc.mintlify.app/concepts/data-versioning) | 大文件用小 metadata pointer 和内容/目录摘要追踪 | 保存小型 snapshot identity，不复制 RAW，也不默认全文读取大文件 |
| [OSTree](https://ostreedev.github.io/ostree/atomic-upgrades/) | 新树先构建，再用 symlink 原子切换；旧部署可回滚 | manifest release 写 staging tree，通过 postcheck 后 `os.replace()` alias |

## Architecture Grill Result

**Proposed architecture:** 把 `ai_lib` 改造成通用内容寻址制品平台。

**Decision:** SHRINK。

**Main judgement affected:** 库管理者需要确认“当前看到、比较和发布的是不是同一组 IP 文件”。

**Evidence of necessity:** 当前目录版本名、scan fingerprint、effective ID 和 release ID 不是同一种身份；`catalog.json` 还同时承载资产快照与运行状态；manifest release 可能逐文件写入最终目录后才报告失败。

**Complexity introduced:** 一个共享 identity 模块、一个 Catalog runtime sidecar、几个兼容读取适配器；不引入服务或数据库。

**Simpler substitute:** 规范化 JSON digest、原子 sidecar、staging directory、现有 alias symlink。

**Forbidden architecture:** 内容对象仓库、后台 daemon、通用依赖 solver、自动 discover 入库、HTML 反向驱动业务状态。

**Allowed current architecture:** RAW + 人工配置 -> JSON/TSV evidence -> Version Detail -> manifest-driven symlink release。

## File Structure

| 文件 | 责任 |
| --- | --- |
| `src/lib_guard/identity.py` | 规范化 JSON、snapshot/effective/diff digest；不读写业务文件 |
| `src/lib_guard/scan/policy.py` | 输出影响 scan 语义的稳定 policy identity |
| `src/lib_guard/scan/scanner.py` | 生成 input fingerprint、hash coverage 和 delivery snapshot identity |
| `src/lib_guard/catalog/runtime.py` | 读取、迁移、原子写入 `catalog_runtime.json`，提供合并后的 Catalog view |
| `src/lib_guard/diff/scan_diff.py` | 生成确定性的 diff identity，绑定 old/new snapshot digest |
| `src/lib_guard/effective/manifest.py` | 生成 effective lock identity，绑定组件顺序和证据强度 |
| `src/lib_guard/effective/pointer.py` | current pointer 绑定 effective digest 和 approval digest |
| `src/lib_guard/release/linker.py` | staging、原子切换、失败保持旧 release |
| `src/lib_guard/render/version_review_model.py` | 把身份和证据强度翻译成 IP 使用者可读字段 |
| `src/lib_guard/render/version_review_render.py` | 只渲染身份、证据、变化与发布状态，不计算 digest |

## Execution Phases and Review Gates

| 阶段 | Tasks | 可独立验收结果 | 进入下一阶段前必须确认 |
| --- | --- | --- | --- |
| A. 身份与证据 | 1-4 | scan/diff/effective 有稳定 digest，现有命令和目录不变 | 历史 artifact 回退测试通过；digest 不被误称为完整内容 hash |
| B. Catalog 状态拆分 | 5 | 单库 scan/cmp 不再重写静态 `catalog.json` | 20 库/500 版本模拟中无库丢失，render/window 读取 sidecar 正确 |
| C. Release 事务化 | 6 | staging 全部成功后才切换 active alias | 管理者确认 active 路径采用 `<release_root>/<alias>`；旧真实目录不自动迁移 |
| D. 用户投影与交付 | 7-8 | 终端和 Version Detail 解释身份但不增加操作负担 | 全量测试和真实 fixture 演练通过 |

Task 6 改变的是 release 路径契约，不应与 Tasks 1-5 混在同一个提交或无审查连续执行。若现网消费者不能改用 `<release_root>/<alias>/LEF/...`，暂停 Task 6，先单独制定兼容迁移方案；Tasks 1-5 和 7-8 仍可独立交付。

### Task 1: Add Canonical Artifact Identity Primitives

**Files:**
- Create: `src/lib_guard/identity.py`
- Create: `src/lib_guard/test/test_artifact_identity.py`

**Interfaces:**
- Produces: `canonical_digest(value) -> str`
- Produces: `build_snapshot_identity(...) -> dict[str, Any]`
- Produces: `build_diff_identity(...) -> dict[str, Any]`
- Produces: `build_effective_identity(manifest) -> dict[str, Any]`

- [ ] **Step 1: Write failing identity tests**

```python
from lib_guard.identity import build_diff_identity, build_effective_identity, canonical_digest


def test_canonical_digest_ignores_mapping_order(self):
    self.assertEqual(canonical_digest({"b": 2, "a": 1}), canonical_digest({"a": 1, "b": 2}))


def test_diff_identity_changes_only_when_evidence_changes(self):
    first = build_diff_identity("sha256:old", "sha256:new", "scan_diff.v1")
    second = build_diff_identity("sha256:old", "sha256:new", "scan_diff.v1")
    changed = build_diff_identity("sha256:old", "sha256:new2", "scan_diff.v1")
    self.assertEqual(first, second)
    self.assertNotEqual(first["digest"], changed["digest"])


def test_effective_identity_excludes_paths_and_timestamps(self):
    left = {"base_full_version": "v1", "components": [{"version_id": "v1", "snapshot_digest": "sha256:a"}], "created_at": "A"}
    right = {**left, "created_at": "B", "manifest_path": "/other/host/file.json"}
    self.assertEqual(build_effective_identity(left)["digest"], build_effective_identity(right)["digest"])
```

- [ ] **Step 2: Run the focused test and confirm import failure**

Run:

```csh
setenv PYTHONPYCACHEPREFIX /tmp/ai_lib_pycache
setenv PYTHONPATH src
python3 -m unittest src.lib_guard.test.test_artifact_identity -q
```

Expected: FAIL because `lib_guard.identity` does not exist.

- [ ] **Step 3: Implement deterministic identity functions**

```python
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def build_snapshot_identity(*, input_fingerprint: Mapping[str, Any], policy_identity: Mapping[str, Any], tool_version: str, strength: str) -> dict[str, Any]:
    payload = {"input_fingerprint": dict(input_fingerprint), "policy": dict(policy_identity), "tool_version": tool_version}
    return {"schema_version": "delivery_snapshot_identity.v1", "digest": canonical_digest(payload), "strength": strength, "payload": payload}


def build_diff_identity(old_digest: str, new_digest: str, policy_version: str) -> dict[str, Any]:
    payload = {"old_snapshot_digest": old_digest, "new_snapshot_digest": new_digest, "policy_version": policy_version}
    return {"schema_version": "diff_identity.v1", "digest": canonical_digest(payload), **payload}


def build_effective_identity(manifest: Mapping[str, Any]) -> dict[str, Any]:
    components = [
        {key: item.get(key) for key in ("role", "version_id", "snapshot_digest", "evidence_strength", "scope", "order")}
        for item in manifest.get("components", []) or []
    ]
    payload = {"library_id": manifest.get("library_id"), "base_full_version": manifest.get("base_full_version"), "components": components, "tombstones": sorted((manifest.get("tombstones") or {}).keys()), "resolver_version": "effective.v1"}
    return {"schema_version": "effective_identity.v1", "digest": canonical_digest(payload), "payload": payload}
```

- [ ] **Step 4: Run focused tests**

Expected: all tests in `test_artifact_identity.py` PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib_guard/identity.py src/lib_guard/test/test_artifact_identity.py
git commit -m "feat: add stable artifact identity primitives"
```

### Task 2: Bind Scan Evidence to Snapshot Identity

**Files:**
- Modify: `src/lib_guard/scan/policy.py`
- Modify: `src/lib_guard/scan/scanner.py`
- Modify: `src/lib_guard/cli_commands/catalog.py`
- Modify: `src/lib_guard/catalog/index.py`
- Test: `src/lib_guard/test/test_scan_pipeline.py`
- Test: `src/lib_guard/test/test_catalog_timeline.py`

**Interfaces:**
- Consumes: `build_snapshot_identity()` from Task 1
- Produces: `ScanPolicy.identity_payload() -> dict[str, Any]`
- Produces: `scan_meta.snapshot_identity`
- Produces: `catalog runtime scan.snapshot_identity`

- [ ] **Step 1: Add failing tests for stable scan identity and evidence strength**

```python
def test_scan_snapshot_identity_is_stable_and_reports_hash_strength(self):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "raw"
        root.mkdir()
        (root / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
        base = dict(
            root_path=str(root), library_type="ip", library_name="demo", version="v1",
            scan_mode="scan", state_dir=str(Path(td) / "state"), cache_dir=str(Path(td) / "cache"),
            skip_cache=True, no_cache=True, no_progress=True, parse_jobs=1,
            tool_version="0.5.0", schema_version="1.0",
        )
        first = Path(td) / "first"
        second = Path(td) / "second"
        ScanRunner(SimpleNamespace(**base, out_dir=str(first), scan_id="S1")).run()
        ScanRunner(SimpleNamespace(**base, out_dir=str(second), scan_id="S2")).run()
        first_meta = json.loads((first / "scan_meta.json").read_text(encoding="utf-8"))
        second_meta = json.loads((second / "scan_meta.json").read_text(encoding="utf-8"))
    self.assertEqual(first_meta["snapshot_identity"]["digest"], second_meta["snapshot_identity"]["digest"])
    self.assertIn(first_meta["snapshot_identity"]["strength"], {"full", "mixed", "metadata"})
```

- [ ] **Step 2: Verify the test fails because `snapshot_identity` is absent**

Run:

```csh
python3 -m unittest src.lib_guard.test.test_scan_pipeline.ScanPipelineTest.test_scan_snapshot_identity_is_stable_and_reports_hash_strength -q
```

- [ ] **Step 3: Add policy identity**

```python
def identity_payload(self) -> dict[str, Any]:
    return {
        "schema_version": "scan_policy_identity.v1",
        "hash_policy": str(_get(self.config, "hash_policy", "smart") or "smart").lower(),
        "small_file_sha256_max_bytes": int(_get(self.config, "small_file_sha256_max_bytes", self.DEFAULT_SMALL_FILE_MAX_BYTES) or self.DEFAULT_SMALL_FILE_MAX_BYTES),
        "parse_file_types": sorted(str(item).lower() for item in (_get(self.config, "parse_file_types", []) or [])),
        "parse_exclude_file_types": sorted(str(item).lower() for item in (_get(self.config, "parse_exclude_file_types", []) or [])),
    }
```

- [ ] **Step 4: Extend `_input_fingerprint()` without renaming its existing `hash` field**

Include `sha256`, `hash_status`, and `hash_policy` in normalized entries. Add coverage counts and derive strength as follows:

```python
hashed = sum(1 for item in entries if item.get("sha256"))
strength = "full" if entries and hashed == len(entries) else ("mixed" if hashed else "metadata")
```

Then call `build_snapshot_identity()` and write the result to both `scan_meta.json` and `file_inventory.json`.

- [ ] **Step 5: Persist the same object in Catalog runtime state**

Pass `snapshot_identity` through `run_catalog_workflow()` into `update_catalog_scan_status()`. Do not recompute it in Catalog.

- [ ] **Step 6: Run scan and timeline tests**

```csh
python3 -m unittest src.lib_guard.test.test_scan_pipeline src.lib_guard.test.test_catalog_timeline -q
```

Expected: PASS; existing `input_fingerprint.hash` assertions remain valid.

- [ ] **Step 7: Commit**

```bash
git add src/lib_guard/scan/policy.py src/lib_guard/scan/scanner.py src/lib_guard/cli_commands/catalog.py src/lib_guard/catalog/index.py src/lib_guard/test/test_scan_pipeline.py src/lib_guard/test/test_catalog_timeline.py
git commit -m "feat: bind scan evidence to stable snapshot identity"
```

### Task 3: Make Diff Identity Deterministic and Traceable

**Files:**
- Modify: `src/lib_guard/diff/scan_diff.py`
- Modify: `src/lib_guard/catalog/index.py`
- Test: `src/lib_guard/test/test_scan_pipeline.py`

**Interfaces:**
- Consumes: `scan_meta.snapshot_identity.digest`
- Produces: `diff_meta.identity`
- Produces: deterministic short `diff_id`

- [ ] **Step 1: Add a failing deterministic diff test**

```python
def test_diff_identity_is_stable_for_same_scan_evidence(self):
    first = diff_scan_outputs(old_out, new_out, out_path=Path(td) / "first")
    second = diff_scan_outputs(old_out, new_out, out_path=Path(td) / "second")
    self.assertEqual(first["diff_meta"]["identity"], second["diff_meta"]["identity"])
    self.assertEqual(first["diff_meta"]["diff_id"], second["diff_meta"]["diff_id"])
```

Place these assertions at the end of the existing `test_diff_scan_reports_inventory_and_summary_changes()` fixture, which already creates `old_out` and `new_out`; do not introduce a second scan fixture.

- [ ] **Step 2: Verify current timestamp-based `diff_id` makes the test fail**

- [ ] **Step 3: Replace timestamp identity with snapshot-bound identity**

```python
identity = build_diff_identity(
    old_snapshot_digest(old_meta, old_inventory),
    new_snapshot_digest(new_meta, new_inventory),
    "scan_diff.v1",
)
diff_id = identity["digest"].split(":", 1)[1][:16]
```

`old_snapshot_digest()` and `new_snapshot_digest()` must use the new snapshot field first and fall back to existing `input_fingerprint.hash` for historical scans. Keep `diff_created_at` as audit time, never as identity input.

- [ ] **Step 4: Add compatibility test for old scans without snapshot identity**

Expected: diff still succeeds and marks `identity_source: input_fingerprint_fallback`.

- [ ] **Step 5: Run diff regression tests**

```csh
python3 -m unittest src.lib_guard.test.test_scan_pipeline.ScanPipelineTest.test_diff_scan_reports_inventory_and_summary_changes src.lib_guard.test.test_scan_pipeline.ScanPipelineTest.test_diff_identity_is_stable_for_same_scan_evidence -q
```

- [ ] **Step 6: Commit**

```bash
git add src/lib_guard/diff/scan_diff.py src/lib_guard/catalog/index.py src/lib_guard/test/test_scan_pipeline.py
git commit -m "feat: make scan diff identity deterministic"
```

### Task 4: Turn Effective Manifest into a Reproducible Lock Artifact

**Files:**
- Modify: `src/lib_guard/effective/manifest.py`
- Modify: `src/lib_guard/effective/pointer.py`
- Modify: `src/lib_guard/window/cli.py`
- Test: `src/lib_guard/test/test_effective_manifest.py`
- Test: `src/lib_guard/test/test_effective_pointer.py`
- Test: `src/lib_guard/test/test_window_intake.py`

**Interfaces:**
- Consumes: component `snapshot_identity.digest`
- Produces: `effective_manifest.identity`
- Produces: `current_effective.effective_digest`
- Produces: `review_approval.candidate_effective_digest`

- [ ] **Step 1: Add failing effective lock tests**

```python
def test_effective_digest_binds_component_order_and_snapshot(self):
    first = build_effective_manifest(catalog, "demo", "full", [("fix1", ["lef"])])
    second = build_effective_manifest(catalog, "demo", "full", [("fix1", ["lef"])])
    self.assertEqual(first["identity"]["digest"], second["identity"]["digest"])
    reordered = build_effective_manifest(catalog, "demo", "full", [("fix2", ["lef"]), ("fix1", ["lef"])])
    self.assertNotEqual(first["identity"]["digest"], reordered["identity"]["digest"])
```

- [ ] **Step 2: Add `snapshot_digest` and `evidence_strength` to each component**

Use scan evidence first; historical components without it use `input_fingerprint.hash` and record `identity_source: legacy_input_fingerprint`.

- [ ] **Step 3: Add effective identity after the manifest file map is complete**

```python
identity = build_effective_identity({
    "library_id": library_id,
    "base_full_version": base_full_version,
    "components": components,
    "tombstones": tombstones,
})
manifest["identity"] = identity
return manifest
```

Implement this by assigning the function's existing return mapping to `manifest`; do not duplicate or reorder the existing `effective_files`, `conflicts`, `summary`, `note`, or `created_at` fields.

- [ ] **Step 4: Bind pointer and approval to effective digest**

`make_current_pointer()` must save `effective_digest`. `_write_review_approval()` must save the same digest. `accept-window` must reject acceptance when the manifest's recomputed digest differs from the compare target or approval digest.

- [ ] **Step 5: Preserve historical manifest compatibility**

When `identity` is absent, retain current manifest SHA256 validation and mark `effective_identity_source: manifest_sha256_fallback`.

- [ ] **Step 6: Run effective/window tests**

```csh
python3 -m unittest src.lib_guard.test.test_effective_manifest src.lib_guard.test.test_effective_pointer src.lib_guard.test.test_window_intake -q
```

- [ ] **Step 7: Commit**

```bash
git add src/lib_guard/effective/manifest.py src/lib_guard/effective/pointer.py src/lib_guard/window/cli.py src/lib_guard/test/test_effective_manifest.py src/lib_guard/test/test_effective_pointer.py src/lib_guard/test/test_window_intake.py
git commit -m "feat: lock effective compositions to evidence digests"
```

### Task 5: Separate Catalog Asset Snapshot from Runtime State

**Files:**
- Create: `src/lib_guard/catalog/runtime.py`
- Modify: `src/lib_guard/catalog/index.py`
- Modify: `src/lib_guard/cli_commands/catalog.py`
- Modify: `src/lib_guard/window/resolver.py`
- Modify: `src/lib_guard/review/state.py`
- Modify: `src/lib_guard/render/catalog_report.py`
- Test: `src/lib_guard/test/test_catalog_timeline.py`
- Test: `src/lib_guard/test/test_short_cli_refresh.py`
- Test: `src/lib_guard/test/test_window_intake.py`

**Interfaces:**
- Produces: `catalog_runtime.json`
- Produces: `load_catalog_view(path) -> dict[str, Any]`
- Produces: `update_runtime_entry(path, version_key, patch) -> Path`

- [ ] **Step 1: Add a failing non-overwrite test**

```python
def test_scan_status_update_does_not_rewrite_catalog_snapshot(self):
    before = catalog_path.read_bytes()
    update_catalog_scan_status(catalog_path, version_key=key, status="PASS", scan_dir=scan_dir, scan_id="S1")
    self.assertEqual(before, catalog_path.read_bytes())
    self.assertTrue((catalog_path.parent / "catalog_runtime.json").exists())
    merged = load_catalog_view(catalog_path)
    self.assertEqual(merged["runtime_state"][key]["scan"]["scan_id"], "S1")
```

- [ ] **Step 2: Implement sidecar reading and atomic writing**

```python
def runtime_path_for(catalog_path: str | Path) -> Path:
    return Path(catalog_path).with_name("catalog_runtime.json")


def load_catalog_view(catalog_path: str | Path) -> dict[str, Any]:
    catalog = read_json(catalog_path, {}) or {}
    embedded = dict(catalog.get("runtime_state", {}) or {})
    sidecar = read_json(runtime_path_for(catalog_path), {}) or {}
    catalog["runtime_state"] = {**embedded, **dict(sidecar.get("runtime_state", {}) or {})}
    return rebuild_catalog(catalog)
```

`update_runtime_entry()` must use `atomic_write_json(..., lock=True)` and preserve unrelated versions.

- [ ] **Step 3: Migrate runtime writers to sidecar only**

Move scan, diff and release status updates out of `catalog.json`. Explicit Catalog refresh may rewrite the asset snapshot but must leave `catalog_runtime.json` untouched.

- [ ] **Step 4: Migrate business consumers to `load_catalog_view()`**

At minimum cover short CLI list/scan/cmp, window resolver, review-state builder and renderer. Sidecar data overrides embedded legacy runtime fields.

- [ ] **Step 5: Add migration and shrink-guard tests**

Test embedded-only legacy Catalog, sidecar-only new Catalog, both present with sidecar precedence, and refresh with 20 libraries retaining all runtime entries.

- [ ] **Step 6: Run Catalog/render/window regression tests**

```csh
python3 -m unittest src.lib_guard.test.test_catalog_timeline src.lib_guard.test.test_short_cli_refresh src.lib_guard.test.test_window_intake src.lib_guard.test.test_render_impact -q
```

- [ ] **Step 7: Commit**

```bash
git add src/lib_guard/catalog/runtime.py src/lib_guard/catalog/index.py src/lib_guard/cli_commands/catalog.py src/lib_guard/window/resolver.py src/lib_guard/review/state.py src/lib_guard/render/catalog_report.py src/lib_guard/test/test_catalog_timeline.py src/lib_guard/test/test_short_cli_refresh.py src/lib_guard/test/test_window_intake.py
git commit -m "refactor: separate catalog snapshot from runtime state"
```

### Task 6: Make Manifest Release Transactional

**Files:**
- Modify: `src/lib_guard/release/linker.py`
- Modify: `src/lib_guard/release/postcheck.py`
- Modify: `src/lib_guard/release/bundle.py`
- Test: `src/lib_guard/test/test_release_manifest_flow.py`

**Interfaces:**
- Produces: `<release_root>/.staging/<release_id>/`
- Produces: immutable `<release_root>/releases/<release_id>/`
- Produces: atomically replaced `<release_root>/<alias>` symlink

- [ ] **Step 1: Add failure-safety test**

```python
def test_manifest_release_failure_keeps_current_alias_unchanged(self):
    current_before = (release_root / "current").resolve()
    manifest["release_id"] = "broken"
    manifest["files"].append({
        "library_type": "ip", "library_name": "demo", "version_id": "v2",
        "source_path": str(root / "missing.lef"), "target_relpath": "LEF/missing.lef", "file_type": "lef",
    })
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    result = link_release_from_manifest(manifest_path, apply=True, overwrite=True)
    self.assertEqual(result["status"], "FAILED")
    self.assertEqual(current_before, (release_root / "current").resolve())
    self.assertFalse((release_root / "releases" / "broken").exists())
```

Extend the existing manifest apply fixture so `root`, `release_root`, `manifest`, and `manifest_path` use its real setup rather than adding a parallel helper.

- [ ] **Step 2: Build all files under staging**

Treat `release_root` as the release container. Never write planned files directly into `<release_root>/<alias>`. Link/copy every manifest entry into `.staging/<release_id>`, preserving the existing uppercase view layout under that tree.

- [ ] **Step 3: Verify staging before promotion**

Refactor `verify_release_manifest()` to accept an explicit candidate root. Verification failure removes only staging and leaves the active alias untouched.

- [ ] **Step 4: Promote and switch alias atomically**

```python
os.replace(staging_dir, release_root / "releases" / release_id)
tmp_alias.symlink_to(immutable_release_dir)
os.replace(tmp_alias, active_alias)
```

`immutable_release_dir` is `<release_root>/releases/<release_id>`, and `active_alias` is `<release_root>/<alias>`. Do not delete the previous immutable release during promotion. Existing `--overwrite` controls replacement of the same `release_id`, not deletion of unrelated releases. If `<release_root>/<alias>` is an existing real directory rather than a symlink, stop with `MIGRATION_REQUIRED`; do not rename or delete it automatically.

- [ ] **Step 5: Add success, rollback and interrupted-staging tests**

Cover symlink mode, copy mode, missing source, hash mismatch, stale staging cleanup and previous alias preservation.

- [ ] **Step 6: Run release tests**

```csh
python3 -m unittest src.lib_guard.test.test_release_manifest_flow src.lib_guard.test.test_release_force_manifest -q
```

- [ ] **Step 7: Commit**

```bash
git add src/lib_guard/release/linker.py src/lib_guard/release/postcheck.py src/lib_guard/release/bundle.py src/lib_guard/test/test_release_manifest_flow.py
git commit -m "feat: make manifest release atomic"
```

### Task 7: Expose Identity and Evidence Strength Without Adding UI Noise

**Files:**
- Modify: `src/lib_guard/cli_commands/catalog.py`
- Modify: `src/lib_guard/render/version_review_model.py`
- Modify: `src/lib_guard/render/version_review_render.py`
- Modify: `src/lib_guard/render/catalog_workspace_report.py`
- Test: `src/lib_guard/test/test_version_detail_report.py`
- Test: `src/lib_guard/test/test_library_workspace_model.py`

**Interfaces:**
- Consumes: delivery/diff/effective identity fields
- Produces: Chinese terminal table and Version Detail identity summary

- [ ] **Step 1: Add failing projection tests**

```python
def test_version_detail_distinguishes_label_digest_and_current_pointer(self):
    html = render_fixture()
    self.assertIn("交付版本", html)
    self.assertIn("证据快照", html)
    self.assertIn("证据强度", html)
    self.assertIn("当前有效组合", html)
    self.assertNotIn("delivery_snapshot_identity.v1", html)
```

- [ ] **Step 2: Add one compact model group**

```python
model["artifact_identity"] = {
    "delivery_label": version_id,
    "snapshot_digest_short": short_digest(snapshot_digest),
    "evidence_strength": strength,
    "diff_digest_short": short_digest(diff_digest),
    "effective_digest_short": short_digest(effective_digest),
    "is_current_effective": is_current,
}
```

- [ ] **Step 3: Render the group in the existing first-screen context**

Do not add metric cards. Use a compact definition table. Translate strengths as `完整内容证据 / 混合证据 / 元数据证据` and state explicitly that metadata evidence is not automatically a blocker.

- [ ] **Step 4: Extend existing list output, not the command surface**

`lg library list <LIB> --versions` should show `版本名 / Snapshot / Scan / Diff / Effective角色`. Do not create `lg identity` or `lg cache`.

- [ ] **Step 5: Run render/list tests**

```csh
python3 -m unittest src.lib_guard.test.test_version_detail_report src.lib_guard.test.test_library_workspace_model src.lib_guard.test.test_short_cli_command_surface -q
```

- [ ] **Step 6: Commit**

```bash
git add src/lib_guard/cli_commands/catalog.py src/lib_guard/render/version_review_model.py src/lib_guard/render/version_review_render.py src/lib_guard/render/catalog_workspace_report.py src/lib_guard/test/test_version_detail_report.py src/lib_guard/test/test_library_workspace_model.py
git commit -m "feat: expose artifact identity in review projections"
```

### Task 8: Complete Migration Documentation and Full Regression

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/data_contract.md`
- Modify: `docs/basic_tutorial.md`
- Modify: `docs/test_plan.md`
- Test: `src/lib_guard/test/test_architecture_boundaries.py`
- Test: `src/lib_guard/test/test_compat_imports.py`

**Interfaces:**
- Documents: identity vocabulary, sidecar precedence, failure behavior and operator commands
- Verifies: no new command/page/database dependency

- [ ] **Step 1: Add architecture boundary assertions**

Assert that render modules do not import scan writers, `identity.py` has no renderer/filesystem business imports, and runtime state writes target `catalog_runtime.json`.

- [ ] **Step 2: Update the data contract table**

Document `delivery_label`, `snapshot_identity`, `diff_identity`, `effective_identity`, `current_effective`, `catalog_runtime.json`, and legacy fallback precedence.

- [ ] **Step 3: Update the operator tutorial**

Keep the normal flow unchanged:

```csh
lg next <LIBRARY>
lg next <LIBRARY> --apply
lg accept-window <LIBRARY> --accepted-by "$USER" --note "review passed"
lg rel <LIBRARY> --check-first --explain
lg rel <LIBRARY> --apply
```

Explain that digest fields are automatic evidence, not new parameters the operator must type.

- [ ] **Step 4: Run compile and full unit suite**

```csh
setenv PYTHONPYCACHEPREFIX /tmp/ai_lib_pycache
setenv PYTHONPATH src
python3 -m compileall -q src
python3 -m unittest discover -s src/lib_guard/test -p 'test*.py' -q
```

Expected: compile PASS and all tests PASS.

- [ ] **Step 5: Run a real-fixture rehearsal**

```csh
setenv WORK "$PROJ/work/artifact_identity_rehearsal"
$PROJ/scripts/lg.csh init "$WORK" --raw-root "$PROJ/tests/fixtures/raw/vendor_A" --library-type ip
$PROJ/scripts/lg.csh library add vendor_A.openroad_platform.openroad_asap7 --root "$PROJ/tests/fixtures/raw/vendor_A/openroad_asap7"
$PROJ/scripts/lg.csh library apply
$PROJ/scripts/lg.csh cat --refresh-catalog --with-evidence
$PROJ/scripts/lg.csh scan vendor_A.openroad_platform.openroad_asap7 20260627_asap7
$PROJ/scripts/lg.csh next vendor_A.openroad_platform.openroad_asap7 --plan-only
```

Expected: Catalog keeps all configured libraries; scan output has snapshot identity; Version Detail displays short digest and evidence strength; no command requests a digest from the operator.

- [ ] **Step 6: Commit**

```bash
git add docs/architecture.md docs/data_contract.md docs/basic_tutorial.md docs/test_plan.md src/lib_guard/test/test_architecture_boundaries.py src/lib_guard/test/test_compat_imports.py
git commit -m "docs: define artifact identity and atomic release flow"
```

## Deferred Work

- Optional per-library manifest for explicit filesets/dependencies. Defer until at least three real libraries cannot be represented cleanly by registry + scan evidence.
- Signature/trust chain similar to FuseSoC signed core files. Defer until there is an organizational key owner and revocation process.
- Evidence retention/prune policy. Define only after measuring real disk use and confirming which historical scans are required for audit.
- Remote artifact distribution or content-addressed blob storage. Explicitly out of scope while RAW remains the authoritative internal filesystem.
- SemVer and transitive dependency solving. Existing delivery directory names remain opaque labels.

## Completion Criteria

- Same scan evidence and policy produce the same snapshot digest.
- Same old/new evidence produce the same diff digest; timestamps do not affect identity.
- Effective acceptance is bound to component evidence and compare digest.
- Scan/cmp updates do not rewrite the static Catalog asset snapshot.
- Failed release never changes the active alias or partially updates the served tree.
- Existing short commands remain valid and require no new digest arguments.
- Version Detail explains label, evidence strength, comparison identity and current effective status without adding a new page.
- Full unit suite and one realistic fixture rehearsal pass.
