from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class WebUiContractTest(unittest.TestCase):
    def test_home_action_deck_exposes_parallel_version_actions_with_scoped_forms(self) -> None:
        template = (ROOT / "src" / "lib_guard" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "lib_guard" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "src" / "lib_guard" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="action-deck"', template)
        self.assertIn('aria-label="版本与交付动作"', template)
        self.assertLess(template.index('id="action-deck"'), template.index('class="content-grid"'))
        self.assertIn(">打开版本详情页<", template)
        self.assertNotIn(">选择版本<", template)
        for action_id, label in (
            ("scan-action-button", "扫描"),
            ("compare-action-button", "对比"),
            ("open-file-diff", "深度文件对比"),
            ("open-review-actions", "审查记录"),
            ("release-action-button", "发布检查"),
        ):
            self.assertIn(f'id="{action_id}"', template)
            self.assertIn(label, template)
        self.assertIn('id="file-diff-relpath"', template)
        self.assertIn('id="review-gate-operation"', template)
        self.assertIn('id="review-packet-operation"', template)
        for element_id in (
            "scan-action-button",
            "compare-action-button",
            "release-action-button",
            "review-gate-operation",
            "review-packet-operation",
            "review-owner",
            "reviewer",
            "review-id",
            "review-decision",
            "review-note",
        ):
            self.assertEqual(template.count(f'id="{element_id}"'), 1, element_id)
        self.assertNotIn('<h4>手动文件核对</h4>', template)
        self.assertNotIn('<h4>审查记录与有效组合</h4>', template)
        self.assertIn("openFileDiffWorkbench", script)
        self.assertIn("openReviewActions", script)
        self.assertIn("action-deck-grid", styles)
        self.assertIn("action-card", styles)
        self.assertIn('class="workflow-operator-strip"', template)
        grid_section = template.split('class="action-deck-grid"', 1)[1].split('class="workflow-operator-strip"', 1)[0]
        self.assertNotIn("接入与有效版", grid_section)
        self.assertIn("新版本接入", template)
        self.assertIn("查看接入建议", template)
        self.assertIn("生成处理建议", template)
        self.assertIn("生成处理计划", template)
        self.assertIn("设为当前可用版本", template)
        self.assertNotIn("接入窗口", template)
        self.assertNotIn("下一步预演", template)
        self.assertNotIn("接受候选有效版", template)
        self.assertIn(".action-deck-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); align-items: start; gap: 10px;", styles)
        self.assertIn(".workflow-operator-strip", styles)

    def test_new_library_intake_has_a_short_safe_path(self) -> None:
        template = (ROOT / "src" / "lib_guard" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "lib_guard" / "web" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="library-add-apply" type="checkbox" checked', template)
        self.assertIn('id="library-add-refresh" type="checkbox" checked', template)
        self.assertIn("登记并加入目录", template)
        self.assertIn("只有一个版本也可以登记；登记后先扫描", template)
        self.assertIn("发现候选库适合未知库根", template)
        self.assertIn("单版本和多版本候选都需要勾选确认", template)
        self.assertIn("使用此候选", script)
        self.assertIn("prefillLibraryAddFromCandidate", script)
        self.assertIn("loadLibraries(preferredLibrary = '')", script)
        self.assertIn("completedJob?.registeredLibrary", script)
        self.assertIn("registeredLibrary: action === 'library-add' ? payload.library_id : ''", script)
        self.assertIn('id="library-add-feedback"', template)
        self.assertIn("showLibraryAddFeedback", script)

    def test_desktop_console_defers_inactive_evidence_and_supports_skip_navigation(self) -> None:
        template = (ROOT / "src" / "lib_guard" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "lib_guard" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "src" / "lib_guard" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('<a class="skip-link" href="#workspace-main">跳到主内容</a>', template)
        self.assertIn('<main id="workspace-main" class="workspace" tabindex="-1">', template)
        self.assertIn(".skip-link", styles)
        self.assertIn(".button-small { min-height: 32px;", styles)
        self.assertIn(".workflow-context-item span { color: var(--muted); font-size: 11px;", styles)
        self.assertIn(".version-link { min-height: 32px;", styles)
        self.assertIn(".zone-kicker { display: block; color: var(--teal); font-size: 11px;", styles)
        self.assertIn("font-size: 11px; font-weight: 850; white-space: nowrap;", styles)
        self.assertIn("font-size: 11px; font-weight: 800;", styles)
        self.assertIn('title="${escapeHtml(item.library_name)}"', script)
        self.assertIn("fileChangesLoadedKey", script)
        self.assertIn("fileTreeLoadedKey", script)
        self.assertIn("refreshActiveEvidenceForSelectedVersion", script)
        self.assertIn("切换到“变化清单”后读取对比证据", script)
        self.assertIn("切换到“文件结构”后读取扫描清单", script)
        self.assertIn("暂无文件变化证据", script)
        self.assertIn("main?.focus()", script)
        self.assertIn("data-retry-file-tree", script)
        self.assertIn("data-retry-file-changes", script)
        self.assertNotIn("await Promise.all([\n      refreshFileChangesForSelectedVersion(requestId),\n      refreshFileTreeForSelectedVersion(requestId),\n    ]);", script)

    def test_desktop_shell_has_bounded_chinese_workbench_sections(self) -> None:
        template = (ROOT / "src" / "lib_guard" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "lib_guard" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "src" / "lib_guard" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        for label in (
            "库目录",
            "版本列表",
            "版本工作表",
            "事实状态",
            "当前可用版本",
            "待扫描/补扫",
            "生成处理建议",
            "生成处理计划",
            "运行与默认配置",
            "先按本次设置试跑",
            "工作区默认值",
            "默认原始库根",
            "最少版本数",
            "保存为默认",
            "扫描证据",
            "证据读取",
            "版本对比",
            "页面输出",
            "扫描或对比后刷新版本详情页",
            "完整内容证据会读取文件内容，可能明显变慢",
            "仅生成扫描和对比事实，不刷新页面",
            "包类型修正",
            "设为当前可用版本",
            "版本概览",
            "当前版本上下文",
            "当前版本处理范围",
            "运行反馈",
            "版本与交付动作",
            "文件核对",
            "变化清单",
            "管理与配置",
            "新版本接入",
            "库与审查管理",
            "查看全部工作清单",
            "发现候选库",
            "候选库",
            "登记已选库",
            "勾选筛选结果",
            "发现范围设置",
            "应用库登记",
            "深度文件对比",
            "文件结构",
            "复制源路径",
            "复制所选路径",
            "选择筛选结果",
            "清空选择",
            "变化类型",
            "视图类型",
            "运行文件级对比",
            "审查门禁",
            "审查记录包",
            "回退当前可用版本",
            "执行预定义动作",
            "浏览目录",
            "使用当前目录",
        ):
            self.assertIn(label, template)
        self.assertIn('class="settings-disclosure panel"', template)
        self.assertIn('class="settings-section"', template)
        self.assertIn('class="workspace-heading-main"', template)
        self.assertIn('class="job-log-details"', template)
        self.assertNotIn('class="job-log-details" open', template)
        self.assertIn('id="catalog-full"', template)
        self.assertIn('id="reviewer"', template)
        self.assertIn("action-card-workflow", template)
        self.assertIn("新版本接入", template)
        self.assertIn("action-deck", template)
        self.assertIn('class="control-zone"', template)
        self.assertIn('aria-label="版本与交付动作"', template)
        self.assertIn('aria-label="管理操作"', template)
        self.assertIn('id="flow-object-value"', template)
        self.assertIn('id="flow-facts-value"', template)
        self.assertIn('id="metric-effective"', template)
        self.assertIn('id="flow-release-value"', template)
        self.assertIn('class="inline-action-details"', template)
        self.assertIn("IP 使用判断", template)
        self.assertIn('colspan="7"', template)
        self.assertIn('id="registered-library-table-body"', template)
        self.assertIn('class="file-tree-filter-group"', template)
        self.assertIn('class="file-tree-action-group"', template)
        self.assertIn("版本列表", template)
        for label in (
            "全部版本",
            "待扫描",
            "待对比",
            "可审查",
            "当前可用",
            "发布受阻",
            "异常",
            "待处理优先",
            "最新版本优先",
            "最旧版本优先",
            "当前可用优先",
            "包类型",
            "对比基准",
            "证据状态",
            "变化摘要",
            "操作",
        ):
            self.assertIn(label, template)
        self.assertIn('id="version-sort"', template)
        self.assertIn('id="version-status-facets"', template)
        self.assertIn('class="version-table-shell"', template)
        self.assertIn("versionFacetCounts", script)
        self.assertIn("renderVersionFacets", script)
        self.assertIn("sortVersionsForDisplay", script)
        self.assertIn("data-version-facet", script)
        self.assertIn("library-item-signals", script)
        self.assertIn("待处理", script)
        self.assertIn("最新", script)
        self.assertIn(".version-status-facets", styles)
        self.assertIn(".library-item-signals", styles)
        self.assertIn('class="version-focus-strip"', template)
        self.assertIn('id="version-focus-target"', template)
        self.assertIn('id="version-focus-base"', template)
        self.assertIn('id="version-focus-effective"', template)
        self.assertIn('id="version-focus-facts"', template)
        self.assertIn("versionEvidenceChips", script)
        self.assertIn("versionRoleLabel", script)
        self.assertIn("versionRowActions", script)
        self.assertIn("发布受阻", script)
        self.assertIn("待扫描", script)
        self.assertIn("待对比", script)
        self.assertIn("可审查", script)
        self.assertIn("version-evidence-stack", styles)
        self.assertIn("版本与交付动作", template)
        self.assertIn("下一步", template)
        self.assertIn("id=\"action-deck\"", template)
        self.assertIn("id=\"registered-library-table-body\"", template)
        self.assertIn("已登记库", template)
        self.assertIn("候选库", template)
        self.assertIn("data-force-hash-type", template)
        self.assertIn("data-skip-hash-type", template)
        self.assertIn("deriveVersionTask", script)
        self.assertIn("renderRegisteredLibraries", script)
        self.assertIn("force_hash_file_types", script)
        self.assertIn("skip_hash_file_types", script)
        self.assertIn("renderActionDeckReadiness", script)
        self.assertIn("openVersionDetail", script)
        self.assertIn("scanFactLabel", script)
        self.assertIn("compareFactLabel", script)
        self.assertIn("扫描记录缺证据", script)
        self.assertIn("对比记录待验证", script)
        self.assertIn("需补扫", script)
        self.assertIn("const hasSuggestion", script)
        self.assertIn("workflowAction === 'window'", script)
        self.assertIn("当前还没有接入建议，请先生成处理建议。", script)
        self.assertNotIn("runReviewSequence", script)
        self.assertIn("loadLibraryCandidates", script)
        self.assertIn("selectedCandidateIds", script)
        self.assertIn("candidate_ids", script)
        self.assertIn("候选库表中勾选至少一个确认的库根", script)
        self.assertIn("candidate-table-wrap", styles)
        self.assertIn("max-height: 300px", styles)
        self.assertNotIn('data-command-action="library-accept"', template)
        self.assertIn("result.result_summary", script)

    def test_library_rail_has_asset_filters_and_dense_metadata(self) -> None:
        template = (ROOT / "src" / "lib_guard" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "lib_guard" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "src" / "lib_guard" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        for element_id in (
            "library-scope-filter",
            "library-kind-filter",
            "library-vendor-filter",
            "library-platform-filter",
            "library-facet-summary",
        ):
            self.assertIn(f'id="{element_id}"', template)
        for label in (
            "全部库",
            "有待处理",
            "发布受阻",
            "无当前可用",
            "候选待登记",
            "库类型",
            "厂商",
            "平台",
        ):
            self.assertIn(label, template)
        for symbol in (
            "libraryScopeCounts",
            "populateLibraryFilters",
            "libraryMatchesFilters",
            "renderLibraryFacetSummary",
            "libraryKindLabel",
            "libraryPlatformLabel",
            "library-meta-line",
        ):
            self.assertIn(symbol, script)
        for selector in (
            ".library-filter-grid",
            ".library-facet-summary",
            ".library-meta-line",
        ):
            self.assertIn(selector, styles)

    def test_library_management_is_presented_as_path_to_intake_flow(self) -> None:
        template = (ROOT / "src" / "lib_guard" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "lib_guard" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "src" / "lib_guard" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("库接入与维护", template)
        self.assertIn("从库路径到版本处理", template)
        self.assertIn('class="library-intake-playbook"', template)
        self.assertIn('data-ui-action="open-library-add"', template)
        self.assertIn('data-ui-action="focus-version-actions"', template)
        self.assertLess(template.index("添加新库"), template.index("目录与工作清单"))
        for label in (
            "已有明确库路径",
            "未知库根时发现候选",
            "应用正式目录",
            "选择版本后处理",
            "填写库根",
            "选中库后扫描",
            "库属性（可登记）",
            "登记后自动应用并刷新目录",
            "不会扫描，也不会切换当前可用版本",
            "发现起点",
            "建议正式库名",
            "只有一个版本的新库也会显示为待确认候选",
        ):
            self.assertIn(label, template)
        self.assertIn("openLibraryAddForm", script)
        self.assertIn("focusVersionActions", script)
        self.assertIn("candidate-discover-root", script)
        self.assertIn("suggested_library_id", script)
        self.assertIn("data-ui-action", script)
        self.assertIn(".library-intake-playbook", styles)
        self.assertIn(".command-action-strip", styles)
        self.assertIn("PASS_WITH_WARNING: '正式发布通过（有提醒）'", script)
        self.assertIn("选择版本后可以独立执行扫描、对比、深度文件核对、审查记录和发布检查。", script)
        self.assertIn("检查正式发布条件", template)
        self.assertIn("无可比基准", script)
        self.assertNotIn("建议动作</th>", template)
        self.assertNotIn("按当前基准依次执行扫描、对比、发布检查", template)
        self.assertIn("运行与默认配置", template)
        self.assertIn("scan-action-note", template)
        for action in (
            "worklist",
            "catalog-refresh",
            "library-discover",
            "library-apply",
            "library-add",
            "file-diff",
            "review-gate",
            "review-packet",
            "effective-rollback",
            "action-file",
        ):
            self.assertIn(f'data-command-action="{action}"', template)
        self.assertIn("runCommand('library-accept')", script)
        self.assertIn("data-command-action", script)
        self.assertIn("正式发布待处理", script)
        self.assertIn("releaseChip", script)
        self.assertIn("不代表 IP 使用失败", script)
        for element_id in ("job-observation", "job-stage", "job-percent", "job-elapsed", "job-progress-bar", "job-log-tail"):
            self.assertIn(f'id="{element_id}"', template)
        self.assertIn('id="open-file-diff"', template)
        self.assertIn('id="open-review-actions"', template)
        self.assertIn('class="action-deck-grid"', template)
        self.assertIn('id="base-version-options"', template)
        self.assertIn("renderJobObservation", script)
        self.assertIn("updateSettingsSummary", script)
        self.assertIn("flow-facts-value", script)
        self.assertNotIn("flow-decision-value", template + script)
        self.assertIn("扫描 ${scanFactLabel", script)
        self.assertNotIn("versionStageStrip", script)
        self.assertNotIn("version-stage-strip", styles)
        self.assertIn("终端输出", template)
        self.assertIn("发布受阻", template)
        self.assertNotIn('data-sequence-step="release-check"', template)
        self.assertNotIn("第 3 步 / 3：发布检查", script)
        self.assertIn("读取中", script)
        self.assertIn("失败原因：", script)
        self.assertIn("当前显示", script)
        self.assertIn("VERSION_RENDER_BATCH", script)
        self.assertIn("versionRenderLimit", script)
        self.assertIn("再显示 ${VERSION_RENDER_BATCH} 个", script)
        self.assertIn("继续读取版本", script)
        self.assertIn("filteredVersions", script)
        self.assertIn("if (!append || selectedChanged) resetSelectedVersionEvidence();", script)
        self.assertIn("接入建议文件无法读取", script)
        self.assertIn("生成接入建议", script)
        self.assertIn("超过 30 分钟", script)
        self.assertIn('value="candidate"', template)
        self.assertIn("是否可执行", template)
        self.assertIn("已连接", script)
        self.assertIn("/api/libraries", script)
        self.assertIn("overflow", styles)
        self.assertIn('class="main-column"', template)
        self.assertIn(".main-column { min-width: 0; display: grid;", styles)
        self.assertIn(".side-stack { position: sticky;", styles)
        self.assertIn("max-height: calc(100vh - 92px);", styles)
        for element_id in ("file-change-body", "file-change-kind-filter", "file-change-type-filter", "linked-old-relpath", "linked-new-relpath", "linked-file-diff-button"):
            self.assertIn(f'id="{element_id}"', template)
        self.assertIn('id="file-change-page-summary"', template)
        self.assertIn('id="load-more-file-changes"', template)
        for element_id in ("library-path-picker", "path-browser-list", "path-browser-current"):
            self.assertIn(f'id="{element_id}"', template)
        self.assertIn("file-changes", script)
        self.assertIn("/api/path-children", script)
        self.assertIn("/file-tree", script)
        self.assertIn("selectedFileTreePaths", script)
        self.assertIn("buildFileTree", script)
        self.assertIn("scheduleFileTreeRender", script)
        self.assertIn("display_path", script)
        self.assertIn("file-tree-scroll", styles)
        self.assertIn(".workspace-tabs { display: flex;", styles)
        self.assertIn(".workspace-tab.is-active", styles)
        self.assertIn(".action-panel { min-width: 0; display: block;", styles)
        self.assertIn(".control-zone { margin-top: 24px;", styles)
        self.assertNotIn('class="metric-strip"', template)
        self.assertIn("activateWorkspaceTab", script)
        self.assertIn("fileChangeLimit: 100", script)
        self.assertIn("URLSearchParams", script)
        self.assertIn("history.replaceState", script)
        self.assertIn("fileChangeTotal", script)
        self.assertIn("fileChangeFacetCounts", script)
        self.assertIn("data-file-change-facet", script)
        self.assertIn('id="file-change-facets"', template)
        self.assertIn("文件变化总览", template)
        self.assertIn("show-settings-button", template)
        self.assertLess(template.index('class="panel version-panel"'), template.index('id="action-deck"'))
        self.assertLess(template.index('id="action-deck"'), template.index('class="content-grid"'))
        self.assertLess(template.index('class="panel version-panel"'), template.index('class="panel evidence-workspace"'))
        self.assertLess(template.index('class="panel evidence-workspace"'), template.index('class="panel run-panel"'))
        self.assertGreater(template.index('class="panel run-panel"'), template.index('class="side-stack"'))
        self.assertIn("old_relpath", script)
        self.assertIn("deep_diff_available", script)
        self.assertNotIn("!rows.some((item) => item.version_id === state.selectedVersion.version_id)", script)
        self.assertNotIn('<h3>当前版本</h3>', template)
        self.assertNotIn('<main class="workspace" aria-live="polite">', template)
        self.assertNotIn("run-shell", template + script)


if __name__ == "__main__":
    unittest.main()
