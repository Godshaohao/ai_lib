(() => {
  const state = {
    libraries: [],
    selectedLibrary: null,
    versions: [],
    selectedVersion: null,
    workspace: null,
    versionQuery: '',
    versionFilter: 'all',
    versionTotal: 0,
    versionHasMore: false,
    versionsLoadingMore: false,
    pollTimer: null,
    activeAction: null,
    libraryRequestId: 0,
    librariesLoading: false,
    libraryLoadError: '',
    versionsLoading: false,
    versionLoadError: '',
    activeJob: null,
    jobWaiter: null,
    sequenceRunning: false,
    libraryLoadRequestId: 0,
    pollStartedAt: 0,
    pollInFlight: false,
    fileChanges: [],
    fileChangesLoading: false,
    fileChangesError: '',
    fileChangesLoadedKey: '',
    fileChangeBaseVersion: '',
    selectedFileChangeIndex: null,
    fileChangeRequestId: 0,
    fileChangeLimit: 100,
    fileTreeFiles: [],
    fileTreeRootPath: '',
    fileTreeLoading: false,
    fileTreeError: '',
    fileTreeLoadedKey: '',
    fileTreeRequestId: 0,
    selectedFileTreePaths: new Set(),
    pathBrowserPath: '',
    pathBrowserParent: '',
    pathBrowserLoading: false,
    pathBrowserError: '',
    pathBrowserRequestId: 0,
    lastActionVersion: '',
    workspaceTab: 'tree',
  };
  const $ = (id) => document.getElementById(id);
  const JOB_TIMEOUT_MS = 30 * 60 * 1000;

  function activateWorkspaceTab(name, { focus = false } = {}) {
    const tabs = Array.from(document.querySelectorAll('[data-workspace-tab]'));
    const nextTab = tabs.find((tab) => tab.dataset.workspaceTab === name) || tabs[0];
    if (!nextTab) return;
    state.workspaceTab = nextTab.dataset.workspaceTab;
    tabs.forEach((tab) => {
      const active = tab === nextTab;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      tab.tabIndex = active ? 0 : -1;
    });
    document.querySelectorAll('[data-workspace-panel]').forEach((panel) => {
      panel.classList.toggle('hidden', panel.dataset.workspacePanel !== state.workspaceTab);
    });
    if (state.workspaceTab === 'changes') renderFileChangeWorkbench();
    refreshActiveEvidenceForSelectedVersion().catch(() => {});
    if (focus) nextTab.focus();
  }

  function selectedEvidenceKey() {
    const version = state.selectedVersion?.version_id;
    return state.selectedLibrary && version ? `${state.selectedLibrary}\n${version}` : '';
  }

  function resetSelectedVersionEvidence() {
    state.fileChangeRequestId += 1;
    state.fileChanges = [];
    state.fileChangesLoading = false;
    state.fileChangesError = '';
    state.fileChangesLoadedKey = '';
    state.fileChangeBaseVersion = '';
    state.selectedFileChangeIndex = null;
    state.fileChangeLimit = 100;
    state.fileTreeRequestId += 1;
    state.fileTreeFiles = [];
    state.fileTreeRootPath = '';
    state.fileTreeLoading = false;
    state.fileTreeError = '';
    state.fileTreeLoadedKey = '';
    state.selectedFileTreePaths = new Set();
    renderFileChangeWorkbench();
    renderFileTree();
  }

  async function refreshActiveEvidenceForSelectedVersion(requestId = state.libraryRequestId) {
    const key = selectedEvidenceKey();
    if (!key) return;
    if (state.workspaceTab === 'changes') {
      if (state.fileChangesLoading || state.fileChangesLoadedKey === key) return;
      await refreshFileChangesForSelectedVersion(requestId);
      return;
    }
    if (state.fileTreeLoading || state.fileTreeLoadedKey === key) return;
    await refreshFileTreeForSelectedVersion(requestId);
  }

  const STATUS_LABELS = {
    PASS: '通过',
    PASSED: '通过',
    SCANNED: '已扫描',
    DIFF_DONE: '已对比',
    CHECKED: '已检查',
    SAME: '无变化',
    CHANGED: '有变化',
    COMPLETED: '已完成',
    COMPLETE: '已完成',
    RUNNING: '运行中',
    QUEUED: '排队中',
    PENDING: '待处理',
    NOT_RUN: '未执行',
    NOT_SCANNED: '未扫描',
    NOT_APPLICABLE: '不适用',
    STALE_SCAN: '扫描已过期',
    DOC_UPDATE: '文档更新',
    NEEDS_PACKAGE_CONFIRM: '待确认包类型',
    NEEDS_BASE_CONFIRM: '待确认基准',
    NO_NEW_VERSION: '没有新版本',
    CONNECTED: '已连接',
    NO_DIFF: '无变化',
    REVIEW: '待审查',
    UNKNOWN: '未知',
    FAILED: '失败',
    FAIL: '失败',
    BLOCKED: '已阻塞',
  };
  const RELEASE_STATUS_LABELS = {
    BLOCK: '正式发布待处理',
    BLOCKED: '正式发布待处理',
    RELEASE_BLOCKED: '正式发布待处理',
    FAILED: '发布检查失败',
    FAIL: '发布检查失败',
    RELEASE_VERIFY_FAILED: '发布检查失败',
    READY: '正式发布通过',
    RELEASE_READY: '正式发布通过',
    APPLIED: '已正式发布',
    RELEASE_APPLIED: '已正式发布',
    UNKNOWN: '未检查',
    NOT_RUN: '未检查',
    NOT_APPLICABLE: '不适用',
  };
  const PACKAGE_LABELS = {
    FULL_PACKAGE: '完整包',
    PARTIAL_UPDATE: '增量更新',
    FIX: '修订包',
    HOTFIX: '紧急修订',
    DOC_UPDATE: '文档更新',
    UNKNOWN_PACKAGE: '未识别',
  };
  const STAGE_LABELS = {
    stable: '稳定版',
    final: '正式版',
    dated: '已登记',
    candidate: '候选版',
    'ad-hoc': '临时版',
    unknown: '未标注',
  };
  const FILE_CHANGE_LABELS = {
    ADDED: '新增',
    REMOVED: '删除',
    CHANGED: '内容变化',
    PATH_CHANGED: '路径变化',
  };
  const FILE_TYPE_LABELS = {
    lef: 'LEF', liberty: 'Liberty', lib: 'Lib', verilog: 'Verilog', systemverilog: 'SystemVerilog',
    gds: 'GDS', oas: 'OAS', db: 'DB', spef: 'SPEF', cdl: 'CDL', spice: 'SPICE', sp: 'SP',
    sdc: 'SDC', upf: 'UPF', cpf: 'CPF', unknown: '未知',
  };
  const JOB_STAGE_LABELS = {
    '1/7 walk': '1/7 文件遍历',
    '2/7 classify': '2/7 文件分类',
    '3/7 hash': '3/7 内容取证',
    '4/7 parse': '4/7 解析任务',
    '5/7 signatures': '5/7 建立签名',
    '6/7 integrity': '6/7 完整性检查',
    '7/7 write': '7/7 写入扫描结果',
    start: '准备运行',
    finish: '已结束',
    waiting: '等待子任务输出',
  };

  async function getJson(url, options) {
    const response = await fetch(url, options);
    const body = await response.text();
    let payload;
    try {
      payload = body ? JSON.parse(body) : {};
    } catch (error) {
      throw new Error(response.ok ? '服务返回了无法读取的数据。' : `请求失败：${response.status}`);
    }
    if (!response.ok) throw new Error(payload.error || `请求失败：${response.status}`);
    return payload;
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  }

  function statusLabel(value) {
    const displayValue = String(value || 'UNKNOWN').trim();
    if (/[\u3400-\u9fff]/.test(displayValue)) return displayValue;
    const raw = displayValue.toUpperCase();
    return STATUS_LABELS[raw] || `未知状态（${String(value || 'UNKNOWN')}）`;
  }

  function packageLabel(value) {
    const raw = String(value || 'UNKNOWN_PACKAGE');
    return PACKAGE_LABELS[raw] || `未知（${raw}）`;
  }

  function stageLabel(value) {
    const raw = String(value || 'unknown').toLowerCase();
    return STAGE_LABELS[raw] || `未知（${raw}）`;
  }

  function jobStageLabel(value) {
    const raw = String(value || 'waiting');
    return JOB_STAGE_LABELS[raw] || raw;
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  function statusClass(value) {
    const text = String(value || '').toUpperCase();
    if (text.includes('PASS') || text === 'SAME' || text.includes('COMPLETE')) return 'status-good';
    if (text.includes('BLOCK') || text.includes('FAIL')) return 'status-bad';
    if (text.includes('PENDING') || text.includes('RUNNING') || text.includes('QUEUED') || text === 'NOT_SCANNED' || text === 'NOT_RUN') return 'status-warn';
    return 'status-neutral';
  }

  function chip(value) {
    return `<span class="status-chip ${statusClass(value)}">${escapeHtml(statusLabel(value))}</span>`;
  }

  function releaseLabel(value) {
    const raw = String(value || 'UNKNOWN').toUpperCase();
    return RELEASE_STATUS_LABELS[raw] || `正式发布：${statusLabel(raw)}`;
  }

  function releaseStatusClass(value) {
    const raw = String(value || 'UNKNOWN').toUpperCase();
    if (raw.includes('FAIL')) return 'status-bad';
    if (raw.includes('BLOCK')) return 'status-warn';
    if (raw.includes('PASS') || raw.includes('READY') || raw.includes('APPLIED')) return 'status-good';
    return 'status-neutral';
  }

  function releaseChip(value) {
    return `<span class="status-chip ${releaseStatusClass(value)}" title="正式发布状态只表示发布门禁，不代表 IP 使用失败">${escapeHtml(releaseLabel(value))}</span>`;
  }

  function fileChangeLabel(value) {
    return FILE_CHANGE_LABELS[String(value || '').toUpperCase()] || '未知变化';
  }

  function fileTypeLabel(value) {
    const raw = String(value || 'unknown').toLowerCase();
    return FILE_TYPE_LABELS[raw] || raw.toUpperCase();
  }

  function visibleFileTreeFiles() {
    const query = String($('file-tree-filter')?.value || '').trim().toLowerCase();
    const type = String($('file-tree-type-filter')?.value || 'all');
    return state.fileTreeFiles.filter((row) => {
      if (type !== 'all' && row.file_type !== type) return false;
      return !query || `${row.path} ${row.role || ''} ${row.domain || ''}`.toLowerCase().includes(query);
    });
  }

  function renderFileTreeTypes() {
    const select = $('file-tree-type-filter');
    if (!select) return;
    const selected = select.value || 'all';
    const types = [...new Set(state.fileTreeFiles.map((row) => row.file_type).filter(Boolean))].sort();
    select.innerHTML = '<option value="all">全部类型</option>' + types.map((type) => `<option value="${escapeHtml(type)}">${escapeHtml(fileTypeLabel(type))}</option>`).join('');
    select.value = types.includes(selected) ? selected : 'all';
  }

  function buildFileTree(files) {
    const root = { dirs: new Map(), files: [] };
    files.forEach((file) => {
      const parts = String(file.display_path || file.path || '').split('/').filter(Boolean);
      if (!parts.length) return;
      let node = root;
      parts.slice(0, -1).forEach((part) => {
        if (!node.dirs.has(part)) node.dirs.set(part, { dirs: new Map(), files: [] });
        node = node.dirs.get(part);
      });
      node.files.push(file);
    });
    return root;
  }

  function renderFileTreeNode(node, depth = 0) {
    const directories = [...node.dirs.entries()].sort(([a], [b]) => a.localeCompare(b));
    const folders = directories.map(([name, child]) => {
      const count = countTreeFiles(child);
      return `<details class="file-tree-dir" ${depth < 1 ? 'open' : ''}><summary><span class="file-tree-folder-icon" aria-hidden="true">▸</span><strong>${escapeHtml(name)}</strong><span class="file-tree-count">${count}</span></summary><div class="file-tree-children">${renderFileTreeNode(child, depth + 1)}</div></details>`;
    }).join('');
    const fileRows = node.files.sort((a, b) => a.name.localeCompare(b.name)).map((file) => {
      const selected = state.selectedFileTreePaths.has(file.path);
      const detail = [fileTypeLabel(file.file_type), formatBytes(file.size_bytes), file.evidence, file.role].filter(Boolean).join(' · ');
      return `<label class="file-tree-file ${selected ? 'selected' : ''}" title="${escapeHtml(file.path)}"><input type="checkbox" data-tree-file="${escapeHtml(file.path)}" ${selected ? 'checked' : ''}><span class="file-tree-file-name">${escapeHtml(file.name)}</span><span class="file-tree-file-meta">${escapeHtml(detail)}</span></label>`;
    }).join('');
    return folders + fileRows;
  }

  function countTreeFiles(node) {
    return node.files.length + [...node.dirs.values()].reduce((sum, child) => sum + countTreeFiles(child), 0);
  }

  function updateFileTreeControls(visible) {
    const summary = $('file-tree-summary');
    const copyRoot = $('copy-library-root');
    const copySelected = $('copy-selected-paths');
    const selectVisible = $('select-visible-files');
    const clearSelected = $('clear-selected-files');
    if (!summary) return;
    copyRoot.disabled = !state.fileTreeRootPath;
    copySelected.disabled = state.selectedFileTreePaths.size === 0;
    selectVisible.disabled = !visible.length;
    clearSelected.disabled = state.selectedFileTreePaths.size === 0;
    if (state.fileTreeFiles.length && !state.fileTreeLoading && !state.fileTreeError) {
      summary.textContent = `显示 ${visible.length} / ${state.fileTreeFiles.length} 个文件 · 已选 ${state.selectedFileTreePaths.size} 个 · 来源：扫描文件清单`;
    }
  }

  function renderFileTree() {
    const tree = $('file-tree');
    const summary = $('file-tree-summary');
    if (!tree || !summary) return;
    renderFileTreeTypes();
    const visible = visibleFileTreeFiles();
    updateFileTreeControls(visible);
    const evidenceKey = selectedEvidenceKey();
    const evidenceDeferred = Boolean(evidenceKey)
      && !state.fileTreeLoading
      && !state.fileTreeError
      && state.fileTreeLoadedKey !== evidenceKey;
    if (evidenceDeferred) {
      summary.textContent = '按需读取';
      tree.innerHTML = '<p class="empty-note">切换到“文件结构”后读取扫描清单。</p>';
      return;
    }
    if (state.fileTreeLoading) {
      summary.textContent = '正在读取扫描文件清单…';
      tree.innerHTML = '<p class="empty-note">正在读取文件结构…</p>';
      return;
    }
    if (state.fileTreeError) {
      summary.textContent = state.fileTreeError;
      tree.innerHTML = '<div class="empty-note">暂时无法显示文件结构。 <button class="button button-secondary button-small" data-retry-file-tree type="button">重新读取</button></div>';
      tree.querySelector('[data-retry-file-tree]')?.addEventListener('click', () => {
        refreshFileTreeForSelectedVersion().catch((error) => showError(error.message));
      });
      return;
    }
    if (!state.fileTreeFiles.length) {
      summary.textContent = '当前版本没有可显示的扫描文件清单。';
      tree.innerHTML = '<p class="empty-note">完成扫描后，这里显示当前版本的目录结构。</p>';
      return;
    }
    updateFileTreeControls(visible);
    tree.innerHTML = visible.length ? renderFileTreeNode(buildFileTree(visible)) : '<p class="empty-note">没有符合筛选条件的文件。</p>';
    tree.querySelectorAll('[data-tree-file]').forEach((input) => input.addEventListener('change', () => {
      if (input.checked) state.selectedFileTreePaths.add(input.dataset.treeFile);
      else state.selectedFileTreePaths.delete(input.dataset.treeFile);
      input.closest('.file-tree-file')?.classList.toggle('selected', input.checked);
      updateFileTreeControls(visibleFileTreeFiles());
    }));
  }

  let fileTreeRenderTimer = null;
  function scheduleFileTreeRender() {
    clearTimeout(fileTreeRenderTimer);
    fileTreeRenderTimer = setTimeout(() => renderFileTree(), 180);
  }

  async function copyText(value) {
    const text = String(value || '');
    if (!text) return false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
      const area = document.createElement('textarea');
      area.value = text;
      document.body.appendChild(area);
      area.select();
      const copied = document.execCommand('copy');
      area.remove();
      return copied;
    } catch (error) {
      return false;
    }
  }

  async function refreshFileTreeForSelectedVersion(requestId = state.libraryRequestId) {
    const version = state.selectedVersion?.version_id;
    const library = state.selectedLibrary;
    const request = ++state.fileTreeRequestId;
    state.fileTreeFiles = [];
    state.fileTreeRootPath = '';
    state.fileTreeError = '';
    state.selectedFileTreePaths = new Set();
    if (!library || !version) {
      state.fileTreeLoading = false;
      renderFileTree();
      return;
    }
    state.fileTreeLoading = true;
    renderFileTree();
    try {
      const payload = await getJson(`/api/libraries/${encodeURIComponent(library)}/versions/${encodeURIComponent(version)}/file-tree`);
      if (requestId !== state.libraryRequestId || request !== state.fileTreeRequestId || library !== state.selectedLibrary || version !== state.selectedVersion?.version_id) return;
      state.fileTreeFiles = Array.isArray(payload.files) ? payload.files : [];
      state.fileTreeRootPath = String(payload.root_path || '');
      state.fileTreeLoading = false;
      state.fileTreeLoadedKey = `${library}\n${version}`;
      if (payload.status !== 'PASS') state.fileTreeError = String(payload.message || '扫描文件清单不可用。');
      renderFileTree();
    } catch (error) {
      if (requestId !== state.libraryRequestId || request !== state.fileTreeRequestId) return;
      state.fileTreeLoading = false;
      state.fileTreeError = `读取文件结构失败：${error.message}`;
      renderFileTree();
    }
  }

  async function copySelectedFileTreePaths() {
    const copied = await copyText([...state.selectedFileTreePaths].join('\n'));
    $('file-tree-summary').textContent = copied ? `已复制 ${state.selectedFileTreePaths.size} 个相对路径。` : '复制失败，请检查浏览器剪贴板权限。';
  }

  async function copyLibraryRootPath() {
    const copied = await copyText(state.fileTreeRootPath);
    $('file-tree-summary').textContent = copied ? '已复制当前版本库根路径。' : '复制失败，请检查浏览器剪贴板权限。';
  }

  function visibleFileChanges() {
    const query = String($('file-change-filter')?.value || '').trim().toLowerCase();
    const kind = String($('file-change-kind-filter')?.value || 'all');
    const type = String($('file-change-type-filter')?.value || 'all');
    return state.fileChanges
      .map((row, index) => ({ row, index }))
      .filter(({ row }) => {
        if (kind !== 'all' && row.change !== kind) return false;
        if (type !== 'all' && row.file_type !== type) return false;
        if (!query) return true;
        return `${row.old_path || ''} ${row.new_path || ''}`.toLowerCase().includes(query);
      });
  }

  function renderFileChangeTypes() {
    const select = $('file-change-type-filter');
    if (!select) return;
    const selected = select.value || 'all';
    const types = [...new Set(state.fileChanges.map((row) => row.file_type).filter(Boolean))].sort();
    select.innerHTML = '<option value="all">全部类型</option>' + types.map((type) => `<option value="${escapeHtml(type)}">${escapeHtml(fileTypeLabel(type))}</option>`).join('');
    select.value = types.includes(selected) ? selected : 'all';
  }

  function renderFileChangeWorkbench() {
    const body = $('file-change-body');
    const summary = $('file-change-summary');
    const selectionLabel = $('file-change-selected-label');
    const oldInput = $('linked-old-relpath');
    const newInput = $('linked-new-relpath');
    const typeInput = $('linked-file-type');
    const runButton = $('linked-file-diff-button');
    const forceInput = $('linked-force-large');
    const note = $('file-change-note');
    const pageSummary = $('file-change-page-summary');
    const loadMore = $('load-more-file-changes');
    if (!body || !summary || !selectionLabel || !oldInput || !newInput || !typeInput || !runButton || !forceInput || !note) return;
    renderFileChangeTypes();
    const evidenceKey = selectedEvidenceKey();
    const evidenceDeferred = Boolean(evidenceKey)
      && !state.fileChangesLoading
      && !state.fileChangesError
      && state.fileChangesLoadedKey !== evidenceKey;
    if (pageSummary) pageSummary.textContent = state.fileChangesLoading ? '正在读取变化清单' : '尚未读取变化清单';
    if (loadMore) loadMore.classList.add('hidden');
    if (evidenceDeferred) {
      summary.textContent = '按需读取';
      body.innerHTML = '<tr><td colspan="6" class="empty-cell">切换到“变化清单”后读取对比证据。</td></tr>';
    } else if (state.fileChangesLoading) {
      summary.textContent = '正在读取对比证据';
      body.innerHTML = '<tr><td colspan="6" class="empty-cell">正在读取文件变化…</td></tr>';
    } else if (state.fileChangesError) {
      summary.textContent = '读取失败';
      body.innerHTML = `<tr><td colspan="6" class="empty-cell">${escapeHtml(state.fileChangesError)} <button class="button button-secondary button-small" data-retry-file-changes type="button">重新读取</button></td></tr>`;
    } else {
      const filtered = visibleFileChanges();
      const visibleRows = filtered.slice(0, state.fileChangeLimit);
      summary.textContent = `${state.fileChanges.length} 条变化${state.fileChangeBaseVersion ? ` · 基准 ${state.fileChangeBaseVersion}` : ''}`;
      if (pageSummary) {
        pageSummary.textContent = !state.fileChanges.length
          ? '暂无文件变化证据'
          : (filtered.length ? `显示 ${visibleRows.length} / ${filtered.length} 条` : '没有符合筛选条件的变化');
      }
      if (loadMore) loadMore.classList.toggle('hidden', visibleRows.length >= filtered.length);
      if (!filtered.length) {
        body.innerHTML = `<tr><td colspan="6" class="empty-cell">${state.fileChanges.length ? '没有符合筛选条件的文件。' : '没有可用的文件变化证据；请先完成版本对比。'}</td></tr>`;
      } else {
        body.innerHTML = visibleRows.map(({ row, index }) => {
          const deep = row.deep_diff_available;
          const selected = state.selectedFileChangeIndex === index;
          return `<tr class="file-change-row ${selected ? 'selected' : ''}">
            <td>${escapeHtml(fileChangeLabel(row.change))}</td>
            <td>${escapeHtml(fileTypeLabel(row.file_type))}</td>
            <td class="path-cell" title="${escapeHtml(row.old_path || '无')}">${escapeHtml(row.old_path || '无')}</td>
            <td class="path-cell" title="${escapeHtml(row.new_path || '无')}">${escapeHtml(row.new_path || '无')}</td>
            <td>${escapeHtml(row.evidence_mode || '文件级')}</td>
            <td><button class="button button-secondary button-small" data-file-change-index="${index}" type="button" ${deep ? '' : 'disabled'}>${deep ? '选择核对' : '无成对文件'}</button></td>
          </tr>`;
        }).join('');
      }
    }
    document.querySelector('[data-retry-file-changes]')?.addEventListener('click', () => {
      refreshFileChangesForSelectedVersion().catch((error) => showError(error.message));
    });
    document.querySelectorAll('[data-file-change-index]').forEach((button) => button.addEventListener('click', () => selectFileChange(Number(button.dataset.fileChangeIndex))));
    const selected = Number.isInteger(state.selectedFileChangeIndex) ? state.fileChanges[state.selectedFileChangeIndex] : null;
    oldInput.value = selected?.old_path || '';
    newInput.value = selected?.new_path || '';
    typeInput.value = selected ? fileTypeLabel(selected.file_type) : '';
    selectionLabel.textContent = selected
      ? `${fileChangeLabel(selected.change)} · ${fileTypeLabel(selected.file_type)}`
      : '尚未选择可比对文件';
    const canRun = Boolean(selected?.deep_diff_available)
      && !state.activeAction
      && (!selected.requires_force_large || forceInput.checked);
    runButton.disabled = !canRun;
    forceInput.disabled = !selected || !selected.requires_force_large;
    if (!selected) {
      forceInput.checked = false;
      note.textContent = '新增、删除或未知类型没有成对文件，不能从这里启动深度核对。';
    } else if (!selected.deep_diff_available) {
      note.textContent = '这条记录缺少可成对核对的旧文件和新文件；请保留为变化证据。';
    } else if (selected.requires_force_large && !forceInput.checked) {
      note.textContent = '该类型默认只保留轻量证据；如确需读取完整内容，请勾选后再运行。';
    } else {
      note.textContent = '将使用已登记版本目录中的这两个文件，结果保留在最近运行中。';
    }
  }

  function selectFileChange(index) {
    if (!Number.isInteger(index) || !state.fileChanges[index]) return;
    state.selectedFileChangeIndex = index;
    const row = state.fileChanges[index];
    const force = $('linked-force-large');
    if (force) force.checked = false;
    renderFileChangeWorkbench();
    if (!row.deep_diff_available) {
      $('file-change-note').textContent = '这条记录没有成对文件，不能启动深度核对。';
    }
  }

  async function refreshFileChangesForSelectedVersion(requestId = state.libraryRequestId) {
    const version = state.selectedVersion?.version_id;
    const library = state.selectedLibrary;
    const request = ++state.fileChangeRequestId;
    state.fileChangeLimit = 100;
    if (!library || !version) {
      state.fileChanges = [];
      state.fileChangeBaseVersion = '';
      state.selectedFileChangeIndex = null;
      state.fileChangesError = '';
      state.fileChangesLoading = false;
      renderFileChangeWorkbench();
      return;
    }
    state.fileChangesLoading = true;
    state.fileChangesError = '';
    state.selectedFileChangeIndex = null;
    renderFileChangeWorkbench();
    try {
      const payload = await getJson(`/api/libraries/${encodeURIComponent(library)}/versions/${encodeURIComponent(version)}/file-changes`);
      if (requestId !== state.libraryRequestId || request !== state.fileChangeRequestId || library !== state.selectedLibrary || version !== state.selectedVersion?.version_id) return;
      state.fileChanges = Array.isArray(payload.rows) ? payload.rows : [];
      state.fileChangeBaseVersion = String(payload.base_version || '');
      state.fileChangesLoading = false;
      state.fileChangesLoadedKey = `${library}\n${version}`;
      renderFileChangeWorkbench();
    } catch (error) {
      if (requestId !== state.libraryRequestId || request !== state.fileChangeRequestId) return;
      state.fileChanges = [];
      state.fileChangeBaseVersion = '';
      state.fileChangesLoading = false;
      state.fileChangesError = `读取文件变化失败：${error.message}`;
      renderFileChangeWorkbench();
    }
  }

  async function runLinkedFileDiff() {
    const item = state.selectedVersion;
    const row = Number.isInteger(state.selectedFileChangeIndex) ? state.fileChanges[state.selectedFileChangeIndex] : null;
    if (!item || !row?.deep_diff_available || state.activeAction) return;
    if (row.requires_force_large && !$('linked-force-large').checked) {
      $('file-change-note').textContent = '该类型默认不读取完整内容；请先勾选“允许读取轻量证据类型的完整内容”。';
      return;
    }
    const payload = {
      base: state.fileChangeBaseVersion || $('base-version').value.trim(),
      old_relpath: row.old_path,
      relpath: row.new_path,
      type: row.file_type,
      force_large: $('linked-force-large').checked,
    };
    setActionBusy('file-diff');
    try {
      const result = await getJson(`/api/libraries/${encodeURIComponent(state.selectedLibrary)}/versions/${encodeURIComponent(item.version_id)}/file-diff`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      await startJob(result, '联动文件深度核对');
    } catch (error) {
      clearActionBusy();
      showError(`联动文件深度核对失败：${error.message}`, { action: true });
    }
  }

  function renderLibraries() {
    const query = $('library-filter').value.trim().toLowerCase();
    const rows = state.libraries.filter((item) => `${item.library_name} ${item.display_name}`.toLowerCase().includes(query));
    $('library-count').textContent = state.libraries.length;
    if (state.librariesLoading) {
      $('library-list').innerHTML = '<p class="empty-note">正在读取库目录…</p>';
    } else if (rows.length) {
      $('library-list').innerHTML = rows.map((item) => `
      <button class="library-item ${item.library_name === state.selectedLibrary ? 'selected' : ''}" data-library="${escapeHtml(item.library_name)}" title="${escapeHtml(item.library_name)}" type="button">
        <span class="library-item-main"><strong>${escapeHtml(item.display_name)}</strong><small>${escapeHtml(item.library_name)}</small></span>
        <span class="library-item-count">${item.version_count}</span>
      </button>`).join('');
    } else if (state.libraryLoadError) {
      $('library-list').innerHTML = `<p class="empty-note">${escapeHtml(state.libraryLoadError)}</p>`;
    } else {
      $('library-list').innerHTML = state.libraries.length ? '<p class="empty-note">没有匹配的正式库。</p>' : '<p class="empty-note">目录中没有已登记库。</p>';
    }
    document.querySelectorAll('[data-library]').forEach((button) => button.addEventListener('click', () => selectLibrary(button.dataset.library)));
  }

  function renderMetrics(library) {
    $('metric-versions').textContent = library ? library.version_count : '-';
    $('metric-pending').textContent = library ? Number(library.review_pending_count ?? Number(library.scan_pending || 0) + Number(library.diff_pending || 0)) : '-';
    $('metric-effective').textContent = library?.current_effective || '未设置';
  }

  function isComplete(item) {
    return ['已完成', '当前有效版', '初始基线'].includes(String(item.review_decision?.label || ''));
  }

  function visibleVersions() {
    const query = state.versionQuery.trim().toLowerCase();
    return state.versions.filter((item) => {
      const matchesQuery = !query || item.version_id.toLowerCase().includes(query) || item.package_type.toLowerCase().includes(query);
      if (!matchesQuery) return false;
      if (state.versionFilter === 'effective') return item.current_effective;
      if (state.versionFilter === 'complete') return isComplete(item);
      if (state.versionFilter === 'pending') return !isComplete(item);
      return true;
    });
  }

  function renderVersions() {
    const rows = visibleVersions();
    $('version-count').textContent = state.versionsLoading ? '读取中' : rows.length === state.versions.length ? `${rows.length} 个版本` : `${rows.length} / ${state.versions.length} 个版本`;
    const pageSummary = $('version-pagination-summary');
    const loadMore = $('load-more-versions');
    if (pageSummary) {
      pageSummary.textContent = state.versionTotal > state.versions.length
        ? `已显示 ${state.versions.length} / ${state.versionTotal} 个版本`
        : state.versionTotal ? `共 ${state.versionTotal} 个版本` : '未加载版本';
    }
    if (loadMore) {
      loadMore.classList.toggle('hidden', !state.versionHasMore);
      loadMore.disabled = state.versionsLoadingMore || Boolean(state.activeAction);
      loadMore.textContent = state.versionsLoadingMore ? '正在加载…' : '加载更多版本';
    }
    if (state.versionsLoading) {
      $('version-table-body').innerHTML = '<tr><td colspan="5" class="empty-cell">正在读取版本列表…</td></tr>';
      return;
    }
    if (state.versionLoadError) {
      $('version-table-body').innerHTML = `<tr><td colspan="5" class="empty-cell">${escapeHtml(state.versionLoadError)}</td></tr>`;
      return;
    }
    $('version-table-body').innerHTML = rows.length ? rows.map((item) => `
      <tr class="version-row ${item.version_id === state.selectedVersion?.version_id ? 'selected' : ''}" data-version="${escapeHtml(item.version_id)}">
        <td><button class="version-link" type="button" title="${escapeHtml(item.version_id)}">${escapeHtml(item.version_id)}</button>${item.current_effective ? '<span class="role-label">当前有效</span>' : ''}</td>
        <td title="${escapeHtml(item.review_decision?.reason || '')}">${chip(item.ip_decision || item.review_decision?.label || '待处理')}</td>
        <td class="change-summary" title="${escapeHtml(item.change_summary || '')}">${escapeHtml(item.change_summary || '待生成对比')}</td>
        <td title="${escapeHtml(item.scan_status)}">${chip(item.scan_status)}</td>
        <td title="正式发布状态：${escapeHtml(item.release_status)}">${releaseChip(item.release_status)}</td>
      </tr>`).join('') : `<tr><td colspan="5" class="empty-cell">${state.versions.length ? '没有符合筛选条件的版本。' : '该库没有版本记录。'}</td></tr>`;
    document.querySelectorAll('[data-version]').forEach((row) => row.addEventListener('click', () => selectVersion(row.dataset.version)));
  }

  function renderVersionFacts() {
    const item = state.selectedVersion;
    const library = state.libraries.find((row) => row.library_name === state.selectedLibrary);
    const pendingWindow = library?.pending_window || {};
    const hasCandidate = pendingWindow.state === 'PENDING'
      && Boolean(pendingWindow.candidate_effective_id)
      && pendingWindow.candidate_manifest_exists !== false;
    const actionDisclosure = $('version-action-disclosure');
    const currentActionVersion = item?.version_id || '';
    if (actionDisclosure && currentActionVersion !== state.lastActionVersion) {
      actionDisclosure.open = false;
      state.lastActionVersion = currentActionVersion;
    }
    document.querySelectorAll('[data-action]').forEach((button) => { button.disabled = true; button.classList.remove('is-busy'); });
    document.querySelectorAll('[data-sequence-action]').forEach((button) => {
      button.disabled = !item || Boolean(state.activeAction) || state.sequenceRunning;
      button.classList.toggle('is-busy', state.sequenceRunning);
    });
    const versionCommandActions = new Set(['file-diff', 'review-gate', 'review-packet']);
    const libraryCommandActions = new Set(['catalog-refresh', 'action-file', 'effective-rollback']);
    document.querySelectorAll('[data-command-action]').forEach((button) => {
      const action = button.dataset.commandAction;
      button.disabled = Boolean(state.activeAction)
        || (versionCommandActions.has(action) && !item)
        || (libraryCommandActions.has(action) && !state.selectedLibrary);
      button.classList.remove('is-busy');
    });
    document.querySelectorAll('[data-workflow-action]').forEach((button) => {
      const isAccept = button.dataset.workflowAction === 'accept-window';
      button.disabled = !state.selectedLibrary || Boolean(state.activeAction) || (isAccept && !hasCandidate);
      button.title = isAccept && !hasCandidate ? '当前没有处于待接受状态的候选有效版，请先生成接入窗口或下一步预演' : '';
    });
    document.querySelectorAll('[data-correction-action]').forEach((button) => { button.disabled = !item || Boolean(state.activeAction); });
    if (!item) {
      $('flow-object-value').textContent = '未选择版本';
      $('flow-facts-value').textContent = '等待扫描与对比';
      $('flow-decision-value').textContent = '等待生成';
      $('flow-release-value').textContent = '未检查';
      $('version-role').textContent = '未选择';
      $('version-role').className = 'status-chip status-neutral';
      $('selected-version-id').textContent = '未选择版本';
      $('version-decision').textContent = '未选择版本';
      $('version-decision-note').textContent = '选择版本后显示是否需要处理。';
      $('action-hint').textContent = '选择版本后显示动作条件。';
      $('action-availability').textContent = '选择版本后显示各动作的可用条件。';
      setSequenceState(null, '选择版本后可生成使用判断；正式发布检查单独执行。');
      $('base-version').value = '';
      $('base-version').dataset.manual = 'false';
      $('base-version-options').innerHTML = '';
      $('version-facts').innerHTML = '<p class="empty-note">选择版本后显示包类型、基准和详情入口。</p>';
      $('write-action-hint').textContent = workflowWindowHint(pendingWindow);
      renderFileChangeWorkbench();
      renderFileTree();
      return;
    }
    const readiness = item.action_readiness || {};
    const reviewDecision = item.review_decision || { label: '待处理', reason: '请按动作条件补齐事实。', next_action: '查看详情' };
    $('flow-object-value').textContent = item.version_id || '未选择版本';
    $('flow-facts-value').textContent = `扫描 ${statusLabel(item.scan_status || '未扫描')} · 对比 ${item.change_summary || '待生成'}`;
    $('flow-decision-value').textContent = reviewDecision.label || '待处理';
    $('flow-release-value').textContent = releaseLabel(item.release_status);
    $('version-role').textContent = item.current_effective ? '当前有效' : stageLabel(item.stage);
    $('version-role').className = `status-chip ${item.current_effective ? 'status-good' : 'status-neutral'}`;
    $('selected-version-id').textContent = item.version_id;
    $('version-decision').textContent = reviewDecision.label;
    $('version-decision-note').textContent = reviewDecision.reason;
    const detail = item.version_detail_url ? `<a class="text-link" href="${item.version_detail_url}" target="_blank" rel="noreferrer">打开版本详情页 ↗</a>` : '<span class="muted">版本详情尚未生成</span>';
    $('version-facts').innerHTML = [
      ['包类型', packageLabel(item.package_type)], ['版本角色', item.current_effective ? '当前有效' : stageLabel(item.stage)], ['对比基准', item.base_version || '未设置'],
    ].map(([label, value]) => `<div class="fact-row"><span>${label}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`).join('') + `<div class="fact-link">${detail}</div>`;
    $('base-version').value = item.adjacent_base_version || item.base_version || '';
    $('base-version').dataset.manual = 'false';
    $('base-version-options').innerHTML = state.versions
      .filter((version) => version.version_id !== item.version_id)
      .map((version) => `<option value="${escapeHtml(version.version_id)}">${escapeHtml(packageLabel(version.package_type))}</option>`)
      .join('');
    syncCompareBaseForMode();
    $('package-type').value = item.package_type || 'UNKNOWN_PACKAGE';
    $('mark-type').value = ({ FULL_PACKAGE: 'FULL', PARTIAL_UPDATE: 'FIX', HOTFIX: 'HOTFIX', DOC_UPDATE: 'UNKNOWN', UNKNOWN_PACKAGE: 'UNKNOWN' }[item.package_type] || 'UNKNOWN');
    $('stage').value = ['initial', 'stable', 'final', 'ad-hoc', 'dated', 'unknown'].includes(item.stage) ? item.stage : 'unknown';
    $('previous-effective').value = item.base_version || '';
    const buttons = {
      scan: ['scan-action-button', '▶'],
      compare: ['compare-action-button', '⇄'],
      'release-check': ['release-action-button', '✓'],
    };
    Object.entries(buttons).forEach(([action, [id, icon]]) => {
      const button = $(id);
      const stateForAction = readiness[action] || { enabled: false, label: '不可用', reason: '当前版本缺少动作条件' };
      button.disabled = !stateForAction.enabled || Boolean(state.activeAction);
      button.title = stateForAction.reason || '';
      button.innerHTML = `<span aria-hidden="true">${icon}</span> ${escapeHtml(stateForAction.label || '执行')}`;
    });
    $('action-hint').textContent = `建议下一步：${reviewDecision.next_action}。${reviewDecision.reason}`;
    const unavailable = Object.entries(readiness)
      .filter(([, value]) => !value?.enabled)
      .map(([action, value]) => `${action === 'scan' ? '扫描' : action === 'compare' ? '对比' : '发布检查'}：${value?.reason || '条件不足'}`);
    $('action-availability').textContent = unavailable.length ? `当前不可用：${unavailable.join('；')}。正式发布检查单独执行。` : '扫描和对比均满足当前条件；正式发布检查单独执行。';
    $('write-action-hint').textContent = workflowWindowHint(pendingWindow);
    renderFileChangeWorkbench();
    renderFileTree();
  }

  function workflowWindowHint(windowState) {
    if (windowState.state === 'INVALID') return '接入窗口文件损坏或无法读取，请重新生成接入窗口。';
    if (windowState.state !== 'PENDING') return '当前没有待接受候选；请先查看或预演接入工作流。';
    if (!windowState.candidate_effective_id) return '接入窗口存在，但还没有候选有效版。';
    if (windowState.candidate_manifest_exists === false) return '候选有效版缺少完整清单，请先完成接入计划。';
    return `已有候选有效版：${windowState.candidate_effective_id}`;
  }

  function renderWorkspaceSettings() {
    const settings = state.workspace?.scan_strategy || {};
    $('hash-policy').value = settings.hash_policy || 'smart';
    $('parse-jobs').value = String(settings.parse_jobs || '8');
    $('parse-file-types').value = settings.parse_file_types || '';
    $('parse-exclude-file-types').value = settings.parse_exclude_file_types || '';
    $('render-detail').checked = settings.render_detail !== false;
    updateSettingsSummary();
    const paths = state.workspace?.paths || {};
    const labels = { workspace: '工作区', raw_root: '原始库根', catalog: '目录快照', catalog_html: 'HTML 输出', reports: '扫描报告', diff: '对比报告' };
    $('workspace-paths').innerHTML = Object.entries(labels).map(([key, label]) => `<div><dt>${label}</dt><dd title="${escapeHtml(paths[key] || '未设置')}">${escapeHtml(paths[key] || '未设置')}</dd></div>`).join('');
  }

  function updateSettingsSummary() {
    const hashLabels = { smart: '智能取证', none: '只读元数据', full: '完整内容证据' };
    const hash = hashLabels[$('hash-policy')?.value] || '智能取证';
    const jobs = $('parse-jobs')?.value || '8';
    const mode = $('compare-mode')?.value === 'cumulative' ? '累计基线' : '相邻版本';
    const evidence = $('rescan')?.checked ? '强制重扫' : $('scan-if-missing')?.checked ? '缺失时补扫' : '沿用已有证据';
    const output = $('render-detail')?.checked ? '自动刷新详情' : '仅生成事实';
    const evidenceSummary = evidence === '沿用已有证据' ? '' : ` · ${evidence}`;
    const summary = $('settings-summary');
    if (!summary) return;
    summary.textContent = `${hash} · 并发 ${jobs} · ${mode}${evidenceSummary} · ${output}`;
    summary.title = `扫描：${hash}；解析并发：${jobs}；对比：${mode}；证据：${evidence}；输出：${output}`;
  }

  function renderPathBrowser(payload = null) {
    const panel = $('library-path-picker');
    const current = $('path-browser-current');
    const up = $('path-browser-up');
    const use = $('use-library-path');
    const list = $('path-browser-list');
    const error = $('path-browser-error');
    if (!panel || !current || !up || !use || !list || !error) return;
    current.textContent = state.pathBrowserPath || '读取中';
    current.title = state.pathBrowserPath || '';
    up.disabled = state.pathBrowserLoading || !state.pathBrowserParent;
    use.disabled = state.pathBrowserLoading || !state.pathBrowserPath;
    error.textContent = state.pathBrowserError;
    error.classList.toggle('hidden', !state.pathBrowserError);
    if (state.pathBrowserLoading) {
      list.innerHTML = '<span class="muted">读取目录中…</span>';
      return;
    }
    const children = Array.isArray(payload?.children) ? payload.children : [];
    if (!children.length) {
      list.innerHTML = '<span class="muted">当前目录没有可继续选择的子目录。</span>';
      return;
    }
    list.innerHTML = children.map((item) => `<button class="path-browser-item" data-path-browser-child="${escapeHtml(item.path)}" title="${escapeHtml(item.path)}" type="button">▸ ${escapeHtml(item.name)}</button>`).join('');
    list.querySelectorAll('[data-path-browser-child]').forEach((button) => button.addEventListener('click', () => loadPathBrowser(button.dataset.pathBrowserChild)));
  }

  async function loadPathBrowser(path = '') {
    const requestId = ++state.pathBrowserRequestId;
    state.pathBrowserLoading = true;
    state.pathBrowserError = '';
    renderPathBrowser();
    try {
      const query = path ? `?path=${encodeURIComponent(path)}` : '';
      const payload = await getJson(`/api/path-children${query}`);
      if (requestId !== state.pathBrowserRequestId) return;
      state.pathBrowserPath = String(payload.current_path || '');
      state.pathBrowserParent = String(payload.parent_path || '');
      state.pathBrowserLoading = false;
      renderPathBrowser(payload);
    } catch (error) {
      if (requestId !== state.pathBrowserRequestId) return;
      state.pathBrowserLoading = false;
      state.pathBrowserError = `目录读取失败：${error.message}`;
      state.pathBrowserParent = '';
      renderPathBrowser();
    }
  }

  function openLibraryPathPicker() {
    const panel = $('library-path-picker');
    if (!panel) return;
    panel.classList.remove('hidden');
    const defaultPath = state.workspace?.paths?.raw_root || state.workspace?.paths?.workspace || '';
    loadPathBrowser(defaultPath).catch(() => {});
  }

  function closeLibraryPathPicker() {
    $('library-path-picker')?.classList.add('hidden');
  }

  function useCurrentLibraryPath() {
    if (!state.pathBrowserPath) return;
    $('library-add-root').value = state.pathBrowserPath;
    closeLibraryPathPicker();
  }

  function strategyPayload() {
    return {
      hash_policy: $('hash-policy').value,
      parse_jobs: $('parse-jobs').value,
      parse_file_types: $('parse-file-types').value.trim(),
      parse_exclude_file_types: $('parse-exclude-file-types').value.trim(),
      no_render: !$('render-detail').checked,
    };
  }

  async function refreshVersionsForSelectedLibrary(requestId = state.libraryRequestId, append = false) {
    if (!state.selectedLibrary) return;
    const libraryName = state.selectedLibrary;
    const offset = append ? state.versions.length : 0;
    if (append) state.versionsLoadingMore = true;
    else state.versionsLoading = true;
    renderVersions();
    const payload = await getJson(`/api/libraries/${encodeURIComponent(libraryName)}/versions?offset=${offset}&limit=100`);
    if (requestId !== state.libraryRequestId || libraryName !== state.selectedLibrary) return;
    const selectedId = state.selectedVersion?.version_id;
    state.versions = append ? [...state.versions, ...payload.versions] : payload.versions;
    state.versionTotal = Number(payload.pagination?.total ?? state.versions.length);
    state.versionHasMore = payload.pagination?.next_offset !== null && payload.pagination?.next_offset !== undefined;
    state.versionsLoading = false;
    state.versionsLoadingMore = false;
    state.versionLoadError = '';
    state.selectedVersion = state.versions.find((item) => item.version_id === selectedId) || state.versions[0] || null;
    resetSelectedVersionEvidence();
    renderVersions();
    renderVersionFacts();
    await refreshActiveEvidenceForSelectedVersion(requestId);
  }

  async function selectLibrary(name) {
    const requestId = ++state.libraryRequestId;
    state.selectedLibrary = name;
    state.selectedVersion = null;
    resetSelectedVersionEvidence();
    state.versions = [];
    state.versionTotal = 0;
    state.versionHasMore = false;
    state.versionsLoadingMore = false;
    state.versionsLoading = true;
    state.versionLoadError = '';
    state.versionQuery = '';
    state.versionFilter = 'all';
    $('version-filter').value = '';
    $('version-status-filter').value = 'all';
    renderLibraries();
    const library = state.libraries.find((item) => item.library_name === name);
    $('selected-library').textContent = library?.display_name || name;
    $('selected-library-crumb').textContent = library?.display_name || name;
    $('selected-library-meta').textContent = `${name} · ${library?.vendor || '未标注厂商'} · ${library?.category || '未标注类别'} · 正在读取版本`;
    renderMetrics(library);
    renderVersions();
    renderVersionFacts();
    try {
      await refreshVersionsForSelectedLibrary(requestId);
      if (requestId === state.libraryRequestId) $('selected-library-meta').textContent = `${name} · ${library?.vendor || '未标注厂商'} · ${library?.category || '未标注类别'}`;
    } catch (error) {
      if (requestId !== state.libraryRequestId) return;
      state.versions = [];
      state.versionTotal = 0;
      state.versionHasMore = false;
      state.versionsLoadingMore = false;
      state.versionsLoading = false;
      state.versionLoadError = `读取版本失败：${error.message}`;
      $('selected-library-meta').textContent = `${name} · 读取版本失败`;
      renderVersions();
      renderVersionFacts();
      showError(state.versionLoadError);
    }
  }

  function selectVersion(versionId, rerender = true) {
    state.selectedVersion = state.versions.find((item) => item.version_id === versionId) || null;
    resetSelectedVersionEvidence();
    if (rerender) renderVersions();
    renderVersionFacts();
    refreshActiveEvidenceForSelectedVersion().catch(() => {});
  }

  async function loadLibraries() {
    const requestId = ++state.libraryLoadRequestId;
    $('reload-button').disabled = true;
    state.librariesLoading = true;
    renderLibraries();
    try {
      const payload = await getJson('/api/libraries');
      if (requestId !== state.libraryLoadRequestId) return;
      state.libraries = payload.libraries;
      state.libraryLoadError = '';
      state.librariesLoading = false;
      renderLibraries();
      $('last-loaded').textContent = `最近读取 ${new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
      const selected = state.libraries.find((item) => item.library_name === state.selectedLibrary) || state.libraries[0];
      if (selected) {
        await selectLibrary(selected.library_name);
      } else {
        state.selectedLibrary = null;
        state.selectedVersion = null;
        state.versions = [];
        state.versionTotal = 0;
        state.versionHasMore = false;
        state.versionsLoadingMore = false;
        state.versionsLoading = false;
        state.versionLoadError = '';
        $('selected-library').textContent = '选择一个正式库';
        $('selected-library-crumb').textContent = '未选择';
        $('selected-library-meta').textContent = '目录中没有可查看的正式库。';
        renderMetrics(null);
        renderVersions();
        renderVersionFacts();
      }
    } catch (error) {
      if (requestId !== state.libraryLoadRequestId) return;
      state.libraries = [];
      state.librariesLoading = false;
      state.libraryLoadError = `读取库目录失败：${error.message}`;
      $('last-loaded').textContent = '最近读取失败';
      state.selectedLibrary = null;
      state.selectedVersion = null;
      state.versions = [];
      state.versionTotal = 0;
      state.versionHasMore = false;
      state.versionsLoadingMore = false;
      state.versionsLoading = false;
      state.versionLoadError = '';
      renderLibraries();
      renderMetrics(null);
      renderVersions();
      renderVersionFacts();
      throw error;
    } finally {
      if (requestId === state.libraryLoadRequestId) {
        state.librariesLoading = false;
        $('reload-button').disabled = false;
        renderLibraries();
      }
    }
  }

  async function loadWorkspace() {
    state.workspace = await getJson('/api/workspace');
    renderWorkspaceSettings();
    setWorkflowStatus('CONNECTED', 'status-good');
  }

  function showError(message, { action = false } = {}) {
    $('job-status').textContent = action ? '动作失败' : '读取失败';
    $('job-status').className = 'status-chip status-bad';
    $('job-summary').textContent = action ? `${message}。可以修正条件后重试。` : `${message}。请检查工作区连接或重试。`;
  }

  function setActionBusy(action) {
    state.activeAction = action;
    document.querySelectorAll('[data-action], [data-workflow-action], [data-correction-action], [data-command-action]').forEach((button) => {
      button.disabled = true;
      if (button.dataset.action === action || button.dataset.workflowAction === action || button.dataset.correctionAction === action) button.classList.add('is-busy');
      if (button.dataset.commandAction === action) button.classList.add('is-busy');
    });
  }

  function clearActionBusy() {
    state.activeAction = null;
    document.querySelectorAll('[data-action], [data-workflow-action], [data-correction-action], [data-command-action]').forEach((button) => button.classList.remove('is-busy'));
    renderVersionFacts();
  }

  function setWorkflowStatus(value, className = 'status-neutral') {
    $('workflow-status').textContent = statusLabel(value);
    $('workflow-status').className = `status-chip ${className}`;
  }

  function actionPayload(action) {
    if (action === 'scan') return strategyPayload();
    if (action === 'compare') {
      return {
        base: $('base-version').value.trim(),
        mode: $('compare-mode').value,
        scan_if_missing: $('scan-if-missing').checked,
        rescan: $('rescan').checked,
      };
    }
    return {};
  }

  function actionLabel(action) {
    return action === 'scan' ? '扫描' : action === 'compare' ? '对比' : '发布检查';
  }

  const COMMAND_LABELS = {
    worklist: '工作清单',
    'catalog-refresh': '目录刷新',
    'library-discover': '候选库发现',
    'library-accept': '候选库登记合并',
    'library-apply': '库登记应用',
    'library-add': '新增库登记',
    'file-diff': '文件级对比',
    'review-gate': '审查门禁',
    'review-packet': '审查记录包',
    'effective-rollback': '有效组合回退',
    'action-file': '动作文件',
  };

  function commandPayload(action) {
    if (action === 'catalog-refresh') return {
      with_evidence: $('catalog-with-evidence').checked,
      full: $('catalog-full').checked,
    };
    if (action === 'file-diff') {
      const item = state.selectedVersion;
      return {
        base: $('base-version').value.trim() || item?.adjacent_base_version || item?.base_version || '',
        relpath: $('file-diff-relpath').value.trim(),
        type: $('file-diff-type').value.trim(),
        force_large: $('file-diff-force-large').checked,
      };
    }
    if (action === 'library-add') return {
      library_id: $('library-add-id').value.trim(),
      root: $('library-add-root').value.trim(),
      display_name: $('library-add-display').value.trim(),
      vendor: $('library-add-vendor').value.trim(),
      middle_path: $('library-add-middle').value.trim(),
      apply: $('library-add-apply').checked,
      refresh_catalog: $('library-add-refresh').checked,
    };
    if (action === 'review-gate') return {
      operation: $('review-gate-operation').value,
      gate: $('review-gate-name').value,
      item: $('review-gate-item').value.trim(),
      by: $('review-gate-by').value.trim(),
      reason: $('review-gate-reason').value.trim(),
    };
    if (action === 'review-packet') return {
      operation: $('review-packet-operation').value,
      base: $('base-version').value.trim() || state.selectedVersion?.base_version || '',
      review_owner: $('review-owner').value.trim(),
      reviewer: $('reviewer').value.trim(),
      review_id: $('review-id').value.trim(),
      decision: $('review-decision').value,
      note: $('review-note').value.trim(),
    };
    if (action === 'effective-rollback') return {
      to: $('rollback-to').value.trim(),
      by: $('rollback-by').value.trim(),
      reason: $('rollback-reason').value.trim(),
    };
    return {};
  }

  function commandEndpoint(action) {
    const library = encodeURIComponent(state.selectedLibrary || '');
    const version = encodeURIComponent(state.selectedVersion?.version_id || '');
    if (action === 'catalog-refresh') return `/api/libraries/${library}/catalog`;
    if (action === 'file-diff') return `/api/libraries/${library}/versions/${version}/file-diff`;
    if (action === 'review-gate') return `/api/libraries/${library}/versions/${version}/review-gate`;
    if (action === 'review-packet') return `/api/libraries/${library}/versions/${version}/review-packet`;
    if (action === 'action-file') return `/api/libraries/${library}/action`;
    if (action === 'effective-rollback') return `/api/libraries/${library}/effective-rollback`;
    if (action === 'worklist') return '/api/worklist';
    if (action === 'library-discover') return '/api/library/discover';
    if (action === 'library-accept') return '/api/library/accept';
    if (action === 'library-apply') return '/api/library/apply';
    if (action === 'library-add') return '/api/library/add';
    return '';
  }

  function commandNeedsConfirmation(action) {
    if (['catalog-refresh', 'library-accept', 'library-apply', 'library-add', 'effective-rollback', 'action-file'].includes(action)) return true;
    if (action === 'review-gate') return ['accept', 'waive'].includes($('review-gate-operation').value);
    if (action === 'review-packet') return $('review-packet-operation').value === 'submit';
    return false;
  }

  function commandConfirmation(action) {
    if (action === 'catalog-refresh') return '即将刷新当前库的 Catalog 投影，可能覆盖该库的目录 HTML。是否继续？';
    if (action === 'library-add') return '即将把新库写入人工登记表；如果勾选同步应用/刷新，还会继续写入库映射和目录投影。是否继续？';
    if (action === 'effective-rollback') return '即将回退当前有效组合，此操作会写入有效版状态和审计记录。是否继续？';
    return `即将执行${COMMAND_LABELS[action]}，结果会写入工作区运行记录。是否继续？`;
  }

  async function runCommand(action) {
    const endpoint = commandEndpoint(action);
    if (!endpoint || state.activeAction) return;
    if (commandNeedsConfirmation(action) && !window.confirm(commandConfirmation(action))) return;
    const payload = commandPayload(action);
    setActionBusy(action);
    try {
      const result = await getJson(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      await startJob(result, COMMAND_LABELS[action]);
    } catch (error) {
      clearActionBusy();
      showError(`${COMMAND_LABELS[action]}失败：${error.message}`, { action: true });
    }
  }

  function syncCompareBaseForMode() {
    const item = state.selectedVersion;
    const field = $('base-version');
    if (!item || field.dataset.manual === 'true') return;
    field.value = $('compare-mode').value === 'cumulative'
      ? (item.cumulative_base_version || item.base_version || '')
      : (item.adjacent_base_version || item.base_version || '');
  }

  function writeConfirmation(action) {
    const library = state.libraries.find((row) => row.library_name === state.selectedLibrary);
    const candidate = library?.pending_window?.candidate_effective_id;
    const target = action === 'accept-window' ? `候选有效版：${candidate || '未生成'}` : action === 'intake-apply' ? '写入接入计划' : '写入下一步处理结果';
    return `即将${target}\n库：${state.selectedLibrary}\n${action === 'accept-window' ? '接受人：' + ($('accepted-by').value.trim() || '未填写') : '当前页面只提交已选择的工作区策略'}\n是否继续？`;
  }

  function renderJobObservation(result, elapsedMs = 0) {
    const progress = result.progress || {};
    const rawPercent = progress.percent;
    const percent = rawPercent === null || rawPercent === undefined || rawPercent === ''
      ? Number.NaN
      : Number(rawPercent);
    const hasPercent = Number.isFinite(percent) && percent >= 0 && percent <= 100;
    const terminal = result.return_code != null || ['COMPLETED', 'FAILED', 'UNKNOWN'].includes(String(result.status || '').toUpperCase());
    const failed = String(result.status || '').toUpperCase() === 'FAILED' || (result.return_code != null && Number(result.return_code) !== 0);
    const elapsedSeconds = Number.isFinite(Number(result.elapsed_seconds))
      ? Number(result.elapsed_seconds)
      : elapsedMs / 1000;
    const track = $('job-progress-bar').parentElement;
    const logDetails = document.querySelector('.job-log-details');
    $('job-observation').classList.remove('hidden');
    $('job-stage').textContent = `阶段：${terminal ? (failed ? '已失败' : '已结束') : jobStageLabel(progress.stage)}`;
    $('job-percent').textContent = terminal ? (failed ? '进度：任务失败' : '进度：已完成') : hasPercent ? `进度：${percent}%` : '进度：处理中';
    $('job-elapsed').textContent = `用时：${Math.max(0, elapsedSeconds).toFixed(1)} 秒`;
    $('job-progress-bar').style.width = terminal ? '0%' : hasPercent ? `${percent}%` : '34%';
    track.classList.toggle('is-indeterminate', !terminal && !hasPercent);
    track.setAttribute('aria-valuenow', terminal ? '0' : hasPercent ? String(percent) : '0');
    $('job-progress-note').textContent = terminal
      ? (failed
        ? (result.error ? `失败原因：${result.error}` : '任务已失败，请打开运行日志查看完整输出。')
        : '任务已完成。')
      : progress.message || '底层任务正在运行。';
    $('job-log-tail').textContent = result.log_tail || '尚未产生终端输出。';
    if (logDetails) logDetails.open = !terminal;
    $('job-log-size').textContent = `原文 ${formatBytes(result.log_bytes)}，已显示 ${formatBytes((result.log_tail || '').length)}`;
  }

  async function startJob(result, label, workflowAction = null) {
    state.activeJob = { label, workflowAction };
    state.pollStartedAt = Date.now();
    state.pollInFlight = false;
    $('job-status').textContent = statusLabel(result.status);
    $('job-status').className = `status-chip ${statusClass(result.status)}`;
    $('job-summary').textContent = `${label}已提交，任务 ${result.job_id} 正在等待运行结果。`;
    $('job-observation').classList.remove('hidden');
    $('job-stage').textContent = '阶段：等待子任务输出';
    $('job-percent').textContent = '进度：未提供';
    $('job-elapsed').textContent = '用时：0 秒';
    $('job-progress-bar').style.width = '0%';
    $('job-progress-bar').parentElement.classList.add('is-indeterminate');
    $('job-progress-note').textContent = '任务已提交，正在等待底层输出阶段信息。';
    $('job-log-tail').textContent = '等待终端输出…';
    document.querySelector('.run-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    $('job-log-size').textContent = '原文 0 B，已显示 0 B';
    $('job-log-link').classList.add('hidden');
    $('job-log-link').removeAttribute('href');
    if (state.pollTimer) clearInterval(state.pollTimer);
    const completion = new Promise((resolve, reject) => { state.jobWaiter = { resolve, reject }; });
    state.pollTimer = setInterval(() => pollJob(result.job_id), 1000);
    await pollJob(result.job_id);
    return completion;
  }

  async function runAction(action) {
    if (!state.selectedLibrary || !state.selectedVersion || state.activeAction) return;
    const payload = actionPayload(action);
    const version = state.selectedVersion.version_id;
    const url = `/api/libraries/${encodeURIComponent(state.selectedLibrary)}/versions/${encodeURIComponent(version)}/${action}`;
    setActionBusy(action);
    try {
      const result = await getJson(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      return await startJob(result, actionLabel(action));
    } catch (error) {
      clearActionBusy();
      showError(`${actionLabel(action)}失败：${error.message}`, { action: true });
      return null;
    }
  }

  function setSequenceState(step, note) {
    const phase = String(step || '').replace(/-failed$/, '');
    const phases = ['scan', 'compare'];
    document.querySelectorAll('[data-sequence-step]').forEach((element) => {
      const current = element.dataset.sequenceStep;
      element.classList.toggle('is-active', Boolean(step) && current === phase && !String(step).endsWith('-failed'));
      element.classList.toggle('is-complete', Boolean(step) && phases.indexOf(current) < phases.indexOf(phase));
      element.classList.toggle('is-failed', Boolean(step) && current === phase && String(step).endsWith('-failed'));
    });
    if ($('sequence-note')) $('sequence-note').textContent = note;
  }

  function sequenceSucceeded(result) {
    return Boolean(result) && Number(result.return_code) === 0;
  }

  async function runReviewSequence() {
    if (!state.selectedLibrary || !state.selectedVersion || state.activeAction || state.sequenceRunning) return;
    state.sequenceRunning = true;
    renderVersionFacts();
    const scanAlreadyReady = Boolean(state.selectedVersion.scan_evidence_ready);
    const hasBase = Boolean(state.selectedVersion.adjacent_base_version || state.selectedVersion.base_version);
    try {
      if (scanAlreadyReady) {
        if (!hasBase) {
          setSequenceState(null, '首版已有扫描事实，无需版本对比；正式发布检查单独执行。');
          return;
        }
        setSequenceState('compare', '第 1 步 / 2：已有有效扫描证据，跳过重复扫描。正在执行对比。');
      } else {
        setSequenceState('scan', hasBase ? '第 1 步 / 2：正在扫描当前版本。' : '第 1 步 / 1：正在生成首版扫描事实。');
        const scan = await runAction('scan');
        if (!sequenceSucceeded(scan)) {
          setSequenceState('scan-failed', '扫描未成功，流程已停止；请查看最近运行中的失败原因。');
          return;
        }
        if (!hasBase) {
          setSequenceState(null, '首版扫描事实已生成，无需版本对比；正式发布检查单独执行。');
          return;
        }
        setSequenceState('compare', '第 2 步 / 2：扫描完成，正在按当前基准执行对比。');
      }
      const compare = await runAction('compare');
      if (!sequenceSucceeded(compare)) {
        setSequenceState('compare-failed', '对比未成功，流程已停止；请检查基准版本和对比证据。');
        return;
      }
      setSequenceState(null, '使用判断已完成；正式发布检查单独执行。');
    } finally {
      state.sequenceRunning = false;
      renderVersionFacts();
    }
  }

  function workflowRequest(action) {
    const common = { ...strategyPayload(), since: $('since-version').value.trim(), rebuild: $('rebuild-workflow').checked };
    if (action === 'next-preview') return { ...common, plan_only: true };
    if (action === 'next-apply') return { ...common, apply: true, plan_only: false };
    if (action === 'intake-preview') return { ...common, plan_only: true };
    if (action === 'intake-apply') return { ...common, plan_only: false };
    if (action === 'accept-window') return { accepted_by: $('accepted-by').value.trim(), note: $('accept-note').value.trim() };
    return {};
  }

  async function runWorkflow(action) {
    if (!state.selectedLibrary || state.activeAction) return;
    const writeAction = ['next-apply', 'intake-apply', 'accept-window'].includes(action);
    if (writeAction && !window.confirm(writeConfirmation(action))) return;
    if (action === 'accept-window' && !$('accepted-by').value.trim()) {
      setWorkflowStatus('FAILED', 'status-bad');
      $('workflow-summary').textContent = '接受候选有效版前必须填写接受人。';
      return;
    }
    const endpointAction = action === 'next-preview' || action === 'next-apply' ? 'next' : action === 'intake-preview' || action === 'intake-apply' ? 'intake' : action;
    const payload = workflowRequest(action);
    setActionBusy(action);
    try {
      const result = await getJson(`/api/libraries/${encodeURIComponent(state.selectedLibrary)}/${endpointAction}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      setWorkflowStatus(result.status, statusClass(result.status));
      $('workflow-summary').textContent = `${endpointAction === 'window' ? '接入窗口' : endpointAction === 'next' ? '下一步预演' : endpointAction === 'intake' ? '接入计划' : '有效版确认'}已提交。详情将在运行记录中更新。`;
      await startJob(result, endpointAction === 'next' ? '下一步' : endpointAction === 'intake' ? '接入计划' : endpointAction === 'accept-window' ? '有效版确认' : '窗口读取', action);
    } catch (error) {
      clearActionBusy();
      setWorkflowStatus('FAILED', 'status-bad');
      $('workflow-summary').textContent = error.message;
    }
  }

  async function runCorrection(action) {
    if (!state.selectedLibrary || !state.selectedVersion || state.activeAction) return;
    if (!window.confirm('这一步会修改目录中的人工确认信息，是否继续？')) return;
    const version = state.selectedVersion.version_id;
    const payload = action === 'mark'
      ? { type: $('mark-type').value, note: $('override-note').value.trim() }
      : { package_type: $('package-type').value, stage: $('stage').value, compare_default: $('compare-default').value, base_full: $('base-full').value.trim(), previous_effective: $('previous-effective').value.trim(), note: $('override-note').value.trim() };
    setActionBusy(action);
    try {
      const result = await getJson(`/api/libraries/${encodeURIComponent(state.selectedLibrary)}/versions/${encodeURIComponent(version)}/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      await startJob(result, action === 'mark' ? '版本类型标记' : '目录修正');
    } catch (error) {
      clearActionBusy();
      showError(`${action === 'mark' ? '版本类型标记' : '目录修正'}失败：${error.message}`, { action: true });
    }
  }

  async function pollJob(jobId) {
    if (state.pollInFlight) return;
    state.pollInFlight = true;
    try {
      const result = await getJson(`/api/runs/${encodeURIComponent(jobId)}`);
      $('job-status').textContent = statusLabel(result.status);
      $('job-status').className = `status-chip ${statusClass(result.status)}`;
      const terminal = result.return_code != null || ['COMPLETED', 'FAILED', 'UNKNOWN'].includes(String(result.status || '').toUpperCase());
      const elapsed = state.pollStartedAt ? Date.now() - state.pollStartedAt : 0;
      const elapsedLabel = `${Math.max(1, Math.round(elapsed / 1000))} 秒`;
      renderJobObservation(result, elapsed);
      $('job-summary').textContent = terminal
        ? (result.return_code == null ? `任务 ${jobId} 的结果无法确认。${result.message || ''}` : `任务 ${jobId} 已结束，返回码 ${result.return_code}。`)
        : elapsed >= JOB_TIMEOUT_MS
          ? `任务 ${jobId} 已运行超过 30 分钟，页面已停止自动轮询；请查看日志确认底层任务是否仍在运行。`
          : `任务 ${jobId} 正在运行，已用时 ${elapsedLabel}。`;
      if (result.log_url) { $('job-log-link').href = result.log_url; $('job-log-link').classList.remove('hidden'); }
      if (result.run_manifest) $('job-summary').textContent += ` 运行清单：${result.run_manifest}`;
      if ((terminal || elapsed >= JOB_TIMEOUT_MS) && state.pollTimer) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        const completedJob = state.activeJob;
        state.activeJob = null;
        if (completedJob?.workflowAction) {
          setWorkflowStatus(elapsed >= JOB_TIMEOUT_MS && !terminal ? 'UNKNOWN' : result.status, statusClass(result.status));
          $('workflow-summary').textContent = result.return_code === 0
            ? `${completedJob.label}已完成，工作区状态已重新读取。`
            : elapsed >= JOB_TIMEOUT_MS && !terminal
              ? `${completedJob.label}运行时间过长，已停止页面轮询，请查看日志。`
              : `${completedJob.label}未成功完成，请查看最近运行中的日志和返回码。`;
        }
        clearActionBusy();
        if (terminal) await loadLibraries();
        const waiter = state.jobWaiter;
        state.jobWaiter = null;
        if (waiter) waiter.resolve(result);
      }
    } catch (error) {
      if (state.pollTimer) clearInterval(state.pollTimer);
      state.pollTimer = null;
      const waiter = state.jobWaiter;
      state.jobWaiter = null;
      clearActionBusy();
      if (waiter) waiter.reject(error);
      showError(`读取运行状态失败：${error.message}`, { action: true });
    } finally {
      state.pollInFlight = false;
    }
  }

  document.querySelector('.skip-link')?.addEventListener('click', () => {
    const main = $('workspace-main');
    window.requestAnimationFrame(() => main?.focus());
  });
  $('library-filter').addEventListener('input', renderLibraries);
  $('version-filter').addEventListener('input', (event) => { state.versionQuery = event.target.value; renderVersions(); renderVersionFacts(); });
  $('version-status-filter').addEventListener('change', (event) => { state.versionFilter = event.target.value; renderVersions(); renderVersionFacts(); });
  $('load-more-versions').addEventListener('click', () => {
    if (state.versionsLoadingMore || !state.versionHasMore) return;
    refreshVersionsForSelectedLibrary(state.libraryRequestId, true).catch((error) => {
      state.versionsLoadingMore = false;
      renderVersions();
      showError(`继续读取版本失败：${error.message}`);
    });
  });
  $('base-version').addEventListener('input', () => { $('base-version').dataset.manual = 'true'; });
  $('compare-mode').addEventListener('change', () => { syncCompareBaseForMode(); updateSettingsSummary(); });
  ['hash-policy', 'parse-jobs', 'parse-file-types', 'parse-exclude-file-types', 'render-detail'].forEach((id) => {
    $(id).addEventListener('input', updateSettingsSummary);
    $(id).addEventListener('change', updateSettingsSummary);
  });
  $('scan-if-missing').addEventListener('change', () => {
    if ($('scan-if-missing').checked) $('rescan').checked = false;
    updateSettingsSummary();
  });
  $('rescan').addEventListener('change', () => {
    if ($('rescan').checked) $('scan-if-missing').checked = false;
    updateSettingsSummary();
  });
  $('file-change-filter').addEventListener('input', () => { state.fileChangeLimit = 100; renderFileChangeWorkbench(); });
  $('file-change-kind-filter').addEventListener('change', () => { state.fileChangeLimit = 100; renderFileChangeWorkbench(); });
  $('file-change-type-filter').addEventListener('change', () => { state.fileChangeLimit = 100; renderFileChangeWorkbench(); });
  $('load-more-file-changes').addEventListener('click', () => { state.fileChangeLimit += 100; renderFileChangeWorkbench(); });
  $('linked-force-large').addEventListener('change', renderFileChangeWorkbench);
  $('linked-file-diff-button').addEventListener('click', runLinkedFileDiff);
  $('file-tree-filter').addEventListener('input', scheduleFileTreeRender);
  $('file-tree-type-filter').addEventListener('change', renderFileTree);
  $('select-visible-files').addEventListener('click', () => {
    visibleFileTreeFiles().forEach((row) => state.selectedFileTreePaths.add(row.path));
    renderFileTree();
  });
  $('clear-selected-files').addEventListener('click', () => {
    state.selectedFileTreePaths = new Set();
    renderFileTree();
  });
  $('copy-selected-paths').addEventListener('click', () => copySelectedFileTreePaths());
  $('copy-library-root').addEventListener('click', () => copyLibraryRootPath());
  document.querySelectorAll('[data-workspace-tab]').forEach((tab) => {
    tab.addEventListener('click', () => activateWorkspaceTab(tab.dataset.workspaceTab));
    tab.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const tabs = Array.from(document.querySelectorAll('[data-workspace-tab]'));
      const current = tabs.indexOf(tab);
      const offset = event.key === 'ArrowRight' ? 1 : -1;
      activateWorkspaceTab(tabs[(current + offset + tabs.length) % tabs.length].dataset.workspaceTab, { focus: true });
    });
  });
  $('show-settings-button').addEventListener('click', () => {
    const settings = $('settings-disclosure');
    settings.open = true;
    settings.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  $('browse-library-root').addEventListener('click', openLibraryPathPicker);
  $('close-library-path-picker').addEventListener('click', closeLibraryPathPicker);
  $('path-browser-up').addEventListener('click', () => loadPathBrowser(state.pathBrowserParent));
  $('use-library-path').addEventListener('click', useCurrentLibraryPath);
  $('reload-button').addEventListener('click', () => loadLibraries().catch((error) => showError(error.message)));
  $('reset-settings').addEventListener('click', () => {
    const settings = state.workspace?.scan_strategy || {};
    $('hash-policy').value = settings.hash_policy || 'smart';
    $('parse-jobs').value = String(settings.parse_jobs || '8');
    $('parse-file-types').value = settings.parse_file_types || '';
    $('parse-exclude-file-types').value = settings.parse_exclude_file_types || '';
    $('render-detail').checked = settings.render_detail !== false;
    $('scan-if-missing').checked = false;
    $('rescan').checked = false;
    $('compare-mode').value = 'adjacent';
    updateSettingsSummary();
  });
  document.querySelectorAll('[data-action]').forEach((button) => button.addEventListener('click', () => runAction(button.dataset.action)));
  document.querySelectorAll('[data-sequence-action]').forEach((button) => button.addEventListener('click', runReviewSequence));
  document.querySelectorAll('[data-workflow-action]').forEach((button) => button.addEventListener('click', () => runWorkflow(button.dataset.workflowAction)));
  document.querySelectorAll('[data-correction-action]').forEach((button) => button.addEventListener('click', () => runCorrection(button.dataset.correctionAction)));
  document.querySelectorAll('[data-command-action]').forEach((button) => button.addEventListener('click', () => runCommand(button.dataset.commandAction)));
  activateWorkspaceTab(state.workspaceTab);
  getJson('/api/health').then(() => { $('health-badge').textContent = '服务正常'; $('health-badge').className = 'status-chip status-good'; }).catch(() => { $('health-badge').textContent = '服务异常'; $('health-badge').className = 'status-chip status-bad'; });
  Promise.all([loadWorkspace(), loadLibraries()]).catch((error) => showError(error.message));
})();
