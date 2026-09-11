(() => {
  const initialRoute = new URLSearchParams(window.location.search);
  const initialTab = initialRoute.get('tab');
  const state = {
    libraries: [],
    selectedLibrary: initialRoute.get('library') || null,
    versions: [],
    selectedVersion: null,
    requestedVersionId: initialRoute.get('version') || '',
    workspace: null,
    libraryQuery: initialRoute.get('library_query') || '',
    libraryScope: initialRoute.get('library_scope') || 'all',
    libraryKind: initialRoute.get('library_kind') || 'all',
    libraryVendor: initialRoute.get('library_vendor') || 'all',
    libraryPlatform: initialRoute.get('library_platform') || 'all',
    versionQuery: initialRoute.get('version_query') || '',
    versionFilter: initialRoute.get('version_filter') || 'all',
    versionSort: initialRoute.get('version_sort') || 'attention',
    versionTotal: 0,
    versionHasMore: false,
    versionsLoadingMore: false,
    versionRenderLimit: 25,
    pollTimer: null,
    activeAction: null,
    libraryRequestId: 0,
    librariesLoading: false,
    libraryLoadError: '',
    versionsLoading: false,
    versionLoadError: '',
    activeJob: null,
    jobWaiter: null,
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
    fileChangeTotal: 0,
    fileChangeHasMore: false,
    fileChangeFacetCounts: { total: 0, by_change: {}, by_file_type: {} },
    fileChangeComparisonSemantics: 'complete_snapshot',
    fileChangeOmittedFromOverlay: 0,
    fileChangeRawRemoved: 0,
    fileChangeQuery: initialRoute.get('file_query') || '',
    fileChangeKind: initialRoute.get('file_change') || 'all',
    fileChangeType: initialRoute.get('file_type') || 'all',
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
    workspaceTab: initialTab === 'changes' ? 'changes' : 'tree',
    libraryCandidates: [],
    candidateSnapshot: null,
    candidateLoading: false,
    candidateError: '',
    candidateQuery: '',
    candidateStatus: 'all',
    selectedCandidateIds: new Set(),
    settingsSaving: false,
  };
  const $ = (id) => document.getElementById(id);
  const JOB_TIMEOUT_MS = 30 * 60 * 1000;
  const VERSION_RENDER_BATCH = 25;

  function updateRouteState() {
    const params = new URLSearchParams();
    if (state.selectedLibrary) params.set('library', state.selectedLibrary);
    const versionId = state.selectedVersion?.version_id || state.requestedVersionId;
    if (versionId) params.set('version', versionId);
    if (state.workspaceTab !== 'tree') params.set('tab', state.workspaceTab);
    if (state.libraryQuery) params.set('library_query', state.libraryQuery);
    if (state.libraryScope !== 'all') params.set('library_scope', state.libraryScope);
    if (state.libraryKind !== 'all') params.set('library_kind', state.libraryKind);
    if (state.libraryVendor !== 'all') params.set('library_vendor', state.libraryVendor);
    if (state.libraryPlatform !== 'all') params.set('library_platform', state.libraryPlatform);
    if (state.versionQuery) params.set('version_query', state.versionQuery);
    if (state.versionFilter !== 'all') params.set('version_filter', state.versionFilter);
    if (state.versionSort !== 'attention') params.set('version_sort', state.versionSort);
    if (state.fileChangeQuery) params.set('file_query', state.fileChangeQuery);
    if (state.fileChangeKind !== 'all') params.set('file_change', state.fileChangeKind);
    if (state.fileChangeType !== 'all') params.set('file_type', state.fileChangeType);
    const query = params.toString();
    history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}`);
  }

  function restoreRouteControls() {
    $('library-filter').value = state.libraryQuery;
    $('library-scope-filter').value = ['all', 'pending', 'blocked', 'no_effective', 'candidate'].includes(state.libraryScope) ? state.libraryScope : 'all';
    $('version-filter').value = state.versionQuery;
    $('version-status-filter').value = ['all', 'scan', 'compare', 'review', 'effective', 'blocked', 'error'].includes(state.versionFilter) ? state.versionFilter : 'all';
    $('version-sort').value = ['attention', 'date_desc', 'date_asc', 'effective'].includes(state.versionSort) ? state.versionSort : 'attention';
    $('file-change-filter').value = state.fileChangeQuery;
    $('file-change-kind-filter').value = ['all', 'ADDED', 'REMOVED', 'CHANGED', 'PATH_CHANGED'].includes(state.fileChangeKind) ? state.fileChangeKind : 'all';
  }

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
    updateRouteState();
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
    state.fileChangeTotal = 0;
    state.fileChangeHasMore = false;
    state.fileChangeFacetCounts = { total: 0, by_change: {}, by_file_type: {} };
    state.fileChangeComparisonSemantics = 'complete_snapshot';
    state.fileChangeOmittedFromOverlay = 0;
    state.fileChangeRawRemoved = 0;
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
    PASS: '正式发布通过',
    PASS_WITH_WARNING: '正式发布通过（有提醒）',
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

  function versionStageClass(status, { management = false } = {}) {
    if (management) return 'is-management';
    const raw = String(status || '').toUpperCase();
    if (raw.includes('PASS') || raw === 'SCANNED' || raw === 'SAME' || raw === 'NO_DIFF' || raw === 'DIFF_DONE') return 'is-ready';
    if (raw.includes('PENDING') || raw.includes('FAIL') || raw.includes('BLOCK') || raw === 'NOT_SCANNED') return 'is-attention';
    return '';
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

  function renderFileChangeTypes() {
    const select = $('file-change-type-filter');
    if (!select) return;
    const selected = state.fileChangeType || 'all';
    const types = Object.keys(state.fileChangeFacetCounts.by_file_type || {}).sort();
    select.innerHTML = '<option value="all">全部类型</option>' + types.map((type) => `<option value="${escapeHtml(type)}">${escapeHtml(fileTypeLabel(type))}</option>`).join('');
    select.value = types.includes(selected) ? selected : 'all';
    state.fileChangeType = select.value;
  }

  function renderFileChangeFacets() {
    const container = $('file-change-facet-chips');
    if (!container) return;
    const counts = state.fileChangeFacetCounts || {};
    const byChange = counts.by_change || {};
    const byFileType = counts.by_file_type || {};
    const changeChips = ['ADDED', 'REMOVED', 'CHANGED', 'PATH_CHANGED']
      .filter((change) => Number(byChange[change] || 0) > 0)
      .map((change) => `<button class="facet-chip ${state.fileChangeKind === change ? 'is-active' : ''}" data-file-change-facet="change" data-file-change-value="${change}" type="button">${escapeHtml(fileChangeLabel(change))} <b>${Number(byChange[change] || 0)}</b></button>`);
    const typeChips = Object.entries(byFileType)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([type, count]) => `<button class="facet-chip ${state.fileChangeType === type ? 'is-active' : ''}" data-file-change-facet="type" data-file-change-value="${escapeHtml(type)}" type="button">${escapeHtml(fileTypeLabel(type))} <b>${Number(count || 0)}</b></button>`);
    const allActive = state.fileChangeKind === 'all' && state.fileChangeType === 'all';
    container.innerHTML = counts.total
      ? `<button class="facet-chip ${allActive ? 'is-active' : ''}" data-file-change-facet="reset" type="button">全部 <b>${Number(counts.total || 0)}</b></button>${changeChips.join('')}${typeChips.join('')}`
      : '<span class="muted">完成对比后显示按变化和视图类型汇总的文件数量。</span>';
    container.querySelectorAll('[data-file-change-facet]').forEach((button) => button.addEventListener('click', () => {
      const facet = button.dataset.fileChangeFacet;
      const value = button.dataset.fileChangeValue || 'all';
      if (facet === 'reset') {
        state.fileChangeKind = 'all';
        state.fileChangeType = 'all';
      } else if (facet === 'change') {
        state.fileChangeKind = state.fileChangeKind === value ? 'all' : value;
      } else if (facet === 'type') {
        state.fileChangeType = state.fileChangeType === value ? 'all' : value;
      }
      $('file-change-kind-filter').value = state.fileChangeKind;
      renderFileChangeTypes();
      resetFileChangePageAndRefresh();
    }));
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
    const scopeNote = $('file-change-scope-note');
    const pageSummary = $('file-change-page-summary');
    const loadMore = $('load-more-file-changes');
    if (!body || !summary || !selectionLabel || !oldInput || !newInput || !typeInput || !runButton || !forceInput || !note) return;
    if (scopeNote) {
      const semantics = state.fileChangeComparisonSemantics;
      const omitted = Number(state.fileChangeOmittedFromOverlay || 0);
      const rawRemoved = Number(state.fileChangeRawRemoved || 0);
      if (semantics === 'overlay') {
        scopeNote.textContent = `这是增量包对比：本次未提供的旧文件不等于删除${omitted ? `，共 ${omitted} 个` : ''}。`;
        scopeNote.className = 'file-change-scope-note scope-overlay';
      } else if (semantics === 'needs_package_confirmation') {
        scopeNote.textContent = `完整包文件数量显著缩小，暂不把旧文件判为删除；原始差异 ${rawRemoved} 条，需先确认包类型。`;
        scopeNote.className = 'file-change-scope-note scope-warning';
      } else {
        scopeNote.textContent = '';
        scopeNote.className = 'file-change-scope-note hidden';
      }
    }
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
      const visibleRows = state.fileChanges.map((row, index) => ({ row, index }));
      const totalEvidence = Number(state.fileChangeFacetCounts.total || state.fileChangeTotal || 0);
      summary.textContent = `${state.fileChangeTotal} 条匹配变化${totalEvidence && totalEvidence !== state.fileChangeTotal ? ` / 共 ${totalEvidence} 条` : ''}${state.fileChangeBaseVersion ? ` · 基准 ${state.fileChangeBaseVersion}` : ''}`;
      if (pageSummary) {
        pageSummary.textContent = !state.fileChangeTotal
          ? '暂无文件变化证据'
          : `显示 ${state.fileChanges.length} / ${state.fileChangeTotal} 条`;
      }
      if (loadMore) loadMore.classList.toggle('hidden', !state.fileChangeHasMore);
      if (!state.fileChangeTotal) {
        body.innerHTML = '<tr><td colspan="6" class="empty-cell">没有符合筛选条件的文件；请调整筛选条件或先完成版本对比。</td></tr>';
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
    renderFileChangeFacets();
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

  function fileChangeRequestQuery(offset = 0) {
    const params = new URLSearchParams({ offset: String(offset), limit: String(state.fileChangeLimit) });
    if (state.fileChangeKind !== 'all') params.set('change', state.fileChangeKind);
    if (state.fileChangeType !== 'all') params.set('file_type', state.fileChangeType);
    if (state.fileChangeQuery) params.set('query', state.fileChangeQuery);
    return params.toString();
  }

  function resetFileChangePageAndRefresh() {
    state.fileChanges = [];
    state.fileChangeTotal = 0;
    state.fileChangeHasMore = false;
    state.selectedFileChangeIndex = null;
    state.fileChangesLoadedKey = '';
    updateRouteState();
    refreshFileChangesForSelectedVersion().catch((error) => showError(error.message));
  }

  async function refreshFileChangesForSelectedVersion(requestId = state.libraryRequestId, { append = false } = {}) {
    const version = state.selectedVersion?.version_id;
    const library = state.selectedLibrary;
    const request = ++state.fileChangeRequestId;
    if (!library || !version) {
      state.fileChanges = [];
      state.fileChangeBaseVersion = '';
      state.selectedFileChangeIndex = null;
      state.fileChangesError = '';
      state.fileChangesLoading = false;
      state.fileChangeTotal = 0;
      state.fileChangeHasMore = false;
      renderFileChangeWorkbench();
      return;
    }
    state.fileChangesLoading = true;
    state.fileChangesError = '';
    if (!append) state.selectedFileChangeIndex = null;
    renderFileChangeWorkbench();
    try {
      const offset = append ? state.fileChanges.length : 0;
      const payload = await getJson(`/api/libraries/${encodeURIComponent(library)}/versions/${encodeURIComponent(version)}/file-changes?${fileChangeRequestQuery(offset)}`);
      if (requestId !== state.libraryRequestId || request !== state.fileChangeRequestId || library !== state.selectedLibrary || version !== state.selectedVersion?.version_id) return;
      const rows = Array.isArray(payload.rows) ? payload.rows : [];
      state.fileChanges = append ? [...state.fileChanges, ...rows] : rows;
      state.fileChangeBaseVersion = String(payload.base_version || '');
      state.fileChangeTotal = Number(payload.pagination?.total ?? payload.count ?? state.fileChanges.length);
      state.fileChangeHasMore = payload.pagination?.next_offset !== null && payload.pagination?.next_offset !== undefined;
      state.fileChangeFacetCounts = payload.counts || { total: state.fileChangeTotal, by_change: {}, by_file_type: {} };
      state.fileChangeComparisonSemantics = String(payload.comparison_semantics || 'complete_snapshot');
      state.fileChangeOmittedFromOverlay = Number(payload.omitted_from_overlay || 0);
      state.fileChangeRawRemoved = Number(payload.raw_removed || 0);
      state.fileChangesLoading = false;
      state.fileChangesLoadedKey = `${library}\n${version}`;
      updateRouteState();
      renderFileChangeWorkbench();
    } catch (error) {
      if (requestId !== state.libraryRequestId || request !== state.fileChangeRequestId) return;
      state.fileChanges = [];
      state.fileChangeBaseVersion = '';
      state.fileChangesLoading = false;
      state.fileChangeTotal = 0;
      state.fileChangeHasMore = false;
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
    if (!state.librariesLoading) populateLibraryFilters();
    const rows = state.libraries.filter((item) => libraryMatchesFilters(item));
    $('library-count').textContent = state.libraries.length;
    renderLibraryFacetSummary(rows, state.libraries);
    if (state.librariesLoading) {
      $('library-list').innerHTML = '<p class="empty-note">正在读取库目录…</p>';
    } else if (rows.length) {
      $('library-list').innerHTML = rows.map((item) => `
      <button class="library-item ${item.library_name === state.selectedLibrary ? 'selected' : ''}" data-library="${escapeHtml(item.library_name)}" title="${escapeHtml(item.library_name)}" type="button">
        <span class="library-item-main">
          <strong>${escapeHtml(item.display_name)}</strong>
          <small>${escapeHtml(item.library_name)}</small>
          <span class="library-meta-line">${escapeHtml(libraryMetaLine(item))}</span>
        </span>
        <span class="library-item-signals">${libraryItemSignals(item)}</span>
        <span class="library-item-count">${Number(item.version_count || 0)}版</span>
      </button>`).join('');
    } else if (state.libraryLoadError) {
      $('library-list').innerHTML = `<p class="empty-note">${escapeHtml(state.libraryLoadError)}</p>`;
    } else {
      $('library-list').innerHTML = state.libraries.length ? '<p class="empty-note">没有匹配的正式库。</p>' : '<p class="empty-note">目录中没有已登记库。</p>';
    }
    renderRegisteredLibraries();
    document.querySelectorAll('[data-library]').forEach((button) => button.addEventListener('click', () => selectLibrary(button.dataset.library)));
  }

  function normalizeFilterValue(value) {
    const text = String(value || '').trim();
    return text || '未标注';
  }

  function libraryKindLabel(item) {
    const raw = normalizeFilterValue(item.library_type || item.category);
    if (raw !== '未标注') return raw;
    const source = `${item.library_name || ''} ${item.display_name || ''}`.toLowerCase();
    if (source.includes('stdcell') || source.includes('standard_cell')) return '标准单元';
    if (source.includes('sram') || source.includes('memory')) return '存储器';
    if (source.includes('analog')) return '模拟 IP';
    if (source.includes('io')) return 'IO';
    if (source.includes('ip') || source.includes('.')) return 'IP';
    return '未分类';
  }

  function libraryPlatformLabel(item) {
    const raw = normalizeFilterValue(item.platform || item.process || item.technology);
    if (raw !== '未标注') return raw;
    const source = `${item.library_name || ''} ${item.display_name || ''} ${item.root_abs || ''}`.toLowerCase();
    const patterns = [
      ['n7', 'N7'],
      ['p3', 'P3'],
      ['asap7', 'ASAP7'],
      ['sky130', 'SKY130'],
      ['gf180', 'GF180'],
      ['nangate45', 'Nangate45'],
    ];
    const found = patterns.find(([needle]) => source.includes(needle));
    return found ? found[1] : '未标注平台';
  }

  function libraryMetaLine(item) {
    return `${item.vendor || '未标注厂商'} · ${libraryKindLabel(item)} · ${libraryPlatformLabel(item)}`;
  }

  function libraryScopeCounts(rows = state.libraries) {
    return rows.reduce((counts, item) => {
      counts.all += 1;
      if (Number(item.workflow_pending_count || 0) > 0) counts.pending += 1;
      if (Number(item.release_blocked_count || 0) > 0) counts.blocked += 1;
      if (!(item.current_effective || item.current_effective_id)) counts.no_effective += 1;
      if (item.pending_window?.candidate_effective_id || ['PRESENT', 'READY', 'PENDING'].includes(String(item.pending_window?.state || '').toUpperCase())) counts.candidate += 1;
      return counts;
    }, { all: 0, pending: 0, blocked: 0, no_effective: 0, candidate: 0 });
  }

  function setSelectOptions(selectId, values, currentValue, fallbackLabel) {
    const select = $(selectId);
    const unique = Array.from(new Set(values.map(normalizeFilterValue))).filter(Boolean).sort((a, b) => a.localeCompare(b, 'zh-CN'));
    select.innerHTML = `<option value="all">${fallbackLabel}</option>${unique.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('')}`;
    select.value = unique.includes(currentValue) ? currentValue : 'all';
  }

  function populateLibraryFilters() {
    setSelectOptions('library-kind-filter', state.libraries.map(libraryKindLabel), state.libraryKind, '库类型');
    state.libraryKind = $('library-kind-filter').value;
    setSelectOptions('library-vendor-filter', state.libraries.map((item) => item.vendor || '未标注厂商'), state.libraryVendor, '厂商');
    state.libraryVendor = $('library-vendor-filter').value;
    setSelectOptions('library-platform-filter', state.libraries.map(libraryPlatformLabel), state.libraryPlatform, '平台');
    state.libraryPlatform = $('library-platform-filter').value;
  }

  function libraryMatchesFilters(item) {
    const query = state.libraryQuery.trim().toLowerCase();
    const searchable = `${item.library_name || ''} ${item.display_name || ''} ${item.vendor || ''} ${libraryKindLabel(item)} ${libraryPlatformLabel(item)}`.toLowerCase();
    if (query && !searchable.includes(query)) return false;
    if (state.libraryKind !== 'all' && libraryKindLabel(item) !== state.libraryKind) return false;
    if (state.libraryVendor !== 'all' && normalizeFilterValue(item.vendor || '未标注厂商') !== state.libraryVendor) return false;
    if (state.libraryPlatform !== 'all' && libraryPlatformLabel(item) !== state.libraryPlatform) return false;
    if (state.libraryScope === 'pending') return Number(item.workflow_pending_count || 0) > 0;
    if (state.libraryScope === 'blocked') return Number(item.release_blocked_count || 0) > 0;
    if (state.libraryScope === 'no_effective') return !(item.current_effective || item.current_effective_id);
    if (state.libraryScope === 'candidate') return Boolean(item.pending_window?.candidate_effective_id || ['PRESENT', 'READY', 'PENDING'].includes(String(item.pending_window?.state || '').toUpperCase()));
    return true;
  }

  function renderLibraryFacetSummary(visibleRows, allRows) {
    const counts = libraryScopeCounts(allRows);
    const scopeName = {
      all: '全部库',
      pending: '有待处理',
      blocked: '发布受阻',
      no_effective: '无当前可用',
      candidate: '候选待登记',
    }[state.libraryScope] || '全部库';
    $('library-facet-summary').textContent = `${scopeName} ${visibleRows.length} / ${counts.all} · 待处理 ${counts.pending} · 受阻 ${counts.blocked}`;
  }

  function libraryItemSignals(item) {
    const pending = Number(item.workflow_pending_count || 0);
    const latest = item.latest_version ? `最新 ${item.latest_version}` : '无版本';
    const current = item.current_effective || item.current_effective_id ? `当前 ${item.current_effective || item.current_effective_id}` : '未设当前';
    const pendingChip = pending
      ? `<span class="library-signal is-attention">待处理 ${pending}</span>`
      : '<span class="library-signal is-ready">无待处理</span>';
    return `${pendingChip}<span class="library-signal">${escapeHtml(latest)}</span><span class="library-signal">${escapeHtml(current)}</span>`;
  }

  function renderRegisteredLibraries() {
    const body = $('registered-library-table-body');
    const status = $('registered-library-status');
    if (!body || !status) return;
    if (state.librariesLoading) {
      status.textContent = '读取中';
      status.className = 'status-chip status-neutral';
      body.innerHTML = '<tr><td colspan="5" class="muted">正在读取已登记库。</td></tr>';
      return;
    }
    if (state.libraryLoadError) {
      status.textContent = '读取失败';
      status.className = 'status-chip status-bad';
      body.innerHTML = `<tr><td colspan="5" class="muted">${escapeHtml(state.libraryLoadError)}</td></tr>`;
      return;
    }
    status.textContent = `已登记 ${state.libraries.length}`;
    status.className = 'status-chip status-good';
    body.innerHTML = state.libraries.length ? state.libraries.map((item) => {
      const current = item.library_name === state.selectedLibrary;
      return `<tr class="${current ? 'is-selected' : ''}">
        <td><code title="${escapeHtml(item.library_name)}">${escapeHtml(item.library_name)}</code><small>${escapeHtml(item.display_name || '未设置显示名称')}</small></td>
        <td><code title="${escapeHtml(item.root_abs || '')}">${escapeHtml(item.root_abs || '未记录')}</code></td>
        <td>${Number(item.version_count || 0)}</td>
        <td>${escapeHtml(item.current_effective || '未设置')}</td>
        <td><button class="button button-secondary button-small" data-registered-library="${escapeHtml(item.library_name)}" type="button">${current ? '处理中' : '打开'}</button></td>
      </tr>`;
    }).join('') : '<tr><td colspan="5" class="muted">目录中还没有已登记库。</td></tr>';
    body.querySelectorAll('[data-registered-library]').forEach((button) => button.addEventListener('click', () => selectLibrary(button.dataset.registeredLibrary)));
  }

  function renderMetrics(library) {
    $('metric-effective').textContent = library?.current_effective || '未设置';
  }

  function isComplete(item) {
    return ['事实已生成', '当前可用版本', '初始基线'].includes(String(item.workflow_status?.label || ''));
  }

  function versionFilterName(value) {
    return {
      all: '全部版本',
      scan: '待扫描/补扫',
      compare: '待对比',
      review: '可审查',
      effective: '当前可用',
      blocked: '发布受阻',
      error: '异常',
    }[value] || '全部版本';
  }

  function versionDateKey(item) {
    const versionId = String(item?.version_id || '');
    const match = versionId.match(/20\d{6}/);
    return match ? Number(match[0]) : 0;
  }

  function versionMatchesFilter(item, filter) {
    if (filter === 'effective') return item.current_effective;
    if (filter === 'scan') return !item.scan_evidence_ready;
    if (filter === 'compare') return deriveVersionTask(item).state === '待对比';
    if (filter === 'review') return deriveVersionTask(item).state === '审查事实已就绪';
    if (filter === 'blocked') return String(item.release_status || '').toUpperCase().includes('BLOCK');
    if (filter === 'error') {
      const scan = String(item.scan_status || '').toUpperCase();
      const diff = String(item.diff_status || '').toUpperCase();
      return scan.includes('FAIL') || diff.includes('FAIL') || diff.includes('ERROR') || String(item.package_type || '').includes('UNKNOWN');
    }
    return true;
  }

  function versionAttentionScore(item) {
    if (versionMatchesFilter(item, 'error')) return 0;
    if (versionMatchesFilter(item, 'blocked')) return 1;
    if (versionMatchesFilter(item, 'scan')) return 2;
    if (versionMatchesFilter(item, 'compare')) return 3;
    if (versionMatchesFilter(item, 'review')) return 4;
    if (item.current_effective) return 5;
    return 6;
  }

  function sortVersionsForDisplay(rows) {
    const sorted = [...rows];
    const byDateDesc = (left, right) => versionDateKey(right) - versionDateKey(left) || String(right.version_id || '').localeCompare(String(left.version_id || ''));
    if (state.versionSort === 'date_asc') return sorted.sort((left, right) => versionDateKey(left) - versionDateKey(right) || String(left.version_id || '').localeCompare(String(right.version_id || '')));
    if (state.versionSort === 'date_desc') return sorted.sort(byDateDesc);
    if (state.versionSort === 'effective') {
      return sorted.sort((left, right) => Number(Boolean(right.current_effective)) - Number(Boolean(left.current_effective)) || versionAttentionScore(left) - versionAttentionScore(right) || byDateDesc(left, right));
    }
    return sorted.sort((left, right) => versionAttentionScore(left) - versionAttentionScore(right) || byDateDesc(left, right));
  }

  function versionFacetCounts() {
    const filters = ['all', 'scan', 'compare', 'review', 'effective', 'blocked', 'error'];
    return Object.fromEntries(filters.map((filter) => [filter, state.versions.filter((item) => versionMatchesFilter(item, filter)).length]));
  }

  function renderVersionFacets() {
    const target = $('version-status-facets');
    if (!target) return;
    if (!state.selectedLibrary) {
      target.innerHTML = '<span class="version-facet-note">选择库后显示版本状态计数。</span>';
      return;
    }
    const counts = versionFacetCounts();
    const filters = ['all', 'scan', 'compare', 'review', 'effective', 'blocked', 'error'];
    target.innerHTML = filters.map((filter) => `
      <button class="version-facet ${state.versionFilter === filter ? 'is-active' : ''}" data-version-facet="${filter}" type="button">
        <span>${escapeHtml(versionFilterName(filter))}</span><strong>${Number(counts[filter] || 0)}</strong>
      </button>`).join('');
    target.querySelectorAll('[data-version-facet]').forEach((button) => button.addEventListener('click', () => {
      state.versionFilter = button.dataset.versionFacet || 'all';
      $('version-status-filter').value = state.versionFilter;
      updateRouteState();
      renderVersions();
      renderVersionFacts();
    }));
  }

  function versionRoleLabel(item) {
    if (!item) return '未选择';
    if (item.current_effective) return '当前可用';
    const selected = item.version_id === state.selectedVersion?.version_id;
    if (selected) return '当前对象';
    const base = state.selectedVersion?.adjacent_base_version || state.selectedVersion?.base_version || '';
    if (base && item.version_id === base) return '建议基准';
    return '历史版本';
  }

  function versionEvidenceChips(item) {
    const scanReady = Boolean(item.scan_evidence_ready);
    const diffStatus = String(item.diff_status || 'NOT_APPLICABLE').toUpperCase();
    const releaseStatus = String(item.release_status || 'UNKNOWN').toUpperCase();
    const scanLabel = scanFactLabel(item);
    const diffLabel = compareFactLabel(item);
    const diffClass = !scanReady && hasCompareRecord(item) ? 'is-warn' : versionStageClass(diffStatus);
    const releaseText = releaseLabel(releaseStatus);
    return `<div class="version-evidence-stack" aria-label="证据状态">
      <span class="mini-chip ${scanReady ? 'is-good' : 'is-warn'}">扫 ${escapeHtml(scanLabel)}</span>
      <span class="mini-chip ${diffClass}">比 ${escapeHtml(diffLabel)}</span>
      <span class="mini-chip ${releaseStatusClass(releaseStatus).replace('status-', 'is-')}">发 ${escapeHtml(releaseText)}</span>
    </div>`;
  }

  function versionRowActions(item) {
    const readiness = item.action_readiness || {};
    const disabled = state.activeAction ? ' disabled' : '';
    const detail = item.version_detail_url
      ? `<button class="table-action-link" data-version-row-action="open" data-version-id="${escapeHtml(item.version_id)}" type="button"${disabled}>详情</button>`
      : '';
    const scan = readiness.scan?.enabled
      ? `<button class="table-action-link" data-version-row-action="scan" data-version-id="${escapeHtml(item.version_id)}" type="button"${disabled}>扫描</button>`
      : '';
    const compare = readiness.compare?.enabled
      ? `<button class="table-action-link" data-version-row-action="compare" data-version-id="${escapeHtml(item.version_id)}" type="button"${disabled}>对比</button>`
      : '';
    return `<div class="version-row-actions">${detail}${scan}${compare}</div>`;
  }

  function deriveVersionTask(item) {
    const scanReady = Boolean(item?.scan_evidence_ready);
    const scanStatus = String(item?.scan_status || '').toUpperCase();
    const base = String(item?.adjacent_base_version || item?.base_version || '');
    const changeSummary = String(item?.change_summary || '');
    const diffReady = Boolean(item?.diff_evidence_ready) || /已生成对比|对比完成|无变化/.test(changeSummary) || ['PASS', 'DIFFED', 'COMPARED', 'DONE'].includes(String(item?.diff_status || '').toUpperCase());
    if (!scanReady && ['PASS', 'PASSED', 'SCANNED', 'DONE'].includes(scanStatus)) {
      return { state: '需补扫', action: '补扫', kind: 'review', base, note: '目录里有扫描记录，但扫描证据文件不可用；请重新扫描补齐证据。' };
    }
    if (!scanReady) return { state: '待扫描', action: '扫描', kind: 'review', base, note: '先生成当前版本的扫描事实。' };
    if (!base) return { state: '首版事实已就绪', action: '查看扫描结果', kind: 'open', base: '', note: '没有可比基准，当前版本只需查看扫描事实。' };
    if (!diffReady) return { state: '待对比', action: '对比', kind: 'review', base, note: `使用建议基准 ${base} 生成版本变化。` };
    return { state: '审查事实已就绪', action: '打开详情', kind: 'open', base, note: '扫描和对比事实已生成，可查看版本详情页。' };
  }

  function scanFactLabel(item) {
    if (item?.scan_evidence_ready) return '扫描已就绪';
    const status = String(item?.scan_status || 'NOT_SCANNED').toUpperCase();
    if (['PASS', 'PASSED', 'SCANNED', 'DONE'].includes(status)) return '扫描记录缺证据';
    return statusLabel(status);
  }

  function hasCompareRecord(item) {
    const diffStatus = String(item?.diff_status || 'NOT_APPLICABLE').toUpperCase();
    const summary = String(item?.change_summary || '');
    return !['', 'PENDING', 'NOT_APPLICABLE'].includes(diffStatus)
      || /已生成对比|已对比|无变化|对比记录待验证|\+/.test(summary);
  }

  function compareFactLabel(item) {
    const diffStatus = String(item?.diff_status || 'NOT_APPLICABLE').toUpperCase();
    if (!item?.scan_evidence_ready && hasCompareRecord(item)) return '对比记录待验证';
    if (diffStatus === 'NOT_APPLICABLE') return '无需对比';
    return item?.change_summary || statusLabel(diffStatus);
  }

  function filteredVersions() {
    const query = state.versionQuery.trim().toLowerCase();
    const filtered = state.versions.filter((item) => {
      const searchable = `${item.version_id || ''} ${item.package_type || ''} ${item.adjacent_base_version || ''} ${item.base_version || ''} ${item.release_status || ''}`.toLowerCase();
      const matchesQuery = !query || searchable.includes(query);
      if (!matchesQuery) return false;
      return versionMatchesFilter(item, state.versionFilter);
    });
    return sortVersionsForDisplay(filtered);
  }

  function visibleVersions(allRows = filteredVersions()) {
    const rows = allRows.slice(0, state.versionRenderLimit);
    const selectedId = state.selectedVersion?.version_id;
    if (!selectedId || rows.some((item) => item.version_id === selectedId)) return rows;
    const selected = allRows.find((item) => item.version_id === selectedId);
    return selected ? [...rows, selected] : rows;
  }

  function renderVersions() {
    const allRows = filteredVersions();
    const rows = visibleVersions(allRows);
    renderVersionFacets();
    const filterName = versionFilterName(state.versionFilter);
    const loadedText = state.versionTotal > state.versions.length ? `已读取 ${state.versions.length} / ${state.versionTotal}` : `${state.versionTotal || state.versions.length}`;
    $('version-count').textContent = state.versionsLoading ? '读取中' : allRows.length === state.versions.length ? `${loadedText} 个版本` : `${filterName} ${allRows.length} / ${state.versions.length}`;
    const pageSummary = $('version-pagination-summary');
    const loadMore = $('load-more-versions');
    if (pageSummary) {
      const showing = Math.min(rows.length, allRows.length);
      const filteredNote = allRows.length === state.versions.length ? '' : `，筛选命中 ${allRows.length}`;
      pageSummary.textContent = state.versionTotal
        ? `当前显示 ${showing}，已读取 ${state.versions.length} / ${state.versionTotal}${filteredNote}`
        : '未加载版本';
    }
    if (loadMore) {
      const hasHiddenLoadedRows = rows.length < allRows.length;
      const canLoadMore = hasHiddenLoadedRows || state.versionHasMore;
      loadMore.classList.toggle('hidden', !canLoadMore);
      loadMore.disabled = state.versionsLoadingMore || Boolean(state.activeAction);
      loadMore.textContent = state.versionsLoadingMore ? '正在加载…' : hasHiddenLoadedRows ? `再显示 ${VERSION_RENDER_BATCH} 个` : '继续读取版本';
    }
    if (state.versionsLoading) {
      $('version-table-body').innerHTML = '<tr><td colspan="7" class="empty-cell">正在读取版本列表…</td></tr>';
      return;
    }
    if (state.versionLoadError) {
      $('version-table-body').innerHTML = `<tr><td colspan="7" class="empty-cell">${escapeHtml(state.versionLoadError)}</td></tr>`;
      return;
    }
    $('version-table-body').innerHTML = rows.length ? rows.map((item) => `
      <tr class="version-row ${item.version_id === state.selectedVersion?.version_id ? 'selected' : ''}" data-version="${escapeHtml(item.version_id)}">
        <td><button class="version-link" type="button" title="${escapeHtml(item.version_id)}">${escapeHtml(item.version_id)}</button></td>
        <td><span class="role-label">${escapeHtml(versionRoleLabel(item))}</span></td>
        <td><span class="package-pill">${escapeHtml(packageLabel(item.package_type))}</span></td>
        <td><code class="base-version-cell" title="${escapeHtml(item.adjacent_base_version || item.base_version || '')}">${escapeHtml(item.adjacent_base_version || item.base_version || '无基准')}</code></td>
        <td>${versionEvidenceChips(item)}</td>
        <td class="change-summary" title="${escapeHtml(deriveVersionTask(item).note)}"><strong>${escapeHtml(item.change_summary || deriveVersionTask(item).state)}</strong><small>${escapeHtml(deriveVersionTask(item).state)}</small></td>
        <td>${versionRowActions(item)}</td>
      </tr>`).join('') : `<tr><td colspan="7" class="empty-cell">${state.versions.length ? '没有符合筛选条件的版本。' : '该库没有版本记录。'}</td></tr>`;
    document.querySelectorAll('[data-version]').forEach((row) => row.addEventListener('click', () => selectVersion(row.dataset.version)));
    document.querySelectorAll('[data-version-row-action]').forEach((button) => button.addEventListener('click', async (event) => {
      event.stopPropagation();
      const versionId = button.dataset.versionId || '';
      const action = button.dataset.versionRowAction || '';
      if (versionId && state.selectedVersion?.version_id !== versionId) selectVersion(versionId, { rerender: true });
      if (action === 'open') return openVersionDetail();
      if (action === 'scan' || action === 'compare') return runAction(action);
    }));
  }

  function setActionDeckState(name, availability) {
    const ids = {
      scan: ['scan-action-state', 'scan-action-note'],
      compare: ['compare-action-state', 'compare-action-note'],
      'file-diff': ['file-diff-action-state', 'file-diff-action-note'],
      review: ['review-action-state', 'review-action-note'],
      'release-check': ['release-action-state', 'release-action-note'],
    };
    const [stateId, noteId] = ids[name] || [];
    const stateChip = stateId ? $(stateId) : null;
    const note = noteId ? $(noteId) : null;
    if (!stateChip || !note) return;
    const enabled = Boolean(availability?.enabled);
    stateChip.textContent = availability?.label || '等待对象';
    stateChip.className = `status-chip ${enabled ? 'status-good' : 'status-neutral'}`;
    note.textContent = availability?.reason || '选择版本后显示执行条件。';
  }

  function renderActionDeckReadiness(item, readiness = {}) {
    const base = String(item?.adjacent_base_version || item?.base_version || '');
    const fileDiff = item
      ? { enabled: Boolean(base), label: base ? '可选择文件' : '缺少基准', reason: base ? '从变化清单选择成对文件，或填写同路径文件。' : '需要先指定可对比的基准版本。' }
      : { enabled: false, label: '等待对象', reason: '选择版本后可以选择文件。' };
    const review = item
      ? { enabled: true, label: '可记录', reason: '可查看门禁、准备审查记录或记录人工结论。' }
      : { enabled: false, label: '等待对象', reason: '选择版本后可以记录审查结论。' };
    setActionDeckState('scan', readiness.scan);
    setActionDeckState('compare', readiness.compare);
    setActionDeckState('file-diff', fileDiff);
    setActionDeckState('review', review);
    setActionDeckState('release-check', readiness['release-check']);
    const fileButton = $('open-file-diff');
    const reviewButton = $('open-review-actions');
    if (fileButton) {
      fileButton.disabled = !fileDiff.enabled || Boolean(state.activeAction);
      fileButton.title = fileDiff.reason;
    }
    if (reviewButton) {
      reviewButton.disabled = !review.enabled || Boolean(state.activeAction);
      reviewButton.title = review.reason;
    }
  }

  function setActionDeckMessage(message) {
    const note = $('action-deck-note');
    if (note) note.textContent = message;
  }

  function renderActionDeckNavigation(item) {
    const button = $('open-version-detail-button');
    if (!button) return;
    const detailUrl = String(item?.version_detail_url || '');
    button.disabled = !detailUrl || Boolean(state.activeAction);
    button.textContent = detailUrl ? '打开版本详情' : item ? '详情尚未生成' : '选择版本';
    button.title = detailUrl ? '打开当前版本的详情页。' : item ? '完成扫描或对比后可生成详情页。' : '请先从版本列表选择版本。';
  }

  function openVersionDetail() {
    const detailUrl = String(state.selectedVersion?.version_detail_url || '');
    if (detailUrl) window.location.assign(detailUrl);
  }

  function openFileDiffWorkbench() {
    if (!$('open-file-diff') || $('open-file-diff').disabled) return;
    activateWorkspaceTab('changes');
    const selection = $('file-change-selection');
    if (selection) selection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function openReviewActions() {
    if (!$('open-review-actions') || $('open-review-actions').disabled) return;
    const details = $('review-actions-details');
    if (details) {
      details.open = true;
      details.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    $('review-gate-operation')?.focus();
  }

  function renderVersionFacts() {
    const item = state.selectedVersion;
    const library = state.libraries.find((row) => row.library_name === state.selectedLibrary);
    const pendingWindow = library?.pending_window || {};
    const hasSuggestion = Boolean(pendingWindow.exists) && pendingWindow.state !== 'INVALID';
    const hasCandidate = pendingWindow.state === 'PENDING'
      && Boolean(pendingWindow.candidate_effective_id)
      && pendingWindow.candidate_manifest_exists !== false;
    document.querySelectorAll('[data-action]').forEach((button) => { button.disabled = true; button.classList.remove('is-busy'); });
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
      const workflowAction = button.dataset.workflowAction;
      const isReadSuggestion = workflowAction === 'window';
      const isAccept = workflowAction === 'accept-window';
      button.disabled = !state.selectedLibrary
        || Boolean(state.activeAction)
        || (isReadSuggestion && !hasSuggestion)
        || (isAccept && !hasCandidate);
      button.title = isReadSuggestion && !hasSuggestion
        ? '当前还没有接入建议，请先生成处理建议。'
        : isAccept && !hasCandidate
          ? '当前没有可确认的新版本，请先生成处理建议或处理计划。'
          : '';
    });
    document.querySelectorAll('[data-correction-action]').forEach((button) => { button.disabled = !item || Boolean(state.activeAction); });
    if (!item) {
      $('flow-object-value').textContent = '未选择版本';
      $('flow-facts-value').textContent = '等待扫描与对比';
      $('flow-release-value').textContent = '未检查';
      $('version-role').textContent = '未选择';
      $('version-role').className = 'status-chip status-neutral';
      $('selected-version-id').textContent = '未选择版本';
      $('version-decision').textContent = '未选择版本';
      $('version-decision-note').textContent = '选择版本后显示是否需要处理。';
      $('current-processing-title').textContent = '请选择一个版本';
      $('current-processing-base').textContent = '选择版本后显示';
      $('current-processing-state').textContent = '未选择';
      $('current-processing-state').className = 'status-chip status-neutral';
      $('version-focus-target').textContent = '未选择版本';
      $('version-focus-base').textContent = '未选择版本';
      $('version-focus-effective').textContent = library?.current_effective || '未设置';
      $('version-focus-facts').textContent = '等待选择';
      renderActionDeckReadiness(null);
      renderActionDeckNavigation(null);
      setActionDeckMessage('选择版本后可以独立执行扫描、对比、深度文件核对、审查记录和发布检查。');
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
    const task = deriveVersionTask(item);
    const reviewDecision = item.workflow_status || { label: '待处理', reason: '请按动作条件补齐事实。', next_action: '查看详情' };
    $('flow-object-value').textContent = item.version_id || '未选择版本';
    $('flow-facts-value').textContent = `扫描 ${scanFactLabel(item)} · 对比 ${compareFactLabel(item)}`;
    $('flow-release-value').textContent = releaseLabel(item.release_status);
    $('version-role').textContent = item.current_effective ? '当前可用' : stageLabel(item.stage);
    $('version-role').className = `status-chip ${item.current_effective ? 'status-good' : 'status-neutral'}`;
    $('selected-version-id').textContent = item.version_id;
    $('version-decision').textContent = reviewDecision.label;
    $('version-decision-note').textContent = reviewDecision.reason;
    $('current-processing-title').textContent = item.version_id;
    $('current-processing-base').textContent = task.base || '无可比基准（首版）';
    $('current-processing-base').title = task.base || '无可比基准（首版）';
    $('current-processing-state').textContent = task.state;
    $('current-processing-state').className = `status-chip ${task.state === '审查事实已就绪' ? 'status-good' : task.state === '需补扫' ? 'status-warn' : task.state === '待扫描' || task.state === '待对比' ? 'status-neutral' : 'status-neutral'}`;
    $('version-focus-target').textContent = item.version_id || '未选择版本';
    $('version-focus-base').textContent = task.base || '无可比基准';
    $('version-focus-effective').textContent = library?.current_effective || '未设置';
    $('version-focus-facts').textContent = `扫描 ${scanFactLabel(item)} · 对比 ${compareFactLabel(item)} · ${releaseLabel(item.release_status)}`;
    const detail = item.version_detail_url ? `<a class="text-link" href="${item.version_detail_url}" target="_blank" rel="noreferrer">打开版本详情页 ↗</a>` : '<span class="muted">版本详情尚未生成</span>';
    $('version-facts').innerHTML = [
      ['包类型', packageLabel(item.package_type)], ['版本角色', item.current_effective ? '当前可用' : stageLabel(item.stage)], ['对比基准', item.base_version || '未设置'],
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
    renderActionDeckReadiness(item, readiness);
    renderActionDeckNavigation(item);
    $('write-action-hint').textContent = workflowWindowHint(pendingWindow);
    setActionDeckMessage(task.note);
    renderFileChangeWorkbench();
    renderFileTree();
  }

  function workflowWindowHint(windowState) {
    if (windowState.state === 'INVALID') return '接入建议文件无法读取，请重新生成接入建议。';
    if (windowState.state !== 'PENDING') return '当前没有可确认的新版本；请先生成处理建议。';
    if (!windowState.candidate_effective_id) return '已有接入建议，但还没有可确认的新版本。';
    if (windowState.candidate_manifest_exists === false) return '候选版本缺少完整清单，请先生成处理计划。';
    return `可确认的新版本：${windowState.candidate_effective_id}`;
  }

  function renderWorkspaceSettings() {
    const settings = state.workspace?.scan_strategy || {};
    const discovery = state.workspace?.discovery_strategy || {};
    const paths = state.workspace?.paths || {};
    if ($('config-raw-root')) $('config-raw-root').value = paths.raw_root || '';
    if ($('config-discover-max-depth')) $('config-discover-max-depth').value = String(discovery.max_depth || '4');
    if ($('config-discover-min-versions')) $('config-discover-min-versions').value = String(discovery.min_versions || '1');
    if ($('config-discover-max-dirs')) $('config-discover-max-dirs').value = String(discovery.max_dirs || '5000');
    if ($('config-discover-max-candidates')) $('config-discover-max-candidates').value = String(discovery.max_candidates || '200');
    if ($('candidate-max-depth')) $('candidate-max-depth').value = String(discovery.max_depth || '4');
    if ($('candidate-min-versions')) $('candidate-min-versions').value = String(discovery.min_versions || '1');
    if ($('candidate-max-dirs')) $('candidate-max-dirs').value = String(discovery.max_dirs || '5000');
    if ($('candidate-max-candidates')) $('candidate-max-candidates').value = String(discovery.max_candidates || '200');
    $('hash-policy').value = settings.hash_policy || 'smart';
    $('parse-jobs').value = String(settings.parse_jobs || '8');
    $('parse-file-types').value = settings.parse_file_types || '';
    $('parse-exclude-file-types').value = settings.parse_exclude_file_types || '';
    setHashTypeChecks('[data-force-hash-type]', settings.force_hash_file_types || '');
    setHashTypeChecks('[data-skip-hash-type]', settings.skip_hash_file_types || '');
    $('render-detail').checked = settings.render_detail !== false;
    updateSettingsSummary();
    const discoverRoot = $('candidate-discover-root');
    if (discoverRoot && !discoverRoot.value.trim()) discoverRoot.value = paths.raw_root || '';
    const labels = { workspace: '工作区', raw_root: '原始库根', catalog: '目录快照', catalog_html: 'HTML 输出', reports: '扫描报告', diff: '对比报告' };
    $('workspace-paths').innerHTML = Object.entries(labels).map(([key, label]) => `<div><dt>${label}</dt><dd title="${escapeHtml(paths[key] || '未设置')}">${escapeHtml(paths[key] || '未设置')}</dd></div>`).join('');
  }

  function scanTypeList(value) {
    if (Array.isArray(value)) return value.map((item) => String(item).trim().toLowerCase()).filter(Boolean);
    return String(value || '').split(/[;,\s]+/).map((item) => item.trim().toLowerCase()).filter(Boolean);
  }

  function setHashTypeChecks(selector, value) {
    const selected = new Set(scanTypeList(value));
    document.querySelectorAll(selector).forEach((input) => { input.checked = selected.has(String(input.value).toLowerCase()); });
  }

  function updateSettingsSummary() {
    const hashLabels = { smart: '智能取证', none: '只读元数据', full: '完整内容证据' };
    const hash = hashLabels[$('hash-policy')?.value] || '智能取证';
    const jobs = $('parse-jobs')?.value || '8';
    const mode = $('compare-mode')?.value === 'cumulative' ? '累计基线' : '相邻版本';
    const evidence = $('rescan')?.checked ? '强制重扫' : $('scan-if-missing')?.checked ? '缺失时补扫' : '沿用已有证据';
    const output = $('render-detail')?.checked ? '自动刷新详情' : '仅生成事实';
    const discoverMin = $('config-discover-min-versions')?.value || $('candidate-min-versions')?.value || '1';
    const evidenceSummary = evidence === '沿用已有证据' ? '' : ` · ${evidence}`;
    const summary = $('settings-summary');
    if (!summary) return;
    const forced = Array.from(document.querySelectorAll('[data-force-hash-type]:checked')).map((input) => input.value);
    const skipped = Array.from(document.querySelectorAll('[data-skip-hash-type]:checked')).map((input) => input.value);
    const typeSummary = [forced.length ? `额外哈希 ${forced.join('/')}` : '', skipped.length ? `跳过 ${skipped.join('/')}` : ''].filter(Boolean).join(' · ');
    summary.textContent = `${hash}${typeSummary ? ` · ${typeSummary}` : ''} · 并发 ${jobs} · 发现≥${discoverMin}版 · ${mode}${evidenceSummary} · ${output}`;
    summary.title = `扫描：${hash}${typeSummary ? `；${typeSummary}` : ''}；解析并发：${jobs}；发现最少版本数：${discoverMin}；对比：${mode}；证据：${evidence}；输出：${output}`;
  }

  function renderPathBrowser(payload = null) {
    const panel = $('library-path-picker');
    const current = $('path-browser-current');
    const up = $('path-browser-up');
    const use = $('use-library-path');
    const list = $('path-browser-list');
    const error = $('path-browser-error');
    const roots = $('path-browser-roots');
    if (!panel || !current || !up || !use || !list || !error) return;
    if (roots) {
      const allowedRoots = Array.isArray(payload?.roots) ? payload.roots : [];
      roots.textContent = allowedRoots.length ? allowedRoots.join('；') : '读取中';
      roots.title = allowedRoots.join('\n');
    }
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

  function openLibraryAddForm() {
    const disclosure = $('library-add-disclosure');
    if (disclosure) disclosure.open = true;
    disclosure?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    window.requestAnimationFrame(() => $('library-add-id')?.focus());
  }

  function focusVersionActions() {
    const target = $('action-deck');
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    window.requestAnimationFrame(() => $('scan-action-button')?.focus());
  }

  function prefillLibraryAddFromCandidate(candidateId) {
    const candidate = state.libraryCandidates.find((item) => item.candidate_id === candidateId);
    if (!candidate) return;
    $('library-add-id').value = candidate.suggested_library_id || candidate.library_id || '';
    $('library-add-root').value = candidate.root_abs || '';
    $('library-add-display').value = candidate.display_name || '';
    $('library-add-vendor').value = candidate.vendor || '';
    $('library-add-middle').value = candidate.middle_path || '';
    const disclosure = $('library-add-disclosure');
    if (disclosure) disclosure.open = true;
    const note = $('library-add-prefill-note');
    if (note) note.textContent = `已带入候选库“${candidate.library_id}”。请核对正式库名和库根目录后，登记并加入目录。`;
    window.requestAnimationFrame(() => {
      $('library-add-id').focus();
      disclosure?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }

  function candidateStatusLabel(candidate) {
    if (candidate.already_registered) return '已登记';
    if (candidate.name_conflict) return '名称冲突';
    const status = String(candidate.status || 'REVIEW').toUpperCase();
    if (status === 'OK') return '可登记';
    if (status === 'IGNORE') return '已忽略';
    return '待确认';
  }

  function visibleLibraryCandidates() {
    const query = state.candidateQuery.trim().toLowerCase();
    return state.libraryCandidates.filter((candidate) => {
      const statusMatches = state.candidateStatus === 'all'
        || (state.candidateStatus === 'registered' && candidate.already_registered)
        || (state.candidateStatus !== 'registered' && String(candidate.status || '').toUpperCase() === state.candidateStatus);
      if (!statusMatches) return false;
      if (!query) return true;
      return [candidate.suggested_library_id, candidate.library_id, candidate.display_name, candidate.vendor, candidate.root_abs, candidate.reason]
        .some((value) => String(value || '').toLowerCase().includes(query));
    });
  }

  function renderLibraryCandidates() {
    const body = $('candidate-table-body');
    const status = $('candidate-snapshot-status');
    const note = $('candidate-snapshot-note');
    const selected = Array.from(state.selectedCandidateIds);
    const register = $('register-selected-candidates');
    if (!body || !status || !note || !register) return;
    const snapshot = state.candidateSnapshot;
    status.textContent = state.candidateLoading ? '读取中' : snapshot?.status === 'READY' ? `候选 ${state.libraryCandidates.length}` : snapshot?.status === 'MISSING' ? '尚未发现' : '快照异常';
    status.className = `status-chip ${state.candidateLoading ? 'status-neutral' : snapshot?.status === 'READY' ? 'status-good' : snapshot?.status === 'MISSING' ? 'status-neutral' : 'status-bad'}`;
    if (state.candidateLoading) {
      note.textContent = '正在读取最近一次候选快照，不会重新扫描原始库目录。';
      body.innerHTML = '<tr><td colspan="6" class="muted">读取候选快照中…</td></tr>';
    } else if (state.candidateError) {
      note.textContent = state.candidateError;
      body.innerHTML = '<tr><td colspan="6" class="muted">候选快照暂不可用。</td></tr>';
    } else if (!snapshot || snapshot.status === 'MISSING') {
      note.textContent = '尚无候选快照。先设置发现范围并执行“发现候选库”；该操作只生成候选，不会登记任何库。';
      body.innerHTML = '<tr><td colspan="6" class="muted">尚未发现候选库。</td></tr>';
    } else {
      const visible = visibleLibraryCandidates();
      const registered = state.libraryCandidates.filter((candidate) => candidate.already_registered).length;
      const warning = Array.isArray(snapshot.warnings) && snapshot.warnings.length ? `；提醒：${snapshot.warnings[0]}` : '';
      note.textContent = `快照共 ${state.libraryCandidates.length} 项，已登记 ${registered} 项，当前显示 ${visible.length} 项${snapshot.truncated ? '；发现结果已达到上限，请收窄范围后重试' : ''}${warning}`;
      if (!visible.length) {
        body.innerHTML = '<tr><td colspan="6" class="muted">没有符合当前筛选条件的候选库。</td></tr>';
      } else {
        body.innerHTML = visible.map((candidate) => {
          const checked = state.selectedCandidateIds.has(candidate.candidate_id);
          const disabled = Boolean(candidate.already_registered || candidate.name_conflict);
          const versions = Number(candidate.version_count || 0);
          const confidence = Number(candidate.confidence);
          const reason = candidate.reason || '仅有候选表信息；请确认库根后登记。';
          const singleVersion = versions === 1;
          const detail = [candidate.vendor, candidate.middle_path].filter(Boolean).join(' / ');
          const versionDetail = candidate.example_versions?.length ? candidate.example_versions.join('，') : '';
          const suggestedId = candidate.suggested_library_id || candidate.library_id;
          return `<tr class="${disabled ? 'is-registered' : ''}">
            <td><input data-candidate-id="${escapeHtml(candidate.candidate_id)}" type="checkbox" ${checked ? 'checked' : ''} ${disabled ? 'disabled' : ''} aria-label="选择 ${escapeHtml(candidate.library_id)}"></td>
            <td><code title="${escapeHtml(suggestedId)}">${escapeHtml(suggestedId)}</code><small>${escapeHtml(candidate.library_id === suggestedId ? (detail || '未标注') : `候选名：${candidate.library_id}`)}</small></td>
            <td><code title="${escapeHtml(candidate.root_abs)}">${escapeHtml(candidate.root_abs)}</code></td>
            <td>${versions || '—'}${singleVersion ? '<span class="candidate-warn">单版本，需确认</span>' : ''}${versionDetail ? `<small title="${escapeHtml(versionDetail)}">${escapeHtml(versionDetail)}</small>` : ''}</td>
            <td>${escapeHtml(reason)}${singleVersion ? '<small>只有一个交付实例，系统不会自动证明它是完整库，请确认库根后登记。</small>' : ''}${Number.isFinite(confidence) ? `<small>置信度 ${confidence.toFixed(2)}</small>` : ''}</td>
            <td><span>${escapeHtml(candidateStatusLabel(candidate))}</span>${disabled ? '' : `<button class="button button-secondary button-small candidate-use" data-candidate-use="${escapeHtml(candidate.candidate_id)}" type="button">使用此候选</button>`}</td>
          </tr>`;
        }).join('');
        body.querySelectorAll('[data-candidate-id]').forEach((input) => input.addEventListener('change', () => {
          const candidateId = input.dataset.candidateId;
          if (!candidateId) return;
          if (input.checked) state.selectedCandidateIds.add(candidateId);
          else state.selectedCandidateIds.delete(candidateId);
          renderLibraryCandidates();
        }));
        body.querySelectorAll('[data-candidate-use]').forEach((button) => button.addEventListener('click', () => {
          prefillLibraryAddFromCandidate(button.dataset.candidateUse);
        }));
      }
    }
    register.disabled = state.activeAction !== null || selected.length === 0;
    $('candidate-selection-summary').textContent = selected.length ? `已选择 ${selected.length} 个候选库；登记后仍需点击“应用库登记”更新正式目录。` : '尚未选择候选库；勾选确认的库根后再登记。';
  }

  async function loadLibraryCandidates() {
    state.candidateLoading = true;
    state.candidateError = '';
    renderLibraryCandidates();
    try {
      const snapshot = await getJson('/api/library-candidates');
      state.candidateSnapshot = snapshot;
      state.libraryCandidates = Array.isArray(snapshot.candidates) ? snapshot.candidates : [];
      const available = new Set(state.libraryCandidates.filter((item) => !item.already_registered && !item.name_conflict).map((item) => item.candidate_id));
      state.selectedCandidateIds = new Set(Array.from(state.selectedCandidateIds).filter((id) => available.has(id)));
    } catch (error) {
      state.candidateSnapshot = null;
      state.libraryCandidates = [];
      state.selectedCandidateIds = new Set();
      state.candidateError = `读取候选快照失败：${error.message}`;
    } finally {
      state.candidateLoading = false;
      renderLibraryCandidates();
    }
  }

  function strategyPayload() {
    return {
      hash_policy: $('hash-policy').value,
      force_hash_file_types: Array.from(document.querySelectorAll('[data-force-hash-type]:checked')).map((input) => input.value),
      skip_hash_file_types: Array.from(document.querySelectorAll('[data-skip-hash-type]:checked')).map((input) => input.value),
      parse_jobs: $('parse-jobs').value,
      parse_file_types: $('parse-file-types').value.trim(),
      parse_exclude_file_types: $('parse-exclude-file-types').value.trim(),
      no_render: !$('render-detail').checked,
    };
  }

  function workspaceConfigPayload() {
    return {
      raw_root: $('config-raw-root')?.value.trim() || '',
      parse_jobs: $('parse-jobs').value,
      hash_policy: $('hash-policy').value,
      force_hash_file_types: Array.from(document.querySelectorAll('[data-force-hash-type]:checked')).map((input) => input.value),
      skip_hash_file_types: Array.from(document.querySelectorAll('[data-skip-hash-type]:checked')).map((input) => input.value),
      parse_file_types: $('parse-file-types').value.trim(),
      parse_exclude_file_types: $('parse-exclude-file-types').value.trim(),
      render_detail: $('render-detail').checked,
      discover_max_depth: $('config-discover-max-depth')?.value || $('candidate-max-depth')?.value || '4',
      discover_min_versions: $('config-discover-min-versions')?.value || $('candidate-min-versions')?.value || '1',
      discover_max_dirs: $('config-discover-max-dirs')?.value || $('candidate-max-dirs')?.value || '5000',
      discover_max_candidates: $('config-discover-max-candidates')?.value || $('candidate-max-candidates')?.value || '200',
    };
  }

  function showSettingsFeedback(message = '', kind = 'info') {
    const feedback = $('settings-save-feedback');
    if (!feedback) return;
    feedback.textContent = message;
    feedback.classList.toggle('hidden', !message);
    feedback.classList.toggle('is-error', kind === 'error');
  }

  async function saveWorkspaceSettings() {
    if (state.settingsSaving) return;
    state.settingsSaving = true;
    const button = $('save-settings');
    if (button) button.disabled = true;
    showSettingsFeedback('正在保存工作区默认配置…');
    try {
      const payload = await getJson('/api/workspace/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(workspaceConfigPayload()),
      });
      state.workspace = { ...(state.workspace || {}), paths: payload.paths, scan_strategy: payload.scan_strategy, discovery_strategy: payload.discovery_strategy };
      renderWorkspaceSettings();
      showSettingsFeedback(`已保存默认配置；备份：${payload.backup || '已生成'}`);
    } catch (error) {
      showSettingsFeedback(`保存失败：${error.message}`, 'error');
    } finally {
      state.settingsSaving = false;
      if (button) button.disabled = false;
    }
  }

  async function refreshVersionsForSelectedLibrary(requestId = state.libraryRequestId, append = false) {
    if (!state.selectedLibrary) return;
    const libraryName = state.selectedLibrary;
    const offset = append ? state.versions.length : 0;
    const previousSelectedId = state.selectedVersion?.version_id || '';
    if (append) state.versionsLoadingMore = true;
    else state.versionsLoading = true;
    renderVersions();
    const payload = await getJson(`/api/libraries/${encodeURIComponent(libraryName)}/versions?offset=${offset}&limit=100`);
    if (requestId !== state.libraryRequestId || libraryName !== state.selectedLibrary) return;
    const selectedId = state.selectedVersion?.version_id || state.requestedVersionId;
    state.versions = append ? [...state.versions, ...payload.versions] : payload.versions;
    state.versionTotal = Number(payload.pagination?.total ?? state.versions.length);
    state.versionHasMore = payload.pagination?.next_offset !== null && payload.pagination?.next_offset !== undefined;
    state.versionsLoading = false;
    state.versionsLoadingMore = false;
    state.versionLoadError = '';
    state.selectedVersion = state.versions.find((item) => item.version_id === selectedId) || state.versions[0] || null;
    if (state.selectedVersion?.version_id === state.requestedVersionId) state.requestedVersionId = '';
    if (!append) state.versionRenderLimit = VERSION_RENDER_BATCH;
    const selectedChanged = previousSelectedId !== (state.selectedVersion?.version_id || '');
    if (!append || selectedChanged) resetSelectedVersionEvidence();
    renderVersions();
    renderVersionFacts();
    if (!append || selectedChanged) await refreshActiveEvidenceForSelectedVersion(requestId);
  }

  async function selectLibrary(name) {
    const requestId = ++state.libraryRequestId;
    const preserveRouteSelection = name === state.selectedLibrary && state.versions.length === 0;
    state.selectedLibrary = name;
    state.selectedVersion = null;
    resetSelectedVersionEvidence();
    state.versions = [];
    state.versionTotal = 0;
    state.versionHasMore = false;
    state.versionsLoadingMore = false;
    state.versionRenderLimit = VERSION_RENDER_BATCH;
    state.versionsLoading = true;
    state.versionLoadError = '';
    if (!preserveRouteSelection) {
      state.versionQuery = '';
      state.versionFilter = 'all';
      $('version-filter').value = '';
      $('version-status-filter').value = 'all';
    }
    updateRouteState();
    renderLibraries();
    const library = state.libraries.find((item) => item.library_name === name);
    $('selected-library').textContent = library?.display_name || name;
    $('selected-library-crumb').textContent = library?.display_name || name;
    $('selected-library-meta').textContent = `${name} · ${library ? libraryMetaLine(library) : '正在读取版本'} · 正在读取版本`;
    renderMetrics(library);
    renderVersions();
    renderVersionFacts();
    try {
      await refreshVersionsForSelectedLibrary(requestId);
      if (requestId === state.libraryRequestId) $('selected-library-meta').textContent = `${name} · ${library ? libraryMetaLine(library) : '未标注库信息'}`;
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
    state.requestedVersionId = '';
    resetSelectedVersionEvidence();
    if (rerender) renderVersions();
    renderVersionFacts();
    updateRouteState();
    refreshActiveEvidenceForSelectedVersion().catch(() => {});
  }

  async function loadLibraries(preferredLibrary = '') {
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
      const selected = state.libraries.find((item) => item.library_name === preferredLibrary)
        || state.libraries.find((item) => item.library_name === state.selectedLibrary)
        || state.libraries[0];
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

  function showLibraryAddFeedback(message = '') {
    const feedback = $('library-add-feedback');
    if (!feedback) return;
    feedback.textContent = message;
    feedback.classList.toggle('hidden', !message);
  }

  function setActionBusy(action) {
    state.activeAction = action;
    document.querySelectorAll('[data-action], [data-workflow-action], [data-correction-action], [data-command-action]').forEach((button) => {
      button.disabled = true;
      if (button.dataset.action === action || button.dataset.workflowAction === action || button.dataset.correctionAction === action) button.classList.add('is-busy');
      if (button.dataset.commandAction === action) button.classList.add('is-busy');
    });
    renderLibraryCandidates();
  }

  function clearActionBusy() {
    state.activeAction = null;
    document.querySelectorAll('[data-action], [data-workflow-action], [data-correction-action], [data-command-action]').forEach((button) => button.classList.remove('is-busy'));
    renderVersionFacts();
    renderLibraryCandidates();
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
    'effective-rollback': '当前可用版本回退',
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
    if (action === 'library-discover') return {
      root: $('candidate-discover-root').value.trim(),
      max_depth: $('candidate-max-depth').value,
      min_versions: $('candidate-min-versions').value,
      max_dirs: $('candidate-max-dirs').value,
      max_candidates: $('candidate-max-candidates').value,
    };
    if (action === 'library-accept') return { candidate_ids: Array.from(state.selectedCandidateIds) };
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
    if (action === 'library-add') return '即将登记新库、应用库映射并刷新目录。不会扫描或改动已有库。是否继续？';
    if (action === 'library-accept') return `即将登记已勾选的 ${state.selectedCandidateIds.size} 个候选库。原始候选快照不会被改写，登记后还需单独应用库登记。是否继续？`;
    if (action === 'effective-rollback') return '即将回退当前可用版本，此操作会写入状态和审计记录。是否继续？';
    return `即将执行${COMMAND_LABELS[action]}，结果会写入工作区运行记录。是否继续？`;
  }

  async function runCommand(action) {
    const endpoint = commandEndpoint(action);
    if (!endpoint || state.activeAction) return;
    if (action === 'library-add') showLibraryAddFeedback();
    if (action === 'library-accept' && state.selectedCandidateIds.size === 0) {
      showError('请先在候选库表中勾选至少一个确认的库根。', { action: true });
      return;
    }
    if (commandNeedsConfirmation(action) && !window.confirm(commandConfirmation(action))) return;
    const payload = commandPayload(action);
    setActionBusy(action);
    try {
      const result = await getJson(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      await startJob(result, COMMAND_LABELS[action], null, action, {
        registeredLibrary: action === 'library-add' ? payload.library_id : '',
      });
    } catch (error) {
      clearActionBusy();
      if (action === 'library-add') showLibraryAddFeedback(error.message);
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
    const target = action === 'accept-window' ? `设为当前可用版本：${candidate || '未生成'}` : action === 'intake-apply' ? '执行完整处理计划' : '按处理建议执行';
    return `即将${target}\n库：${state.selectedLibrary}\n${action === 'accept-window' ? '接受人：' + ($('accepted-by').value.trim() || '未填写') : '当前页面只提交已选择的工作区策略'}\n是否继续？`;
  }

  function renderJobObservation(result, elapsedMs = 0) {
    const progress = result.progress || {};
    const rawPercent = progress.percent;
    const percent = rawPercent === null || rawPercent === undefined || rawPercent === ''
      ? Number.NaN
      : Number(rawPercent);
    const hasPercent = Number.isFinite(percent) && percent >= 0 && percent <= 100;
    const terminal = result.return_code != null || ['COMPLETED', 'FAILED'].includes(String(result.status || '').toUpperCase());
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

  async function startJob(result, label, workflowAction = null, commandAction = null, context = {}) {
    state.activeJob = { label, workflowAction, commandAction, ...context };
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
    $('job-log-size').textContent = '原文 0 B，已显示 0 B';
    $('job-log-link').classList.add('hidden');
    $('job-log-link').removeAttribute('href');
    if (state.pollTimer) clearInterval(state.pollTimer);
    const completion = new Promise((resolve, reject) => { state.jobWaiter = { resolve, reject }; });
    state.pollTimer = setInterval(() => pollJob(result.job_id), 1000);
    await pollJob(result.job_id);
    return completion;
  }

  async function runAction(action, payloadOverrides = null) {
    if (!state.selectedLibrary || !state.selectedVersion || state.activeAction) return;
    const payload = { ...actionPayload(action), ...(payloadOverrides || {}) };
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
      $('workflow-summary').textContent = '设为当前可用版本前必须填写确认人。';
      return;
    }
    const endpointAction = action === 'next-preview' || action === 'next-apply' ? 'next' : action === 'intake-preview' || action === 'intake-apply' ? 'intake' : action;
    const payload = workflowRequest(action);
    setActionBusy(action);
    try {
      const result = await getJson(`/api/libraries/${encodeURIComponent(state.selectedLibrary)}/${endpointAction}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      setWorkflowStatus(result.status, statusClass(result.status));
      $('workflow-summary').textContent = `${endpointAction === 'window' ? '查看接入建议' : endpointAction === 'next' ? '生成处理建议' : endpointAction === 'intake' ? '生成处理计划' : '确认当前可用版本'}已提交。详情将在运行记录中更新。`;
      await startJob(result, endpointAction === 'next' ? '处理建议' : endpointAction === 'intake' ? '处理计划' : endpointAction === 'accept-window' ? '确认当前可用版本' : '查看建议', action);
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
      const terminal = result.return_code != null || ['COMPLETED', 'FAILED'].includes(String(result.status || '').toUpperCase());
      const elapsed = state.pollStartedAt ? Date.now() - state.pollStartedAt : 0;
      const elapsedLabel = `${Math.max(1, Math.round(elapsed / 1000))} 秒`;
      renderJobObservation(result, elapsed);
      $('job-summary').textContent = terminal
        ? (result.result_summary
          ? result.result_summary
          : result.return_code == null
            ? `任务 ${jobId} 的结果无法确认。${result.message || ''}`
            : `任务 ${jobId} 已结束，返回码 ${result.return_code}。`)
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
          setWorkflowStatus(elapsed >= JOB_TIMEOUT_MS && !terminal ? 'RUNNING' : result.status, statusClass(result.status));
          $('workflow-summary').textContent = result.return_code === 0
            ? `${completedJob.label}已完成，工作区状态已重新读取。`
            : elapsed >= JOB_TIMEOUT_MS && !terminal
              ? `${completedJob.label}运行时间过长，已停止页面轮询，请查看日志。`
              : `${completedJob.label}未成功完成，请查看最近运行中的日志和返回码。`;
        }
        clearActionBusy();
        if (terminal) {
          await loadLibraries(result.return_code === 0 ? completedJob?.registeredLibrary : '');
          if (['library-discover', 'library-accept', 'library-apply', 'library-add'].includes(completedJob?.commandAction)) {
            if (completedJob.commandAction === 'library-accept' && result.return_code === 0) state.selectedCandidateIds = new Set();
            await loadLibraryCandidates();
          }
        }
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
  $('library-filter').addEventListener('input', (event) => {
    state.libraryQuery = event.target.value;
    updateRouteState();
    renderLibraries();
  });
  [
    ['library-scope-filter', 'libraryScope'],
    ['library-kind-filter', 'libraryKind'],
    ['library-vendor-filter', 'libraryVendor'],
    ['library-platform-filter', 'libraryPlatform'],
  ].forEach(([id, key]) => {
    $(id).addEventListener('change', (event) => {
      state[key] = event.target.value;
      updateRouteState();
      renderLibraries();
    });
  });
  $('version-filter').addEventListener('input', (event) => { state.versionQuery = event.target.value; state.versionRenderLimit = VERSION_RENDER_BATCH; updateRouteState(); renderVersions(); renderVersionFacts(); });
  $('version-status-filter').addEventListener('change', (event) => { state.versionFilter = event.target.value; state.versionRenderLimit = VERSION_RENDER_BATCH; updateRouteState(); renderVersions(); renderVersionFacts(); });
  $('version-sort').addEventListener('change', (event) => { state.versionSort = event.target.value; state.versionRenderLimit = VERSION_RENDER_BATCH; updateRouteState(); renderVersions(); renderVersionFacts(); });
  $('load-more-versions').addEventListener('click', () => {
    if (state.versionsLoadingMore) return;
    const allRows = filteredVersions();
    if (visibleVersions(allRows).length < allRows.length) {
      state.versionRenderLimit += VERSION_RENDER_BATCH;
      renderVersions();
      return;
    }
    if (!state.versionHasMore) return;
    refreshVersionsForSelectedLibrary(state.libraryRequestId, true).catch((error) => {
      state.versionsLoadingMore = false;
      renderVersions();
      showError(`继续读取版本失败：${error.message}`);
    });
  });
  $('base-version').addEventListener('input', () => { $('base-version').dataset.manual = 'true'; });
  $('compare-mode').addEventListener('change', () => { syncCompareBaseForMode(); updateSettingsSummary(); });
  ['config-raw-root', 'config-discover-max-depth', 'config-discover-min-versions', 'config-discover-max-dirs', 'config-discover-max-candidates', 'hash-policy', 'parse-jobs', 'parse-file-types', 'parse-exclude-file-types', 'render-detail'].forEach((id) => {
    $(id).addEventListener('input', updateSettingsSummary);
    $(id).addEventListener('change', updateSettingsSummary);
  });
  document.querySelectorAll('[data-force-hash-type], [data-skip-hash-type]').forEach((input) => input.addEventListener('change', updateSettingsSummary));
  $('scan-if-missing').addEventListener('change', () => {
    if ($('scan-if-missing').checked) $('rescan').checked = false;
    updateSettingsSummary();
  });
  $('rescan').addEventListener('change', () => {
    if ($('rescan').checked) $('scan-if-missing').checked = false;
    updateSettingsSummary();
  });
  let fileChangeFilterTimer = null;
  $('file-change-filter').addEventListener('input', (event) => {
    state.fileChangeQuery = event.target.value.trim();
    clearTimeout(fileChangeFilterTimer);
    fileChangeFilterTimer = setTimeout(resetFileChangePageAndRefresh, 220);
  });
  $('file-change-kind-filter').addEventListener('change', (event) => {
    state.fileChangeKind = event.target.value;
    resetFileChangePageAndRefresh();
  });
  $('file-change-type-filter').addEventListener('change', (event) => {
    state.fileChangeType = event.target.value;
    resetFileChangePageAndRefresh();
  });
  $('load-more-file-changes').addEventListener('click', () => {
    if (!state.fileChangeHasMore || state.fileChangesLoading) return;
    refreshFileChangesForSelectedVersion(state.libraryRequestId, { append: true }).catch((error) => showError(error.message));
  });
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
  $('open-file-diff').addEventListener('click', openFileDiffWorkbench);
  $('open-review-actions').addEventListener('click', openReviewActions);
  $('browse-library-root').addEventListener('click', openLibraryPathPicker);
  $('close-library-path-picker').addEventListener('click', closeLibraryPathPicker);
  $('path-browser-up').addEventListener('click', () => loadPathBrowser(state.pathBrowserParent));
  $('use-library-path').addEventListener('click', useCurrentLibraryPath);
  $('library-add-root').addEventListener('input', () => showLibraryAddFeedback());
  $('candidate-filter').addEventListener('input', (event) => { state.candidateQuery = event.target.value; renderLibraryCandidates(); });
  $('candidate-status-filter').addEventListener('change', (event) => { state.candidateStatus = event.target.value; renderLibraryCandidates(); });
  $('refresh-candidates').addEventListener('click', () => loadLibraryCandidates());
  $('select-visible-candidates').addEventListener('click', () => {
    visibleLibraryCandidates().filter((candidate) => !candidate.already_registered && !candidate.name_conflict).forEach((candidate) => state.selectedCandidateIds.add(candidate.candidate_id));
    renderLibraryCandidates();
  });
  $('clear-selected-candidates').addEventListener('click', () => {
    state.selectedCandidateIds = new Set();
    renderLibraryCandidates();
  });
  $('register-selected-candidates').addEventListener('click', () => runCommand('library-accept'));
  $('reload-button').addEventListener('click', () => loadLibraries().catch((error) => showError(error.message)));
  $('reset-settings').addEventListener('click', () => {
    const settings = state.workspace?.scan_strategy || {};
    const discovery = state.workspace?.discovery_strategy || {};
    const paths = state.workspace?.paths || {};
    if ($('config-raw-root')) $('config-raw-root').value = paths.raw_root || '';
    if ($('config-discover-max-depth')) $('config-discover-max-depth').value = String(discovery.max_depth || '4');
    if ($('config-discover-min-versions')) $('config-discover-min-versions').value = String(discovery.min_versions || '1');
    if ($('config-discover-max-dirs')) $('config-discover-max-dirs').value = String(discovery.max_dirs || '5000');
    if ($('config-discover-max-candidates')) $('config-discover-max-candidates').value = String(discovery.max_candidates || '200');
    if ($('candidate-max-depth')) $('candidate-max-depth').value = String(discovery.max_depth || '4');
    if ($('candidate-min-versions')) $('candidate-min-versions').value = String(discovery.min_versions || '1');
    if ($('candidate-max-dirs')) $('candidate-max-dirs').value = String(discovery.max_dirs || '5000');
    if ($('candidate-max-candidates')) $('candidate-max-candidates').value = String(discovery.max_candidates || '200');
    $('hash-policy').value = settings.hash_policy || 'smart';
    $('parse-jobs').value = String(settings.parse_jobs || '8');
    $('parse-file-types').value = settings.parse_file_types || '';
    $('parse-exclude-file-types').value = settings.parse_exclude_file_types || '';
    setHashTypeChecks('[data-force-hash-type]', settings.force_hash_file_types || '');
    setHashTypeChecks('[data-skip-hash-type]', settings.skip_hash_file_types || '');
    $('render-detail').checked = settings.render_detail !== false;
    $('scan-if-missing').checked = false;
    $('rescan').checked = false;
    $('compare-mode').value = 'adjacent';
    showSettingsFeedback();
    updateSettingsSummary();
  });
  $('save-settings').addEventListener('click', () => saveWorkspaceSettings());
  document.querySelectorAll('[data-action]').forEach((button) => button.addEventListener('click', () => runAction(button.dataset.action)));
  $('open-version-detail-button').addEventListener('click', openVersionDetail);
  document.querySelectorAll('[data-workflow-action]').forEach((button) => button.addEventListener('click', () => runWorkflow(button.dataset.workflowAction)));
  document.querySelectorAll('[data-correction-action]').forEach((button) => button.addEventListener('click', () => runCorrection(button.dataset.correctionAction)));
  document.querySelectorAll('[data-command-action]').forEach((button) => button.addEventListener('click', () => runCommand(button.dataset.commandAction)));
  document.querySelectorAll('[data-ui-action]').forEach((button) => {
    button.addEventListener('click', () => {
      if (button.dataset.uiAction === 'open-library-add') openLibraryAddForm();
      if (button.dataset.uiAction === 'focus-version-actions') focusVersionActions();
    });
  });
  restoreRouteControls();
  activateWorkspaceTab(state.workspaceTab);
  getJson('/api/health').then(() => { $('health-badge').textContent = '服务正常'; $('health-badge').className = 'status-chip status-good'; }).catch(() => { $('health-badge').textContent = '服务异常'; $('health-badge').className = 'status-chip status-bad'; });
  Promise.all([loadWorkspace(), loadLibraries(), loadLibraryCandidates()]).catch((error) => showError(error.message));
})();
