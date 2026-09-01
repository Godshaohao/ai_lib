from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class WebUiContractTest(unittest.TestCase):
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
            "IP 使用判断",
            "变化摘要",
            "当前有效版",
            "下一步预演",
            "接入计划",
            "本次运行设置",
            "默认值来自工作区配置",
            "扫描证据",
            "证据读取",
            "版本对比",
            "页面输出",
            "完整内容证据会读取文件内容，可能明显变慢",
            "仅生成扫描和对比事实，不刷新页面",
            "包类型修正",
            "接受候选有效版",
            "版本概览",
            "当前版本上下文",
            "当前版本处理范围",
            "事实更新",
            "运行反馈",
            "版本处理",
            "文件核对",
            "变化清单",
            "管理与配置",
            "接入与有效版",
            "库与审查管理",
            "查看全部工作清单",
            "发现候选库",
            "合并候选库登记",
            "应用库登记",
            "手动文件核对",
            "变化清单没有可配对记录",
            "联动文件核对",
            "文件结构",
            "复制源路径",
            "复制所选文件清单",
            "选择当前筛选",
            "清空选择",
            "变化类型",
            "视图类型",
            "运行深度核对",
            "审查门禁",
            "审查记录包",
            "回退有效组合",
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
        self.assertIn("workflow-disclosure", template)
        self.assertIn("接入与有效版", template)
        self.assertIn("action-disclosure", template)
        self.assertIn('class="control-zone"', template)
        self.assertIn('aria-label="事实更新"', template)
        self.assertIn('aria-label="管理操作"', template)
        self.assertIn('id="flow-object-value"', template)
        self.assertIn('id="flow-facts-value"', template)
        self.assertIn('id="flow-decision-value"', template)
        self.assertIn('id="flow-release-value"', template)
        self.assertIn('class="write-actions"', template)
        self.assertIn("IP 使用判断", template)
        self.assertIn("变化摘要", template)
        self.assertIn("生成使用判断", template)
        self.assertIn("选择版本后可生成使用判断；正式发布检查单独执行。", script)
        self.assertIn("检查正式发布条件", template)
        self.assertIn("首版只生成自身扫描事实", template)
        self.assertNotIn("建议动作</th>", template)
        self.assertNotIn("按当前基准依次执行扫描、对比、发布检查", template)
        self.assertIn("调整运行设置", template)
        self.assertIn("action-availability", template)
        for action in (
            "worklist",
            "catalog-refresh",
            "library-discover",
            "library-accept",
            "library-apply",
            "library-add",
            "file-diff",
            "review-gate",
            "review-packet",
            "effective-rollback",
            "action-file",
        ):
            self.assertIn(f'data-command-action="{action}"', template)
        self.assertIn("data-command-action", script)
        self.assertIn("正式发布待处理", script)
        self.assertIn("releaseChip", script)
        self.assertIn("不代表 IP 使用失败", script)
        for element_id in ("job-observation", "job-stage", "job-percent", "job-elapsed", "job-progress-bar", "job-log-tail"):
            self.assertIn(f'id="{element_id}"', template)
        self.assertIn('id="version-action-disclosure"', template)
        self.assertIn('class="action-disclosure single-action-details"', template)
        self.assertIn('按步骤执行与调整基准', template)
        self.assertIn('id="base-version-options"', template)
        self.assertIn("renderJobObservation", script)
        self.assertIn("updateSettingsSummary", script)
        self.assertIn("flow-facts-value", script)
        self.assertIn("扫描 ${statusLabel", script)
        self.assertIn("终端输出（仅显示尾部）", template)
        self.assertIn("需要技术处理", template)
        self.assertNotIn('data-sequence-step="release-check"', template)
        self.assertNotIn("第 3 步 / 3：发布检查", script)
        self.assertIn("读取中", script)
        self.assertIn("失败原因：", script)
        self.assertIn("已显示", script)
        self.assertIn("接入窗口文件损坏", script)
        self.assertIn("超过 30 分钟", script)
        self.assertIn('value="candidate"', template)
        self.assertNotIn("可执行", template + script)
        self.assertIn("已连接", script)
        self.assertIn("/api/libraries", script)
        self.assertIn("overflow", styles)
        self.assertIn('class="main-column"', template)
        self.assertIn(".main-column { min-width: 0; display: grid;", styles)
        self.assertIn(".side-stack { position: sticky;", styles)
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
        self.assertIn("activateWorkspaceTab", script)
        self.assertIn("fileChangeLimit: 100", script)
        self.assertIn("show-settings-button", template)
        self.assertLess(template.index('class="panel version-panel"'), template.index('class="panel action-panel"'))
        self.assertLess(template.index('class="panel action-panel"'), template.index('class="panel evidence-workspace"'))
        self.assertLess(template.index('class="panel evidence-workspace"'), template.index('class="panel run-panel"'))
        self.assertIn("old_relpath", script)
        self.assertIn("deep_diff_available", script)
        self.assertNotIn("!rows.some((item) => item.version_id === state.selectedVersion.version_id)", script)
        self.assertNotIn('<h3>当前版本</h3>', template)
        self.assertNotIn('<main class="workspace" aria-live="polite">', template)
        self.assertNotIn("run-shell", template + script)


if __name__ == "__main__":
    unittest.main()
