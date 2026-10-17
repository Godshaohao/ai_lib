(() => {
  const initialRoute = new URLSearchParams(window.location.search);
  const initialTab = initialRoute.get('tab');
  const state = {
    libraries: [],
    directoryMode: initialRoute.get('directory') === 'published' ? 'published' : 'source',
    selectedPublishedStage: initialRoute.get('release_stage') || '',
    publishedLibrary: initialRoute.get('published_library') || '',
    publishedQuery: '',
    publishedFileQuery: '',
    publishedOffset: 0,
    publishedRequestId: 0,
    selectedLibrary: initialRoute.get('library') || null,
    versions: [],
    effectiveDrafts: new Map(),
    semanticOptions: null,
    semanticOptionsLibrary: '',
    semanticOptionsLoading: false,
    semanticOptionsError: '',
    semanticOptionsRequestId: 0,
    formalDirectoryMode: true,
    formalInventory: null,
    formalOffset: 0,
    selectedVersion: null,
    requestedVersionId: initialRoute.get('version') || '',
    workspace: null,
    libraryQuery: initialRoute.get('library_query') || '',
    libraryScope: initialRoute.get('library_scope') || 'all',
    libraryKind: initialRoute.get('library_kind') || 'all',
    libraryVendor: initialRoute.get('library_vendor') || 'all',
    libraryPlatform: initialRoute.get('library_platform') || 'all',
    versionQuery: initialRoute.get('version_query') || '',
    versionFilter: initialRoute.get('version_filter') || 'focus',
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
    formalReleaseLibraries: [],
    formalReleaseSnapshot: null,
    formalReleaseLoading: false,
    formalReleaseError: '',
    formalReleaseQuery: '',
    formalReleaseTarget: null,
    selectedReleaseSetLibraries: new Set(),
    releaseSetLastManifest: '',
    releaseSetResultHtml: '',
    settingsSaving: false,
    workspaceSetupSaving: false,
    workspaceSetupMessage: '',
    workspaceSetupError: false,
    updateNote: null,
    updateNoteLoading: false,
    updateNoteSaving: false,
    releasePlan: null,
    activeStage: 'version-workspace',
  };
  const $ = (id) => document.getElementById(id);
  const JOB_TIMEOUT_MS = 30 * 60 * 1000;
  const VERSION_RENDER_BATCH = 25;
  const STAGE_IDS = ['version-workspace', 'action-workspace', 'release-workspace', 'management-workspace', 'published-release-inspector'];
  const requestedStage = initialRoute.get('stage') === 'evidence-workspace' ? 'action-workspace' : initialRoute.get('stage');
  const initialStage = initialRoute.get('directory') === 'published'
    ? 'published-release-inspector'
    : STAGE_IDS.includes(requestedStage)
    ? requestedStage
    : initialTab === 'changes'
      ? 'action-workspace'
      : 'version-workspace';
  state.activeStage = initialStage;

  function primaryDomainForStage(stageId) {
    return ['release-workspace', 'published-release-inspector'].includes(stageId) ? 'release' : 'library';
  }

  function setReleaseSubview(nextView) {
    const tabs = Array.from(document.querySelectorAll('[data-release-subview]'));
    if (!tabs.some((tab) => tab.dataset.releaseSubview === nextView)) return;
    tabs.forEach((tab) => {
      const active = tab.dataset.releaseSubview === nextView;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      tab.classList.toggle('is-active', active);
    });
    document.querySelectorAll('[data-release-panel]').forEach((panel) => {
      const active = panel.dataset.releasePanel === nextView;
      panel.classList.toggle('hidden', !active);
      panel.setAttribute('aria-hidden', String(!active));
    });
  }

  function updateRouteState() {
    const params = new URLSearchParams();
    if (state.directoryMode === 'published') params.set('directory', 'published');
    if (state.selectedPublishedStage) params.set('release_stage', state.selectedPublishedStage);
    if (state.publishedLibrary) params.set('published_library', state.publishedLibrary);
    if (state.selectedLibrary) params.set('library', state.selectedLibrary);
    const versionId = state.selectedVersion?.version_id || state.requestedVersionId;
    if (versionId) params.set('version', versionId);
    if (state.activeStage !== 'version-workspace') params.set('stage', state.activeStage);
    if (state.activeStage === 'action-workspace' && state.workspaceTab !== 'tree') params.set('tab', state.workspaceTab);
    if (state.libraryQuery) params.set('library_query', state.libraryQuery);
    if (state.libraryScope !== 'all') params.set('library_scope', state.libraryScope);
    if (state.libraryKind !== 'all') params.set('library_kind', state.libraryKind);
    if (state.libraryVendor !== 'all') params.set('library_vendor', state.libraryVendor);
    if (state.libraryPlatform !== 'all') params.set('library_platform', state.libraryPlatform);
    if (state.versionQuery) params.set('version_query', state.versionQuery);
    if (state.versionFilter !== 'focus') params.set('version_filter', state.versionFilter);
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
    if (state.versionFilter === 'scan') state.versionFilter = 'new_scan';
    if (!['focus', 'all', 'new_scan', 'base_scan', 'effective_hygiene', 'compare', 'review', 'effective', 'blocked', 'error'].includes(state.versionFilter)) state.versionFilter = 'focus';
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

  function setActiveStageTab(stageId) {
    const requested = stageId === 'evidence-workspace' ? 'action-workspace' : stageId;
    const nextStage = STAGE_IDS.includes(requested) ? requested : STAGE_IDS[0];
    const domain = primaryDomainForStage(nextStage);
    state.activeStage = nextStage;
    document.querySelectorAll('[data-stage-target]').forEach((tab) => {
      const active = tab.dataset.stageTarget === nextStage;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-current', active ? 'true' : 'false');
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      tab.tabIndex = active ? 0 : -1;
    });
    STAGE_IDS.forEach((id) => {
      const panel = $(id);
      if (!panel) return;
      const active = id === nextStage;
      panel.classList.toggle('hidden', !active);
      panel.setAttribute('aria-hidden', active ? 'false' : 'true');
    });
    document.querySelectorAll('[data-primary-target]').forEach((tab) => {
      const active = tab.dataset.primaryTarget === domain;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-current', active ? 'page' : 'false');
    });
    document.querySelector('.library-view-tabs').classList.toggle('hidden', domain !== 'library');
    document.querySelector('.release-view-tabs').classList.toggle('hidden', domain !== 'release');
    $('workspace-heading').classList.toggle('hidden', domain === 'release');
    $('workspace-setup-panel').classList.toggle('hidden', domain === 'release' || !state.workspace?.setup_required);
    $('evidence-workspace').classList.toggle('hidden', nextStage !== 'action-workspace');
    $('evidence-workspace').setAttribute('aria-hidden', nextStage === 'action-workspace' ? 'false' : 'true');
    $('workspace-settings-button').setAttribute('aria-expanded', nextStage === 'management-workspace' ? 'true' : 'false');
    if (nextStage !== 'action-workspace') {
      document.querySelectorAll('[data-analysis-action]').forEach((button) => {
        button.setAttribute('aria-pressed', 'false');
        button.classList.remove('is-active');
      });
    }
    if (nextStage === 'action-workspace'
      && !Array.from(document.querySelectorAll('[data-analysis-action]')).some((button) => button.getAttribute('aria-pressed') === 'true')) {
      selectAnalysisAction('scan');
    }
    updateRouteState();
  }

  function scrollToStage(stageId) {
    setActiveStageTab(stageId);
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
    state.libDbCorrespondence = null;
    state.libDbOffset=0;
    state.fileTreeRootPath = '';
    state.fileTreeLoading = false;
    state.fileTreeError = '';
    state.fileTreeLoadedKey = '';
    state.selectedFileTreePaths = new Set();
    state.updateNote = null;
    state.updateNoteLoading = false;
    state.updateNoteSaving = false;
    state.releasePlan = null;
    renderFileChangeWorkbench();
    renderFileTree();
    renderUpdateNote();
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
    doc: '文档', md: '文档', txt: '文本', flow_config: '流程配置',
    tech_config: '技术配置', package: '封装文件',
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

  function splitNoteLines(value) {
    return String(value || '')
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function splitNoteTags(value) {
    return String(value || '')
      .split(/[,\n，；;]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function updateNoteEndpoint() {
    if (!state.selectedLibrary || !state.selectedVersion) return '';
    return `/api/libraries/${encodeURIComponent(state.selectedLibrary)}/versions/${encodeURIComponent(state.selectedVersion.version_id)}/update-note`;
  }

  function setUpdateNoteFeedback(message, kind = 'info') {
    const feedback = $('update-note-feedback');
    if (!feedback) return;
    feedback.textContent = message;
    feedback.classList.toggle('is-error', kind === 'error');
  }

  function setUpdateNoteDisabled(disabled) {
    ['load-update-note', 'save-update-note-draft', 'publish-update-note'].forEach((id) => {
      const button = $(id);
      if (button) button.disabled = disabled;
    });
  }

  function renderUpdateNote(note = null) {
    const hasVersion = Boolean(state.selectedLibrary && state.selectedVersion);
    const effectiveNote = note || state.updateNote || {};
    const status = String(effectiveNote.status || (hasVersion ? 'missing' : 'none')).toLowerCase();
    const label = { published: '已发布', draft: '草稿', missing: '暂无备注', invalid: '备注异常', none: '未选择版本' }[status] || status;
    const preview = $('version-note-preview');
    if (preview) preview.textContent = !hasVersion ? '未选择版本' : effectiveNote.summary
      ? `${label} · ${effectiveNote.use_suggestion || '待确认'}\n${effectiveNote.summary}`
      : label;
    if (preview) preview.closest('.version-note-preview').hidden = !effectiveNote.summary && status !== 'invalid';
    const chip = $('update-note-status');
    if (chip) {
      chip.textContent = label;
      chip.className = `status-chip ${status === 'published' ? 'status-good' : status === 'draft' || status === 'missing' ? 'status-warn' : status === 'invalid' ? 'status-bad' : 'status-neutral'}`;
    }
    if (!hasVersion) {
      setUpdateNoteDisabled(true);
      ['update-note-summary', 'update-note-key-changes', 'update-note-risks', 'update-note-must-check', 'update-note-impact', 'update-note-evidence', 'update-note-author'].forEach((id) => { const el = $(id); if (el) el.value = ''; });
      if ($('update-note-suggestion')) $('update-note-suggestion').value = '待确认';
      setUpdateNoteFeedback('选择版本后显示备注状态。');
      return;
    }
    setUpdateNoteDisabled(Boolean(state.activeAction || state.updateNoteSaving || state.updateNoteLoading));
    if ($('update-note-suggestion')) $('update-note-suggestion').value = ['推荐使用', '条件使用', '暂缓使用', '待确认'].includes(effectiveNote.use_suggestion) ? effectiveNote.use_suggestion : '待确认';
    if ($('update-note-summary')) $('update-note-summary').value = effectiveNote.summary || '';
    if ($('update-note-impact')) $('update-note-impact').value = (effectiveNote.impact_areas || []).join('，');
    if ($('update-note-key-changes')) $('update-note-key-changes').value = (effectiveNote.key_changes || []).join('\n');
    if ($('update-note-risks')) $('update-note-risks').value = (effectiveNote.risks || []).join('\n');
    if ($('update-note-must-check')) $('update-note-must-check').value = (effectiveNote.must_check || []).join('\n');
    if ($('update-note-evidence')) $('update-note-evidence').value = (effectiveNote.evidence_refs || []).join('，');
    if ($('update-note-author') && !$('update-note-author').value) $('update-note-author').value = effectiveNote.updated_by || '';
    const meta = effectiveNote.updated_at ? `最近更新：${effectiveNote.updated_at}` : '尚未保存人工备注。';
    setUpdateNoteFeedback(meta);
  }

  function updateNotePayload(status) {
    return {
      status,
      use_suggestion: $('update-note-suggestion')?.value || '待确认',
      summary: $('update-note-summary')?.value.trim() || '',
      impact_areas: splitNoteTags($('update-note-impact')?.value),
      key_changes: splitNoteLines($('update-note-key-changes')?.value),
      risks: splitNoteLines($('update-note-risks')?.value),
      must_check: splitNoteLines($('update-note-must-check')?.value),
      evidence_refs: splitNoteTags($('update-note-evidence')?.value),
      updated_by: $('update-note-author')?.value.trim() || 'web',
    };
  }

  function validateUpdateNotePayload(payload) {
    const textLimits = [
      ['summary', '备注摘要', 1200],
      ['updated_by', '更新人', 80],
    ];
    for (const [key, label, limit] of textLimits) {
      if (String(payload[key] || '').length > limit) {
        throw new Error(`${label}过长，最多 ${limit} 个字符`);
      }
    }
    const listLimits = [
      ['impact_areas', '影响场景', 24, 120],
      ['key_changes', '关键变化', 24, 300],
      ['risks', '风险提醒', 24, 300],
      ['must_check', '必须确认', 24, 300],
      ['evidence_refs', '证据引用', 24, 240],
    ];
    for (const [key, label, maxItems, itemLimit] of listLimits) {
      const items = Array.isArray(payload[key]) ? payload[key] : [];
      if (items.length > maxItems) throw new Error(`${label}最多 ${maxItems} 条`);
      items.forEach((item, index) => {
        if (String(item || '').length > itemLimit) throw new Error(`${label}第 ${index + 1} 条过长，最多 ${itemLimit} 个字符`);
      });
    }
  }

  async function loadUpdateNoteForSelectedVersion() {
    const endpoint = updateNoteEndpoint();
    if (!endpoint) {
      state.updateNote = null;
      renderUpdateNote();
      return;
    }
    state.updateNoteLoading = true;
    renderUpdateNote();
    try {
      const payload = await getJson(endpoint);
      if (endpoint !== updateNoteEndpoint()) return;
      state.updateNote = payload.note || {};
      state.updateNoteLoading = false;
      renderUpdateNote(state.updateNote);
    } catch (error) {
      state.updateNoteLoading = false;
      setUpdateNoteFeedback(`读取备注失败：${error.message}`, 'error');
      renderUpdateNote(state.updateNote);
    }
  }

  async function saveUpdateNote(status) {
    const endpoint = updateNoteEndpoint();
    if (!endpoint || state.updateNoteSaving) return;
    state.updateNoteSaving = true;
    renderUpdateNote(state.updateNote);
    setUpdateNoteFeedback(status === 'published' ? '正在发布备注并刷新详情页…' : '正在保存草稿…');
    try {
      const notePayload = updateNotePayload(status);
      validateUpdateNotePayload(notePayload);
      const payload = await getJson(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(notePayload),
      });
      state.updateNote = payload.note || {};
      state.updateNoteSaving = false;
      renderUpdateNote(state.updateNote);
      const renderStatus = payload.render?.status === 'PASS' ? '详情页已刷新。' : `备注已保存，详情页刷新失败：${payload.render?.error || '原因未知'}`;
      setUpdateNoteFeedback(`${status === 'published' ? '备注已发布' : '草稿已保存'}；${renderStatus}`, payload.render?.status === 'PASS' ? 'info' : 'error');
      await refreshVersionsForSelectedLibrary(state.libraryRequestId);
    } catch (error) {
      state.updateNoteSaving = false;
      renderUpdateNote(state.updateNote);
      setUpdateNoteFeedback(`保存备注失败：${error.message}`, 'error');
    }
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
      const openAttr = depth === 0 && count <= 8 ? 'open' : '';
      return `<details class="file-tree-dir" ${openAttr}><summary><span class="file-tree-folder-icon" aria-hidden="true">▸</span><strong>${escapeHtml(name)}</strong><span class="file-tree-count">${count}</span></summary><div class="file-tree-children">${renderFileTreeNode(child, depth + 1)}</div></details>`;
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
    renderLibDbCorrespondence();
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
    state.libDbCorrespondence = null;
    state.libDbOffset=0;
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
      state.libDbCorrespondence=payload.lib_db_correspondence || null;
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

  function renderLibDbCorrespondence() {
    const panel=$('lib-db-correspondence-panel');
    if (!panel) return;
    const data=state.libDbCorrespondence;
    $('lib-db-count').textContent=data ? `Liberty ${data.liberty_count} / DB ${data.db_count}` : '尚未读取扫描清单';
    $('lib-db-basis').textContent=data?.basis || '读取已有扫描清单后展示，不会重新扫描。';
    const query=$('lib-db-query').value.trim().toLowerCase(), relation=$('lib-db-relation').value;
    const rows=(data?.rows || []).filter(row=>(!relation || row.relation===relation) && (!query || [row.name,...row.liberty_files,...row.db_files].join(' ').toLowerCase().includes(query)));
    const offset=state.libDbOffset || 0;
    $('lib-db-page-count').textContent=`显示 ${Math.min(100,Math.max(0,rows.length-offset))} / ${rows.length} 组`;
    $('lib-db-prev').disabled=!offset;
    $('lib-db-next').disabled=offset+100>=rows.length;
    $('lib-db-rows').innerHTML=rows.slice(offset,offset+100).map(row=>'<tr>'+[row.name,row.relation,row.liberty_files.join('\n') || '—',row.db_files.join('\n') || '—'].map(value=>`<td>${escapeHtml(value)}</td>`).join('')+'</tr>').join('') || '<tr><td colspan="4">没有匹配文件。</td></tr>';
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

  function fileChangeOperationLabel(row) {
    if (row.deep_diff_available) return '选择核对';
    if (!row.old_path) return '缺旧文件';
    if (!row.new_path) return '缺新文件';
    return '类型不支持';
  }

  function fileEvidenceLabel(mode) {
    return ({'metadata-only': '元数据级', 'summary-only': '摘要级', 'file-level': '文件级'})[mode] || mode || '文件级';
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
            <td>${escapeHtml(fileEvidenceLabel(row.evidence_mode))}</td>
            <td><button class="button button-secondary button-small" data-file-change-index="${index}" type="button" ${deep ? '' : 'disabled'}>${escapeHtml(fileChangeOperationLabel(row))}</button></td>
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
      note.textContent = '请选择旧、新文件齐全且支持深度核对的记录；禁用原因见每行操作栏。';
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

  function updateExplicitFileDiffState() {
    const button = $('run-explicit-file-diff');
    if (!button) return;
    const oldFile = $('file-diff-old-file')?.value.trim() || '';
    const newFile = $('file-diff-new-file')?.value.trim() || '';
    const fileType = $('file-diff-explicit-type')?.value.trim() || '';
    const ready = Boolean(state.selectedLibrary && state.selectedVersion && oldFile && newFile && fileType);
    button.disabled = !ready || Boolean(state.activeAction);
    button.title = ready ? '比较指定的两份文件，并输出 HTML 结构化 diff 与 Markdown 摘要。' : '请选择一个版本，并填写旧文件、新文件和文件类型。';
  }

  async function runExplicitFileDiff() {
    const item = state.selectedVersion;
    if (!item || state.activeAction) return;
    const payload = {
      old_file: $('file-diff-old-file').value.trim(),
      new_file: $('file-diff-new-file').value.trim(),
      type: $('file-diff-explicit-type').value.trim(),
      force_large: $('file-diff-explicit-force-large').checked,
    };
    if (!payload.old_file || !payload.new_file || !payload.type) {
      showError('任意两文件对比需要填写旧文件、新文件和文件类型。', { action: true });
      updateExplicitFileDiffState();
      return;
    }
    setActionBusy('file-diff');
    updateExplicitFileDiffState();
    try {
      const result = await getJson(`/api/libraries/${encodeURIComponent(state.selectedLibrary)}/versions/${encodeURIComponent(item.version_id)}/file-diff`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      await startJob(result, '任意两文件深度对比', null, 'file-diff');
    } catch (error) {
      clearActionBusy();
      showError(`任意两文件深度对比失败：${error.message}`, { action: true });
    }
  }

  let representativeCandidate = null;
  function representativeEndpoint() {
    return state.selectedLibrary && state.selectedVersion ? `/api/libraries/${encodeURIComponent(state.selectedLibrary)}/versions/${encodeURIComponent(state.selectedVersion.version_id)}/representative-files` : '';
  }
  function updateRepresentativeButton() {
    const candidate = representativeCandidate;
    const matches = candidate && candidate.eligible && candidate.library === state.selectedLibrary && candidate.version === state.selectedVersion?.version_id;
    const button = $('save-representative-file');
    button.disabled = !matches || Boolean(state.activeAction);
    button.textContent = matches ? `保存 ${fileTypeLabel(candidate.file_type)} 到详情` : '保存到版本详情';
    button.title = matches ? '保存本次结果与备注；替换详情页中同类型的代表文件，不改变版本总体判断。' : '先完成当前版本的一组深度文件对比，再保存结果。';
  }
  async function loadRepresentativeFiles() {
    updateRepresentativeButton();
    const endpoint = representativeEndpoint();
    if (!endpoint) { $('representative-file-list').innerHTML = ''; return; }
    const result = await getJson(endpoint);
    if (endpoint !== representativeEndpoint()) return;
    const rows = result.rows || [];
    const detailLink = $('representative-detail-link');
    detailLink.classList.toggle('hidden', !rows.length || !state.selectedVersion?.version_detail_url);
    if (state.selectedVersion?.version_detail_url) detailLink.href = `${state.selectedVersion.version_detail_url.split('#')[0]}#file-checks`;
    const sourcePair = (row) => ['old', 'new'].map((side) => {
      const path = String(row[`${side}_file`] || '');
      const label = side === 'old' ? '旧' : '新';
      return `<div class="representative-source" title="${escapeHtml(path)}"><span>${label}</span><code>${escapeHtml(path.split(/[\\/]/).pop())}</code></div>`;
    }).join('') + `<details class="representative-paths"><summary>原始路径 / 复制</summary>${['old', 'new'].map((side) => `<code>${escapeHtml(row[`${side}_file`])}</code><button type="button" class="button button-secondary button-small" data-representative-copy="${escapeHtml(row[`${side}_file`])}">复制${side === 'old' ? '旧' : '新'}文件路径</button>`).join('')}</details>`;
    $('representative-file-list').innerHTML = rows.length ? `<div class="release-link-scroll"><table><colgroup><col style="width:12%"><col style="width:38%"><col style="width:20%"><col style="width:30%"></colgroup><thead><tr><th>已保存类型</th><th>所选文件</th><th>文件状态</th><th>核查备注</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${escapeHtml(fileTypeLabel(row.file_type))}</td><td>${sourcePair(row)}</td><td>${escapeHtml(row.freshness)}</td><td>${escapeHtml(row.note || '未填写')}</td></tr>`).join('')}</tbody></table></div>` : '<p class="muted">尚未保存核查结果。</p>';
    $('representative-file-list').querySelectorAll('[data-representative-copy]').forEach((button) => button.addEventListener('click', async () => {
      const ok = await copyText(button.dataset.representativeCopy);
      button.textContent = ok ? '已复制路径' : '复制失败';
    }));
  }
  async function saveRepresentativeFile() {
    const endpoint = representativeEndpoint();
    const candidate = representativeCandidate;
    if (!endpoint || !candidate || $('save-representative-file').disabled) return;
    $('save-representative-file').disabled = true;
    $('representative-feedback').textContent = '正在保存并刷新当前版本详情…';
    try {
      const result = await getJson(endpoint, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({job_id:candidate.job_id, note:$('representative-note').value, updated_by:$('representative-author').value || 'web'})});
      if (endpoint !== representativeEndpoint()) return;
      $('representative-feedback').textContent = result.render?.status === 'PASS' ? '已加入详情页；仅代表所选文件，不代表整个视图通过。' : `结果已保存，但详情刷新失败：${result.render?.error || '原因未知'}`;
      await loadRepresentativeFiles();
    } catch (error) {
      $('representative-feedback').textContent = `保存失败：${error.message}`;
    } finally { updateRepresentativeButton(); }
  }

  function renderLibraries() {
    if (state.directoryMode === 'published') { renderPublishedDirectory(); return; }
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
      $('library-list').innerHTML = state.libraries.length ? '<p class="empty-note">没有匹配的已登记库。</p>' : '<p class="empty-note">目录中没有已登记库。</p>';
    }
    renderRegisteredLibraries();
    renderReleaseSetWorkbench();
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
      const newPending = Number(item.new_candidate_pending_count ?? item.workflow_pending_count ?? 0);
      const basePending = Number(item.base_scan_pending_count || 0);
      if (newPending > 0 || basePending > 0) counts.pending += 1;
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
    if (state.libraryScope === 'pending') return Number(item.new_candidate_pending_count ?? item.workflow_pending_count ?? 0) > 0;
    if (state.libraryScope === 'blocked') return Number(item.release_blocked_count || 0) > 0;
    if (state.libraryScope === 'no_effective') return !(item.current_effective || item.current_effective_id);
    if (state.libraryScope === 'candidate') return Boolean(item.pending_window?.candidate_effective_id || ['PRESENT', 'READY', 'PENDING'].includes(String(item.pending_window?.state || '').toUpperCase()));
    return true;
  }

  function renderLibraryFacetSummary(visibleRows, allRows) {
    const counts = libraryScopeCounts(allRows);
    const newPendingLibraries = allRows.filter((item) => Number(item.new_candidate_pending_count ?? item.workflow_pending_count ?? 0) > 0).length;
    const basePendingLibraries = allRows.filter((item) => Number(item.base_scan_pending_count || 0) > 0).length;
    const scopeName = {
      all: '全部库',
      pending: '需处理库',
      blocked: '发布待确认',
      no_effective: '无当前有效',
      candidate: '候选待登记',
    }[state.libraryScope] || '全部库';
    $('library-facet-summary').textContent = `${scopeName} ${visibleRows.length} / ${counts.all} · 有新版本 ${newPendingLibraries} 库 · 基准待扫 ${basePendingLibraries} 库 · 发布待确认 ${counts.blocked} 库`;
  }

  function libraryItemSignals(item) {
    const pending = Number(item.new_candidate_pending_count ?? item.workflow_pending_count ?? 0);
    const basePending = Number(item.base_scan_pending_count || 0);
    const hygiene = Number(item.effective_hygiene_count || 0);
    const latest = item.latest_version ? `最新 ${item.latest_version}` : '无版本';
    const current = item.current_effective || item.current_effective_id ? `当前 ${item.current_effective || item.current_effective_id}` : '未设当前';
    const pendingChip = pending
      ? `<span class="library-signal is-attention">新版本待办 ${pending}</span>`
      : item.current_effective_stack?.available
        ? '<span class="library-signal is-ready">新版本无待办</span>'
        : '<span class="library-signal is-neutral">当前组合待确认</span>';
    const baseChip = basePending
      ? `<span class="library-signal is-neutral">基准待扫 ${basePending}</span>`
      : '';
    const hygieneChip = hygiene
      ? `<span class="library-signal is-neutral">当前版补证据 ${hygiene}</span>`
      : '';
    return `${pendingChip}${baseChip}${hygieneChip}<span class="library-signal">${escapeHtml(latest)}</span><span class="library-signal">${escapeHtml(current)}</span>`;
  }

  function renderRegisteredLibraries() {
    const body = $('registered-library-table-body');
    const status = $('registered-library-status');
    if (!body || !status) return;
    if (state.librariesLoading) {
      status.textContent = '读取中';
      status.className = 'status-chip status-neutral';
      body.innerHTML = '<tr><td colspan="7" class="muted">正在读取原始库。</td></tr>';
      return;
    }
    if (state.libraryLoadError) {
      status.textContent = '读取失败';
      status.className = 'status-chip status-bad';
      body.innerHTML = `<tr><td colspan="7" class="muted">${escapeHtml(state.libraryLoadError)}</td></tr>`;
      return;
    }
    status.textContent = `原始库 ${state.libraries.length}`;
    status.className = 'status-chip status-good';
    const query = $('registered-library-filter').value.trim().toLowerCase();
    const rows = state.libraries.filter((item) => [item.library_name, item.display_name, item.root_display, item.root_abs, item.latest_version].some((value) => String(value || '').toLowerCase().includes(query)));
    $('registered-library-count').textContent = `${rows.length} / ${state.libraries.length} 个库`;
    body.innerHTML = rows.length ? rows.map((item) => {
      const current = item.library_name === state.selectedLibrary;
      const root = item.root_display || item.root_abs || '';
      const rootSource = item.root_source === 'version_raw_path'
        ? '由版本路径推导'
        : item.root_source === 'catalog_root'
          ? '库级登记'
          : '未记录';
      return `<tr class="${current ? 'is-selected' : ''}">
        <td><code title="${escapeHtml(item.library_name)}">${escapeHtml(item.library_name)}</code><small>${escapeHtml(item.display_name || '未设置显示名称')}</small></td>
        <td><code title="${escapeHtml(root)}">${escapeHtml(root || '未记录')}</code><small>${escapeHtml(rootSource)}</small></td>
        <td>${Number(item.version_count || 0)}</td>
        <td><code title="${escapeHtml(item.latest_version || '')}">${escapeHtml(item.latest_version || '未记录')}</code></td>
        <td>${escapeHtml(item.raw_updated_at ? new Date(item.raw_updated_at).toLocaleString('zh-CN', {hour12:false}) : '未记录')}<small>目录快照记录</small></td>
        <td>${escapeHtml(item.current_effective || '未设置')}</td>
        <td><button class="button button-secondary button-small" data-registered-library="${escapeHtml(item.library_name)}" type="button">${current ? '当前库' : '查看版本'}</button></td>
      </tr>`;
    }).join('') : '<tr><td colspan="7" class="muted">没有匹配的原始库；可清除筛选重新查看。</td></tr>';
    body.querySelectorAll('[data-registered-library]').forEach((button) => button.addEventListener('click', () => selectLibrary(button.dataset.registeredLibrary)));
  }

  function effectiveSelectionKey(selection) {
    return JSON.stringify([selection.base_full, selection.includes]);
  }

  function eligibleEffectiveOverlays(versions, base, manual = false) {
    const index = versions.findIndex((row) => row.version_id === base);
    return (manual ? versions : index < 0 ? [] : versions.slice(0, index)).filter((row) =>
      ['PARTIAL_UPDATE', 'HOTFIX', 'DOC_UPDATE'].includes(row.package_type));
  }

  function effectiveSelectionDraft() {
    if (!state.selectedLibrary) return null;
    if (!state.effectiveDrafts.has(state.selectedLibrary)) {
      const library = selectedLibraryRow();
      const candidate = library?.pending_window?.candidate_effective_stack;
      const current = library?.current_effective_stack;
      const saved = candidate?.base_full_version ? candidate : current?.base_full_version ? current : null;
      const base = saved?.base_full_version || state.versions.find((row) => row.package_type === 'FULL_PACKAGE')?.version_id;
      // Wait for version metadata before choosing an automatic default.
      if (!base) return null;
      state.effectiveDrafts.set(state.selectedLibrary, {
        base_full: base,
        includes: saved ? [...(saved.accepted_updates || [])] : eligibleEffectiveOverlays(state.versions, base).map((row) => row.version_id).reverse(),
        source: saved && saved === candidate ? '已保存候选' : saved ? '当前有效组合' : '最新完整包预填',
        dirty: false, preview: null,
      });
    }
    return state.effectiveDrafts.get(state.selectedLibrary);
  }

  function changeEffectiveSelection(selection) {
    const draft = effectiveSelectionDraft();
    if (!draft || effectiveSelectionKey(draft) === effectiveSelectionKey(selection)) return;
    draft.base_full = selection.base_full;
    draft.includes = [...selection.includes];
    draft.dirty = true;
    draft.preview = null;
  }

  function effectiveSelectionPreviewReady(draft, endpoint) {
    return Boolean(draft?.preview && draft.preview.endpoint === endpoint
      && draft.preview.key === effectiveSelectionKey(draft));
  }

  function effectiveSelectionMatchesCandidate(draft, candidate) {
    return Boolean(!effectiveVersionEdits().size && draft && candidate?.base_full_version && effectiveSelectionKey(draft)
      === effectiveSelectionKey({base_full: candidate.base_full_version, includes: candidate.accepted_updates || []}));
  }

  function effectiveVersionEdits() {
    state.effectiveEdits ||= new Map();
    if (!state.effectiveEdits.has(state.selectedLibrary)) state.effectiveEdits.set(state.selectedLibrary, new Map());
    return state.effectiveEdits.get(state.selectedLibrary);
  }

  function effectiveVersionRows() {
    const edits = effectiveVersionEdits();
    return state.versions.map(row => ({...row, ...(edits.get(row.version_id) || {})}));
  }

  function editEffectiveVersion(version, patch) {
    const edits = effectiveVersionEdits();
    const original = state.versions.find(row => row.version_id === version);
    const values = {...(edits.get(version) || {}), ...patch};
    Object.keys(values).forEach(key => { if (values[key] === original?.[key]) delete values[key]; });
    if (Object.keys(values).length) edits.set(version, values); else edits.delete(version);
    let draft = effectiveSelectionDraft();
    if (!draft) {
      const base = effectiveVersionRows().find(row => row.package_type === 'FULL_PACKAGE')?.version_id;
      if (base) { state.effectiveDrafts.set(state.selectedLibrary, {base_full:base, includes:[], source:'人工修改', dirty:true, preview:null}); draft = effectiveSelectionDraft(); }
    }
    if (draft) { draft.preview = null; draft.dirty = true; }
  }

  async function saveEffectiveVersionEdits(library) {
    const edits = effectiveVersionEdits();
    for (const [version, values] of [...edits]) {
      if (state.selectedLibrary !== library) throw new Error('库已切换，停止保存。');
      setActionBusy('next-preview');
      const payload = {...values, note:'版本配置表人工修正'};
      if (values.previous_effective) payload.compare_default = 'previous_effective';
      const result = await getJson(`/api/libraries/${encodeURIComponent(library)}/versions/${encodeURIComponent(version)}/override`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
      const completed = await startJob(result, `保存版本属性：${version}`);
      if (completed?.return_code !== 0) throw new Error(`${version} 保存失败，未保存内容已保留；请查看运行日志。`);
      edits.delete(version);
      if (state.selectedLibrary !== library) throw new Error(`${version} 已保存，但库已切换；请重新选择原库后预览。`);
    }
  }

  function renderEffectiveSelection() {
    const body = $('effective-selection-body');
    if (!body) return;
    const draft = effectiveSelectionDraft();
    const busy = Boolean(state.activeAction || state.versionsLoading || state.versionsLoadingMore);
    const rows = effectiveVersionRows();
    const current = selectedLibraryRow()?.current_effective_stack;
    const currentMembers = new Set([current?.base_full_version, ...(current?.accepted_updates || [])]);
    const eligible = new Set(eligibleEffectiveOverlays(rows, draft?.base_full, true).map((row) => row.version_id));
    body.innerHTML = rows.map((row) => {
      const full = row.package_type === 'FULL_PACKAGE';
      const enabled = full || eligible.has(row.version_id);
      const checked = full ? draft?.base_full === row.version_id : draft?.includes.includes(row.version_id);
      const types = ['FULL_PACKAGE','PARTIAL_UPDATE','HOTFIX','DOC_UPDATE','UNKNOWN_PACKAGE'];
      const base = row.previous_effective || row.base_version || '';
      const options = rows.filter(other => other.version_id !== row.version_id).map(other => `<option value="${escapeHtml(other.version_id)}" ${base === other.version_id ? 'selected' : ''}>${escapeHtml(other.version_id)}</option>`).join('');
      return `<tr class="${effectiveVersionEdits().has(row.version_id) ? 'effective-row-dirty' : ''}"><td><input type="${full ? 'radio' : 'checkbox'}" ${full ? 'name="effective-base" data-effective-base' : 'data-effective-overlay'} value="${escapeHtml(row.version_id)}" aria-label="${full ? '完整包基线' : '叠加更新'} ${escapeHtml(row.version_id)}" ${checked ? 'checked' : ''} ${busy || !enabled ? 'disabled' : ''}></td><td><code>${escapeHtml(row.version_id)}</code>${row.current_effective || currentMembers.has(row.version_id) ? '<small>当前有效组成</small>' : ''}</td><td><select data-effective-type="${escapeHtml(row.version_id)}" aria-label="包类型 ${escapeHtml(row.version_id)}" ${busy ? 'disabled' : ''}>${types.map(type => `<option value="${type}" ${row.package_type === type ? 'selected' : ''}>${escapeHtml(packageLabel(type))}</option>`).join('')}</select></td><td><select data-effective-compare="${escapeHtml(row.version_id)}" aria-label="对比基准 ${escapeHtml(row.version_id)}" ${busy ? 'disabled' : ''}><option value="" disabled ${!base ? 'selected' : ''}>沿用现有规则</option>${base && !rows.some(other => other.version_id === base) ? `<option value="${escapeHtml(base)}" selected>${escapeHtml(base)}（未读取）</option>` : ''}${options}</select></td><td>${row.scan_evidence_ready ? '已就绪' : '待补齐'}</td><td>${effectiveVersionEdits().has(row.version_id) ? '待保存' : '已保存'}</td></tr>`;
    }).join('') || '<tr><td colspan="6">尚未读取版本。</td></tr>';
    body.querySelectorAll('[data-effective-type], [data-effective-compare]').forEach(input => input.addEventListener('change', () => {
      const version = input.dataset.effectiveType || input.dataset.effectiveCompare;
      editEffectiveVersion(version, input.dataset.effectiveType ? {package_type:input.value} : {previous_effective:input.value});
      if (input.dataset.effectiveType && draft) {
        const rows = effectiveVersionRows();
        if (draft.base_full === version && input.value !== 'FULL_PACKAGE') draft.base_full = '';
        draft.includes = draft.includes.filter(id => eligibleEffectiveOverlays(rows, draft.base_full, true).some(row => row.version_id === id));
      }
      renderVersionFacts();
    }));
    $('next-preview-button').textContent = effectiveVersionEdits().size ? `保存并预览（${effectiveVersionEdits().size} 行）` : '预览组合';
    body.querySelectorAll('[data-effective-base], [data-effective-overlay]').forEach((input) => input.addEventListener('change', () => {
      if (input.hasAttribute('data-effective-base')) {
        changeEffectiveSelection({base_full: input.value, includes: draft?.includes || []});
      } else {
        changeEffectiveSelection({base_full: draft.base_full, includes: input.checked ? [...draft.includes, input.value] : draft.includes.filter((id) => id !== input.value)});
      }
      $('workflow-summary').textContent = '组成选择已更改，原预览已失效。';
      renderVersionFacts();
    }));
    $('effective-selection-order').innerHTML = (draft?.includes || []).map((id, index, all) => `<li><span>${index + 1}. <code>${escapeHtml(id)}</code></span><div><button class="button button-secondary button-small" type="button" data-effective-move="${index}" data-direction="-1" title="上移 ${escapeHtml(id)}" aria-label="上移 ${escapeHtml(id)}" ${busy || !index ? 'disabled' : ''}>&uarr;</button><button class="button button-secondary button-small" type="button" data-effective-move="${index}" data-direction="1" title="下移 ${escapeHtml(id)}" aria-label="下移 ${escapeHtml(id)}" ${busy || index === all.length - 1 ? 'disabled' : ''}>&darr;</button></div></li>`).join('') || '<li>无叠加更新</li>';
    $('effective-selection-order').querySelectorAll('[data-effective-move]').forEach((button) => button.addEventListener('click', () => {
      const includes = [...draft.includes];
      const index = Number(button.dataset.effectiveMove), target = index + Number(button.dataset.direction);
      [includes[index], includes[target]] = [includes[target], includes[index]];
      changeEffectiveSelection({base_full: draft.base_full, includes});
      $('workflow-summary').textContent = '叠加顺序已更改，原预览已失效。';
      renderVersionFacts();
    }));
    const missing = draft ? [draft.base_full, ...draft.includes].filter((id) => !state.versions.some((row) => row.version_id === id)) : [];
    $('effective-selection-status').textContent = draft
      ? `${draft.dirty ? '人工修改' : draft.source} · ${draft.base_full} · ${draft.includes.length} 个叠加更新${missing.length ? ' · 部分组成版本未读取' : ''}${draft.preview ? ' · 已预览' : ' · 待预览'}`
      : '未找到完整包基线';
    $('effective-selection-load-all').disabled = busy || !state.versionHasMore;
    $('effective-selection-count').textContent = `${state.versions.length} / ${state.versionTotal} 个版本`;
  }

  async function loadAllEffectiveVersions() {
    const library = state.selectedLibrary, requestId = state.libraryRequestId;
    if (!library || state.versionsLoading || state.versionsLoadingMore) return;
    try {
      while (state.versionHasMore && library === state.selectedLibrary && requestId === state.libraryRequestId) {
        const count = state.versions.length;
        await refreshVersionsForSelectedLibrary(requestId, true);
        if (state.versions.length <= count) break;
      }
    } catch (error) {
      state.versionsLoadingMore = false;
      $('effective-selection-status').textContent = `读取版本失败：${error.message}`;
    }
  }

  function shortDigest(value) {
    const text = String(value || '').replace(/^sha256:/, '');
    return text ? text.slice(0, 12) : '';
  }

  function currentEffectiveStack(library = null) {
    return (library || state.libraries.find((row) => row.library_name === state.selectedLibrary))?.current_effective_stack || {};
  }

  function effectiveCompositionRows(current, candidate, versions) {
    const byVersion = new Map(versions.map((row) => [row.version_id, row]));
    const rows = [];
    for (const [side, stack] of [['current', current], ['candidate', candidate]]) {
      if (!stack.base_full_version) continue;
      [stack.base_full_version, ...(stack.accepted_updates || [])].forEach((version, index) => {
        const evidence = byVersion.get(version);
        rows.push({side, version, order: index + 1, role: index ? '叠加更新' : '完整包基线',
          evidence: !evidence ? '未读取' : evidence.scan_evidence_ready ? '已就绪' : '待补齐',
          selectable: Boolean(evidence)});
      });
    }
    return rows;
  }

  function filterEffectiveCompositionRows(rows, scope, query) {
    const search = query.trim().toLowerCase();
    return rows.filter((row) => (scope === 'all' || scope === row.side)
      && `${row.version} ${row.role}`.toLowerCase().includes(search));
  }

  function renderEffectiveCompositionTable() {
    const body = $('effective-composition-body');
    if (!body) return;
    const library = state.libraries.find((row) => row.library_name === state.selectedLibrary);
    const pendingWindow = library?.pending_window || {};
    const rows = effectiveCompositionRows(library?.current_effective_stack || {}, pendingWindow.state === 'ACCEPTED' ? {} : pendingWindow.candidate_effective_stack || {}, state.versions);
    const visible = filterEffectiveCompositionRows(rows, $('effective-composition-scope').value, $('effective-composition-query').value);
    body.innerHTML = visible.length ? visible.map((row) => `<tr>
      <td><span class="effective-side-label ${row.side === 'current' ? 'is-current' : 'is-candidate'}">${row.side === 'current' ? '当前有效' : '待确认候选'}</span></td>
      <td class="effective-order">${row.order}</td><td>${row.role}</td>
      <td class="effective-version-name"><code>${escapeHtml(row.version)}</code></td>
      <td>${row.evidence}</td><td>${row.selectable ? `<button class="button button-secondary button-small" type="button" data-effective-version="${escapeHtml(row.version)}">查看版本</button>` : '版本状态未读取'}</td></tr>`).join('')
      : `<tr><td colspan="6">${rows.length ? '没有匹配的组成版本，请清除筛选。' : '尚无组合，先预览处理计划，再生成候选。'}</td></tr>`;
    $('effective-composition-count').textContent = `${visible.length} / ${rows.length} 个组成版本`;
    body.querySelectorAll('[data-effective-version]').forEach((button) => button.addEventListener('click', () => {
      selectVersion(button.dataset.effectiveVersion);
      scrollToStage('action-workspace');
    }));
  }

  function renderEffectiveStack() {
    const library = state.libraries.find((row) => row.library_name === state.selectedLibrary);
    const stack = currentEffectiveStack(library);
    const pendingWindow = library?.pending_window || {};
    const candidate = pendingWindow.candidate_effective_stack || {};
    const acceptedCandidate = pendingWindow.state === 'ACCEPTED';
    const source = $('current-effective-source');
    if (!source) return;
    const available = Boolean(stack.available);
    source.textContent = `来源：${stack.source_label || '未读取'}`;
    source.className = `status-chip ${available ? 'status-good' : 'status-neutral'}`;
    $('current-effective-base').textContent = stack.base_full_version || '未设置';
    $('current-effective-base').title = stack.base_full_version || '';
    const overlays = Array.isArray(stack.accepted_updates) ? stack.accepted_updates : [];
    $('current-effective-overlays').textContent = overlays.length ? overlays.join(' + ') : '无叠加更新';
    $('current-effective-overlays').title = overlays.join('\n');
    $('current-effective-id').textContent = stack.current_effective_id || '未设置';
    $('current-effective-id').title = stack.current_effective_id || '';
    $('current-effective-digest').textContent = shortDigest(stack.effective_digest || stack.manifest_sha256) || '未设置';
    $('current-effective-digest').title = stack.effective_digest || stack.manifest_sha256 || '';
    const candidateAvailable = Boolean(candidate.available || candidate.candidate_effective_id);
    $('candidate-effective-heading').textContent = acceptedCandidate ? '最近确认组合' : '待确认候选';
    $('candidate-effective-status').textContent = acceptedCandidate ? '已确认' : candidateAvailable ? '尚未生效' : '未生成';
    $('candidate-effective-id').textContent = candidate.candidate_effective_id || '未生成';
    $('candidate-effective-id').title = candidate.candidate_effective_id || '';
    $('candidate-effective-source').textContent = candidateAvailable
      ? `来源：${candidate.source_label || pendingWindow.base_source_label || '处理计划'}；完整包基线：${candidate.base_full_version || '未设置'}；叠加更新：${(candidate.accepted_updates || []).join(' + ') || '无'}`
      : '来源：未生成处理计划';
    const link = $('compare-current-candidate');
    if (link) {
      link.textContent = acceptedCandidate ? '查看已确认组合的核对记录' : available ? '比较当前与候选' : '核对初始候选';
      link.hidden = !pendingWindow.compare_url;
      if (pendingWindow.compare_url) link.href = pendingWindow.compare_url;
      else link.removeAttribute('href');
    }
    $('workflow-compare-placeholder').hidden = Boolean(pendingWindow.compare_url);
    const compositionReport = $('candidate-composition-report');
    compositionReport.hidden = !pendingWindow.candidate_html_url;
    if (pendingWindow.candidate_html_url) compositionReport.href = pendingWindow.candidate_html_url;
    else compositionReport.removeAttribute('href');
    $('workflow-compare-hint').textContent = acceptedCandidate ? '保留确认时的比较记录' : pendingWindow.compare_url ? '核对候选差异与同名文件覆盖' : '执行后生成核对结果';
    const rollback = $('rollback-to');
    const previous = rollback.value;
    const saved = (pendingWindow.saved_combinations || []).filter((row) => row.effective_id !== stack.current_effective_id && row.effective_id !== candidate.candidate_effective_id);
    rollback.innerHTML = '<option value="">选择回退目标</option>' + saved.map((row) => `<option value="${escapeHtml(row.effective_id)}">${escapeHtml(row.effective_id)}</option>`).join('');
    if (saved.some((row) => row.effective_id === previous)) rollback.value = previous;
    rollback.disabled = !saved.length || Boolean(state.activeAction);
    renderEffectiveCompositionTable();
  }

  function renderSemanticReviewReadiness() {
    const ready = state.semanticOptionsLibrary === state.selectedLibrary && state.semanticOptions;
    const busy = Boolean(state.activeAction) || Boolean(state.semanticOptionsLoading);
    for (const id of ['semantic-review-target', 'semantic-review-base', 'semantic-review-profile']) $(id).disabled = busy || !ready;
    $('semantic-review-refresh').disabled = busy || !state.selectedLibrary;
    const target = $('semantic-review-target').value;
    const base = $('semantic-review-base').value;
    const inputs = Array.from($('semantic-review-checks').querySelectorAll('input'));
    inputs.forEach((input) => { input.disabled = busy || !ready || (input.dataset.requiresBase === 'true' && !base); });
    const selected = inputs.filter(input => input.checked && (base || input.dataset.requiresBase !== 'true')).length;
    const omitted = !base && inputs.some(input => input.dataset.requiresBase === 'true');
    const selectedTarget = ready && state.semanticOptions.targets.find(row => row.id === target);
    const selectedBase = ready && state.semanticOptions.targets.find(row => row.id === base);
    $('semantic-review-scope').textContent = selectedTarget
      ? `实际检查：${selectedTarget.label}（编号 ${target}）${selectedBase ? `；对比：${selectedBase.label}（编号 ${base}）` : '；不做版本对比'}`
      : '尚未选择检查组合。';
    $('semantic-review-run').disabled = busy || !ready || !target || target === base || !selected;
    $('semantic-review-feedback').textContent = state.semanticOptionsLoading ? '正在读取已保存的组合与检查方案…'
      : state.semanticOptionsError ? state.semanticOptionsError
      : !state.selectedLibrary ? '请先选择库。'
      : !ready || !state.semanticOptions.targets.length ? '尚无已生成的有效组合；请先生成候选组合，不需要先设为当前有效。'
      : !target ? '请选择要检查的已保存组合。'
      : target === base ? '检查目标与对比基准不能相同。'
      : !selected ? (omitted ? '请先选择对比基准，或改用包含单组合检查的方案。' : '请至少勾选一项检查。')
      : state.activeAction === 'semantic-review' ? '正在生成报告；进度和文件入口见顶部运行状态。'
      : base ? '检查目标及其相对基准的变化。' : (omitted ? '本次仅执行单组合检查；标有“需要基准”的项目不执行。' : '本次仅检查所选组合。');
    if (ready && state.semanticOptions.notice) $('semantic-review-feedback').textContent = `${state.semanticOptions.notice} ${$('semantic-review-feedback').textContent}`;
  }

  function renderSemanticReviewChecks(selected = null) {
    const profile = state.semanticOptions?.profiles.find((item) => item.name === $('semantic-review-profile').value);
    $('semantic-review-checks').innerHTML = (profile?.checks || []).map((check) =>
      `<label class="toggle-field"><input type="checkbox" value="${escapeHtml(check.id)}" data-requires-base="${Boolean(check.requires_base)}" ${selected === null || selected.has(check.id) ? 'checked' : ''}>${escapeHtml(check.label)}${check.requires_base ? '（需要基准）' : ''}</label>`).join('');
    $('semantic-review-checks').querySelectorAll('input').forEach((input) => input.addEventListener('change', renderSemanticReviewReadiness));
    renderSemanticReviewReadiness();
  }

  async function loadSemanticReviewOptions() {
    const library = state.selectedLibrary;
    const requestId = ++state.semanticOptionsRequestId;
    const preserve = state.semanticOptionsLibrary === library;
    const oldProfile = $('semantic-review-profile').value;
    const selectedChecks = new Set(Array.from($('semantic-review-checks').querySelectorAll('input:checked')).map((input) => input.value));
    state.semanticOptionsLoading = Boolean(library);
    state.semanticOptionsError = '';
    renderSemanticReviewReadiness();
    if (!library) return;
    try {
      const options = await getJson(`/api/libraries/${encodeURIComponent(library)}/semantic-review`);
      if (requestId !== state.semanticOptionsRequestId || library !== state.selectedLibrary) return;
      const oldTarget = preserve ? $('semantic-review-target').value : options.default_target;
      const oldBase = preserve ? $('semantic-review-base').value : options.default_base;
      state.semanticOptions = options;
      state.semanticOptionsLibrary = library;
      const choices = options.targets.map((row) => `<option value="${escapeHtml(row.id)}" ${row.available === false ? 'disabled' : ''}>${escapeHtml(row.label)}</option>`).join('');
      $('semantic-review-target').innerHTML = '<option value="">选择已生成的组合</option>' + choices;
      $('semantic-review-base').innerHTML = '<option value="">不对比，仅核查目标</option>' + choices;
      $('semantic-review-target').value = options.targets.some((row) => row.id === oldTarget && row.available !== false) ? oldTarget : '';
      $('semantic-review-base').value = options.targets.some((row) => row.id === oldBase && row.available !== false) ? oldBase : '';
      $('semantic-review-profile').innerHTML = options.profiles.map((profile) => `<option value="${escapeHtml(profile.name)}">${escapeHtml(profile.label)}</option>`).join('');
      $('semantic-review-profile').value = preserve && options.profiles.some((profile) => profile.name === oldProfile) ? oldProfile : options.default_profile;
      if (!$('semantic-review-profile').value) $('semantic-review-profile').selectedIndex = 0;
      renderSemanticReviewChecks(preserve && oldProfile === $('semantic-review-profile').value ? selectedChecks : null);
    } catch (error) {
      if (requestId !== state.semanticOptionsRequestId || library !== state.selectedLibrary) return;
      state.semanticOptions = null;
      state.semanticOptionsError = `读取技术检查选项失败：${error.message}；可点击刷新组合选项重试。`;
    } finally {
      if (requestId === state.semanticOptionsRequestId) {
        state.semanticOptionsLoading = false;
        renderSemanticReviewReadiness();
      }
    }
  }

  async function runSemanticReview() {
    if ($('semantic-review-run').disabled || !state.selectedLibrary || state.activeAction) return;
    const payload = {target: $('semantic-review-target').value, base: $('semantic-review-base').value,
      profile: $('semantic-review-profile').value,
      checks: Array.from($('semantic-review-checks').querySelectorAll('input:checked:not(:disabled)')).map((input) => input.value)};
    const library = state.selectedLibrary;
    setActionBusy('semantic-review');
    try {
      const task = await getJson(`/api/libraries/${encodeURIComponent(library)}/semantic-review`,
        {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      return await startJob(task, `技术检查 ${payload.target}${payload.base ? ` vs ${payload.base}` : ''}`, null, 'semantic-review');
    } catch (error) {
      clearActionBusy();
      state.semanticOptionsError = `提交技术检查失败：${error.message}`;
      renderSemanticReviewReadiness();
      showError(state.semanticOptionsError, {action: true});
      return null;
    }
  }

  function releaseSetLibraryAvailable(item) {
    const available = item.current_effective_stack?.available;
    return typeof available === 'boolean' ? available : Boolean(item.current_effective || item.current_effective_id);
  }

  function visibleReleaseSetLibraries() {
    const query = $('release-set-filter').value.trim().toLowerCase();
    const scope = $('release-set-availability').value;
    return state.libraries.filter((item) => {
      const available = releaseSetLibraryAvailable(item);
      return (scope === 'all' || (scope === 'available' ? available : !available))
        && [item.library_name, item.vendor, item.current_effective, item.current_effective_id, item.current_effective_stack?.current_effective_id].some((value) => String(value || '').toLowerCase().includes(query));
    });
  }

  function renderReleaseSetWorkbench() {
    const body = $('release-set-library-body');
    const result = $('release-set-result');
    if (!body || !result) return;
    const visible = visibleReleaseSetLibraries();
    if (!state.librariesLoading) {
      const available = new Set(state.libraries.filter(releaseSetLibraryAvailable).map((item) => item.library_name));
      state.selectedReleaseSetLibraries.forEach((name) => { if (!available.has(name)) state.selectedReleaseSetLibraries.delete(name); });
    }
    if (state.librariesLoading) {
      body.innerHTML = '<tr><td colspan="4" class="muted">正在读取已登记库。</td></tr>';
    } else if (!state.libraries.length) {
      body.innerHTML = '<tr><td colspan="4" class="muted">目录中还没有已登记库。</td></tr>';
    } else {
      body.innerHTML = visible.map((item) => {
        const stack = currentEffectiveStack(item);
        const enabled = releaseSetLibraryAvailable(item);
        const checked = state.selectedReleaseSetLibraries.has(item.library_name) && enabled;
        const effective = stack.current_effective_id || item.current_effective || item.current_effective_id || '未设置';
        return `<tr class="${item.library_name === state.selectedLibrary ? 'is-selected' : ''}">
          <td><input data-release-set-library="${escapeHtml(item.library_name)}" type="checkbox" ${checked ? 'checked' : ''} ${enabled && !state.activeAction ? '' : 'disabled'} aria-label="选择 ${escapeHtml(item.library_name)}"></td>
          <td><code title="${escapeHtml(item.library_name)}">${escapeHtml(item.library_name)}</code><small>${escapeHtml(libraryMetaLine(item))}</small></td>
          <td><code title="${escapeHtml(effective)}">${escapeHtml(effective)}</code><small>Base FULL：${escapeHtml(stack.base_full_version || '未设置')}；叠加：${escapeHtml((stack.accepted_updates || []).join(' + ') || '无')}</small></td>
          <td><span class="mini-chip ${enabled ? 'is-ready' : 'is-neutral'}">${escapeHtml(stack.source_label || '未找到当前有效指针')}</span>${!enabled ? `<button class="button button-quiet button-small" data-release-set-setup="${escapeHtml(item.library_name)}" type="button" ${state.activeAction ? 'disabled' : ''}>查看库版本</button>` : ''}</td>
        </tr>`;
      }).join('') || '<tr><td colspan="4" class="muted">没有符合筛选条件的库。</td></tr>';
    }
    body.querySelectorAll('[data-release-set-library]').forEach((input) => input.addEventListener('change', () => {
      const name = input.dataset.releaseSetLibrary;
      if (!name) return;
      if (input.checked) state.selectedReleaseSetLibraries.add(name);
      else state.selectedReleaseSetLibraries.delete(name);
      if ($('release-set-acknowledged')) $('release-set-acknowledged').checked = false;
      renderReleaseSetWorkbench();
    }));
    body.querySelectorAll('[data-release-set-setup]').forEach((button) => button.addEventListener('click', async () => {
      await selectLibrary(button.dataset.releaseSetSetup);
      setActiveStageTab('version-workspace');
    }));
    const selectedCount = state.libraries.filter((item) => state.selectedReleaseSetLibraries.has(item.library_name)
      && releaseSetLibraryAvailable(item)).length;
    const visibleSelected = visible.filter((item) => releaseSetLibraryAvailable(item) && state.selectedReleaseSetLibraries.has(item.library_name)).length;
    $('release-set-selection-summary').textContent = `显示 ${visible.length} / ${state.libraries.length} 库；已选 ${selectedCount}（筛选外 ${selectedCount - visibleSelected}）`;
    $('select-visible-release-set').disabled = Boolean(state.activeAction) || !visible.some(releaseSetLibraryAvailable);
    $('clear-release-set').disabled = Boolean(state.activeAction) || selectedCount === 0;
    const buildButton = $('release-set-build');
    const compareButton = $('release-set-compare');
    if (buildButton) buildButton.disabled = selectedCount === 0 || Boolean(state.activeAction);
    ['release-set-plan', 'release-set-apply'].forEach((id) => {
      if ($(id)) $(id).disabled = selectedCount === 0 || Boolean(state.activeAction) || (id === 'release-set-apply' && !$('release-set-acknowledged')?.checked);
    });
    if (compareButton) compareButton.disabled = Boolean(state.activeAction);
    if (state.releaseSetResultHtml) {
      result.innerHTML = state.releaseSetResultHtml;
    } else if (!state.releaseSetLastManifest) {
      result.textContent = selectedCount
        ? `已选择 ${selectedCount} 个库；生成后会得到 release_set_manifest.json。`
        : '请选择至少一个已有当前有效组合的库。';
    }
  }

  function renderMetrics(library) {
    $('metric-effective').textContent = library?.current_effective || '未设置';
  }

  function isComplete(item) {
    return ['事实已生成', '当前可用版本', '初始基线'].includes(String(item.workflow_status?.label || ''));
  }

  function selectedLibraryRow() {
    return state.libraries.find((row) => row.library_name === state.selectedLibrary) || null;
  }

  function workflowLabel(item) {
    return String(item?.workflow_status?.label || '');
  }

  function selectedLatestVersionId() {
    return String(selectedLibraryRow()?.latest_version || '');
  }

  function latestVersionRow() {
    const latest = selectedLatestVersionId();
    return latest ? state.versions.find((item) => item.version_id === latest) || null : null;
  }

  function baseForLatestVersionId() {
    const latest = latestVersionRow();
    return String(latest?.adjacent_base_version || latest?.base_version || '');
  }

  function isScanAttention(item) {
    const label = workflowLabel(item);
    if (!item?.scan_evidence_ready) return true;
    return ['扫描失败', '需补扫', '待生成扫描', '基准待扫描'].includes(label);
  }

  function isCurrentEffectiveVersion(item) {
    return Boolean(item?.current_effective);
  }

  function isLatestVersion(item) {
    const latest = selectedLatestVersionId();
    return Boolean(latest && item?.version_id === latest);
  }

  function isBaseForLatestVersion(item) {
    const base = baseForLatestVersionId();
    return Boolean(base && item?.version_id === base);
  }

  function isFocusScanAttention(item) {
    return Boolean(item?.focus_scope) && isScanAttention(item);
  }

  function versionFilterName(value) {
    return {
      focus: '当前关注',
      all: '全部历史',
      scan: '新版本待扫',
      new_scan: '新版本待扫',
      base_scan: '基准待扫',
      effective_hygiene: '当前版补证据',
      compare: '待对比',
      review: '可审查',
      effective: '当前有效',
      blocked: '发布待确认',
      error: '异常',
    }[value] || '当前关注';
  }

  function versionDateKey(item) {
    const versionId = String(item?.version_id || '');
    const match = versionId.match(/20\d{6}/);
    return match ? Number(match[0]) : 0;
  }

  function versionMatchesFilter(item, filter) {
    const inFocus = Boolean(item.focus_scope);
    if (filter === 'focus') return inFocus;
    if (filter === 'effective') return item.current_effective;
    if (filter === 'scan' || filter === 'new_scan') return isFocusScanAttention(item) && !isCurrentEffectiveVersion(item) && !isBaseForLatestVersion(item);
    if (filter === 'base_scan') return isFocusScanAttention(item) && isBaseForLatestVersion(item);
    if (filter === 'effective_hygiene') return isCurrentEffectiveVersion(item) && isScanAttention(item);
    if (filter === 'compare') return inFocus && deriveVersionTask(item).state === '待对比';
    if (filter === 'review') return inFocus && deriveVersionTask(item).state === '审查事实已就绪';
    if (filter === 'blocked') return inFocus && String(item.release_status || '').toUpperCase().includes('BLOCK');
    if (filter === 'error') {
      const scan = String(item.scan_status || '').toUpperCase();
      const diff = String(item.diff_status || '').toUpperCase();
      return inFocus && (scan.includes('FAIL') || diff.includes('FAIL') || diff.includes('ERROR') || String(item.package_type || '').includes('UNKNOWN'));
    }
    return true;
  }

  function versionAttentionScore(item) {
    if (!item.focus_scope && !item.current_effective) return 8;
    if (versionMatchesFilter(item, 'error')) return 0;
    if (versionMatchesFilter(item, 'new_scan')) return 1;
    if (versionMatchesFilter(item, 'base_scan')) return 2;
    if (versionMatchesFilter(item, 'compare')) return 3;
    if (versionMatchesFilter(item, 'review')) return 4;
    if (versionMatchesFilter(item, 'effective_hygiene')) return 5;
    if (versionMatchesFilter(item, 'blocked')) return 6;
    if (item.current_effective) return 7;
    return 8;
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
    const filters = ['focus', 'new_scan', 'base_scan', 'effective_hygiene', 'compare', 'review', 'effective', 'blocked', 'error', 'all'];
    return Object.fromEntries(filters.map((filter) => [filter, state.versions.filter((item) => versionMatchesFilter(item, filter)).length]));
  }

  function renderVersionFacets() {
    const target = $('version-status-facets');
    const advancedTarget = $('version-advanced-facets');
    if (!target || !advancedTarget) return;
    if (!state.selectedLibrary) {
      target.innerHTML = '<span class="version-facet-note">选择库后显示版本状态计数。</span>';
      advancedTarget.innerHTML = '';
      return;
    }
    const counts = versionFacetCounts();
    const filters = ['focus', 'all', 'error'];
    const advancedFilters = ['new_scan', 'base_scan', 'effective_hygiene', 'compare', 'review', 'effective', 'blocked'];
    const render = (items) => items.map((filter) => `
      <button class="version-facet ${state.versionFilter === filter ? 'is-active' : ''}" data-version-facet="${filter}" type="button">
        <span>${escapeHtml(versionFilterName(filter))}</span><strong>${Number(counts[filter] || 0)}</strong>
      </button>`).join('');
    target.innerHTML = render(filters);
    advancedTarget.innerHTML = render(advancedFilters);
    document.querySelectorAll('[data-version-facet]').forEach((button) => button.addEventListener('click', () => {
      state.versionFilter = button.dataset.versionFacet || 'all';
      updateRouteState();
      renderVersions();
      renderVersionFacts();
    }));
  }

  function versionRoleLabel(item) {
    if (!item) return '未选择';
    if (item.current_effective) return '当前有效';
    const selected = item.version_id === state.selectedVersion?.version_id;
    if (selected) return '当前对象';
    if (item.focus_scope) return '当前关注';
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
    const base = item.adjacent_base_version || item.base_version || '';
    return `<td><span class="mini-chip ${scanReady ? 'is-good' : 'is-warn'}">${escapeHtml(scanLabel)}</span></td>
      <td><span class="mini-chip ${diffClass}">${escapeHtml(diffLabel)}</span>${base ? `<small class="version-base-label" title="${escapeHtml(base)}">基准：${escapeHtml(base)}</small>` : ''}</td>
      <td><span class="mini-chip ${releaseStatusClass(releaseStatus).replace('status-', 'is-')}">${escapeHtml(releaseText)}</span></td>`;
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

  function versionPrimaryAction(item) {
    if (!item) return { kind: '', label: '选择版本', reason: '从版本列表选择一个版本。', disabled: true };
    const packageType = String(item.package_type || '').toUpperCase();
    if (['UNKNOWN', 'UNKNOWN_PACKAGE', 'UNCLASSIFIED'].includes(packageType)) {
      return { kind: 'settings', label: '修正包类型', reason: '包类型未确认；先在设置与维护中确认版本类型。' };
    }
    const readiness = effectiveReadiness(item, item.action_readiness || {});
    const task = deriveVersionTask(item);
    if (task.action === '扫描' || task.action === '补扫') {
      return readiness.scan?.enabled
        ? { kind: 'scan', label: task.action, reason: task.note }
        : { kind: 'analysis', label: '查看扫描条件', reason: readiness.scan?.reason || task.note };
    }
    if (task.action === '对比') {
      return readiness.compare?.enabled
        ? { kind: 'compare', label: readiness.compare.button_label || '对比', reason: readiness.compare.reason || task.note }
        : { kind: 'analysis', label: '查看对比条件', reason: readiness.compare?.reason || task.note };
    }
    if (item.version_detail_url) return { kind: 'open', label: '打开详情', reason: task.note };
    return { kind: 'analysis', label: '查看已有结果', reason: '扫描事实已存在；当前没有可打开的版本详情页。' };
  }

  function versionFocusActionDisabled(item, action, activeAction) {
    return !item || Boolean(activeAction)
      || (action === 'open' && !item.version_detail_url)
      || (action === 'next' && versionPrimaryAction(item).disabled);
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

  function renderVersionResultSummary(item) {
    const change = $('version-result-change');
    const scan = $('version-result-scan');
    const compare = $('version-result-compare');
    const base = $('version-result-base');
    const links = $('version-result-links');
    const detail = $('version-result-detail');
    if (!change || !scan || !compare || !base || !links || !detail) return;
    if (!item) {
      change.textContent = '选择版本后显示已生成的扫描与对比结果。';
      scan.textContent = '未读取';
      compare.textContent = '未读取';
      base.textContent = '未读取';
      links.innerHTML = '';
      detail.classList.add('hidden');
      detail.removeAttribute('href');
      return;
    }
    change.textContent = String(item.change_summary || (hasCompareRecord(item) ? statusLabel(item.diff_status) : '尚无对比结果；扫描完成不代表已完成版本对比。'));
    scan.textContent = scanFactLabel(item);
    compare.textContent = compareFactLabel(item);
    base.textContent = item.base_version || '无对比基准';
    detail.classList.toggle('hidden', !item.version_detail_url);
    if (item.version_detail_url) detail.href = item.version_detail_url;
    else detail.removeAttribute('href');
    const entries = [
      ['扫描报告', item.scan_html],
      ['对比报告', item.diff_html],
    ].filter(([, href]) => typeof href === 'string' && (/^https?:\/\//.test(href) || href.startsWith('/artifacts/')));
    links.innerHTML = entries.map(([label, href]) => `<a class="text-link" href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${label} ↗</a>`).join('');
  }

  function filteredVersions() {
    const query = state.versionQuery.trim().toLowerCase();
    const filtered = state.versions.filter((item) => {
      const searchable = `${item.version_id || ''} ${item.package_type || ''} ${item.adjacent_base_version || ''} ${item.base_version || ''} ${item.release_status || ''}`.toLowerCase();
      const matchesQuery = !query || searchable.includes(query);
      if (!matchesQuery) return false;
      if (query && state.versionFilter === 'focus') return true;
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
    const query = state.versionQuery.trim();
    $('version-count').textContent = state.versionsLoading
      ? '读取中'
      : query
        ? `搜索结果 ${allRows.length} / ${state.versions.length}`
        : allRows.length === state.versions.length
          ? `${loadedText} 个版本`
          : `${filterName} ${allRows.length} / ${state.versions.length}`;
    const pageSummary = $('version-pagination-summary');
    const loadMore = $('load-more-versions');
    if (pageSummary) {
      const showing = Math.min(rows.length, allRows.length);
      const filteredNote = allRows.length === state.versions.length ? '' : query ? `，搜索命中 ${allRows.length}` : `，筛选命中 ${allRows.length}`;
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
      $('version-table-body').innerHTML = '<tr><td colspan="5" class="empty-cell">正在读取版本列表…</td></tr>';
      return;
    }
    if (state.versionLoadError) {
      $('version-table-body').innerHTML = `<tr><td colspan="5" class="empty-cell">${escapeHtml(state.versionLoadError)}</td></tr>`;
      return;
    }
    $('version-table-body').innerHTML = rows.length ? rows.map((item) => `
      <tr class="version-row ${item.version_id === state.selectedVersion?.version_id ? 'selected' : ''}" data-version="${escapeHtml(item.version_id)}">
        <td><button class="version-link" type="button" title="${escapeHtml(item.version_id)} · ${escapeHtml(versionRoleLabel(item))}">${escapeHtml(item.version_id)}</button></td>
        <td><span class="package-pill">${escapeHtml(packageLabel(item.package_type))}</span></td>
        ${versionEvidenceChips(item)}
      </tr>`).join('') : `<tr><td colspan="5" class="empty-cell">${state.versions.length ? '没有符合筛选条件的版本。' : '该库没有版本记录。'}</td></tr>`;
    document.querySelectorAll('[data-version]').forEach((row) => row.addEventListener('click', () => selectVersion(row.dataset.version)));
    document.querySelectorAll('[data-version-focus-action]').forEach((button) => {
      const action = button.dataset.versionFocusAction;
      button.disabled = versionFocusActionDisabled(state.selectedVersion, action, state.activeAction);
      if (action === 'next') {
        const next = versionPrimaryAction(state.selectedVersion);
        button.textContent = next.label;
        button.title = next.reason;
      } else {
        button.title = button.disabled ? '该版本详情尚未生成。' : '';
      }
    });
    $('version-focus-action-hint').textContent = state.selectedVersion
      ? versionPrimaryAction(state.selectedVersion).reason
      : '选择版本后执行操作';
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

  function releasePlanStatusLabel(status) {
    if (status === 'DRY_RUN') return '预演已生成';
    if (status === 'FORCE_DRY_RUN') return '强制预演已生成';
    if (status === 'APPLIED') return '已发布';
    if (status === 'FORCED_APPLIED') return '已发布（强制）';
    if (status === 'PARTIAL_APPLIED') return '部分发布（同名冲突）';
    if (status === 'PARTIAL_DRY_RUN') return '预演完成（同名冲突将跳过）';
    if (status === 'BLOCKED') return '发布受阻';
    if (status === 'MIGRATION_REQUIRED') return '入口需迁移';
    if (['FAILED', 'FORCE_FAILED'].includes(status)) return '发布失败';
    return statusLabel(status || '未知');
  }

  function releaseLinkAction(row) {
    if (row.status === 'FAILED' || row.error) return 'failed';
    const value = row.link_action || row.status;
    return ({LINK: 'new', REPLACE: 'replace', KEEP: 'same', WOULD_LINK: 'new', WOULD_REPLACE: 'replace', WOULD_KEEP: 'same'})[value] || 'unknown';
  }

  function initialReleaseLinkScope(rows) {
    return rows.some((row) => row.error || row.warning || ['replace', 'failed'].includes(releaseLinkAction(row)))
      ? 'focus' : 'all';
  }

  function filterReleaseLinks(rows, query, type, scope) {
    const term = String(query || '').trim().toLowerCase();
    return rows.filter((row) => {
      const action = releaseLinkAction(row);
      const exception = Boolean(row.error || row.warning || action === 'failed');
      return (!type || row.file_type === type)
        && (!term || `${row.relative_path} ${row.target_path || ''} ${row.previous_target || ''} ${row.library_name || ''} ${row.version_id || ''}`.toLowerCase().includes(term))
        && (scope === 'all' || (scope === 'focus' ? exception || action === 'replace' : scope === 'exceptions' ? exception : scope === action));
    });
  }

  function releaseResultHeadline(plan) {
    const count = plan.planned_files == null ? '文件数量未记录' : `${plan.planned_files} 个交付文件`;
    if (['PARTIAL_APPLIED', 'PARTIAL_DRY_RUN'].includes(plan.status)) return `${plan.dry_run ? '预演完成，尚未发布；拟交付' : '部分发布完成；已交付'} ${plan.created_files || 0} 个文件，同名冲突跳过 ${plan.skipped_files || 0} 个；冲突目标未交付`;
    if (plan.dry_run) return ['DRY_RUN', 'FORCE_DRY_RUN'].includes(plan.status) ? `预演完成，尚未发布；${count}` : '预演未通过，未写入发布目录';
    if (!['APPLIED', 'FORCED_APPLIED'].includes(plan.status)) return '发布未完成；请核对下方异常和原发布入口';
    return ['PASS', 'PASS_WITH_WARNING'].includes(plan.verify_status) ? `已发布；${count}，链接校验通过${plan.verify_status === 'PASS_WITH_WARNING' ? '（有提醒）' : ''}` : `已执行发布；链接校验${plan.verify_status === 'FAILED' ? '未通过' : '未完成'}`;
  }

  function releaseCsvCell(value) {
    let text = String(value ?? '');
    if (/^[=+@\-\t\r]/.test(text)) text = '\t' + text;
    return '"' + text.replaceAll('"', '""') + '"';
  }

  function renderReleasePlanResult(plan = state.releasePlan) {
    const multiLibrary = plan?.scope === 'release_set';
    const container = $(multiLibrary ? 'release-set-plan-result' : 'release-plan-result');
    const inactive = $(multiLibrary ? 'release-plan-result' : 'release-set-plan-result');
    if (inactive) { inactive.classList.add('hidden'); inactive.innerHTML = ''; }
    if (!container) return;
    const selected = state.selectedVersion?.version_id || '';
    if (!plan || (!multiLibrary && (plan.library !== state.selectedLibrary || plan.version !== selected))) {
      container.classList.add('hidden');
      container.innerHTML = '';
      return;
    }
    const rows = plan.link_rows || [];
    const tableState = state.releaseTable?.plan === plan
      ? state.releaseTable
      : {plan, query: '', type: '', scope: initialReleaseLinkScope(rows), page: 0};
    state.releaseTable = tableState;
    const verified = ['APPLIED', 'FORCED_APPLIED'].includes(plan.status) && ['PASS', 'PASS_WITH_WARNING'].includes(plan.verify_status);
    const previewReady = plan.dry_run && ['DRY_RUN', 'FORCE_DRY_RUN'].includes(plan.status);
    const items = [
      [plan.dry_run ? '拟发布位置' : '正式位置', plan.release_dir || '未记录'],
      ['最新入口', plan.target_alias || '未记录'],
      [plan.dry_run ? '拟保留旧链接' : '旧链接备份', plan.daily_backup || '未记录'],
    ];
    const command = plan.dry_run ? (plan.final_cli_command || '') : '';
    const labels = {new: plan.link_mode === 'copy' ? '新建文件' : '新建链接', replace: plan.link_mode === 'copy' ? '替换文件' : '替换指向', same: '指向相同', failed: '异常', unknown: '操作未记录'};
    const counts = Object.fromEntries(Object.keys(labels).map((key) => [key, rows.filter((row) => releaseLinkAction(row) === key).length]));
    const issues = plan.issues || [];
    container.classList.remove('hidden');
    container.innerHTML = `<div class="release-plan-result-heading"><strong>${plan.dry_run ? '发布预演结果' : '实际发布结果'}</strong><span class="status-chip ${verified || previewReady ? 'status-good' : 'status-warn'}">${escapeHtml(releasePlanStatusLabel(plan.status))}</span></div><p class="release-result-headline">${escapeHtml(releaseResultHeadline(plan))}</p><p class="release-result-object">${escapeHtml(plan.library)} / ${escapeHtml(plan.version)} · ${plan.link_mode === 'copy' ? '复制交付' : '链接交付'}</p><dl class="release-result-destinations">${items.map(([label, value], index) => `<div><dt>${escapeHtml(label)}</dt><dd><code title="${escapeHtml(value)}">${escapeHtml(value)}</code>${value.startsWith('/') ? `<button class="release-copy-path button button-secondary button-small" data-path-index="${index}" type="button">复制路径</button>` : ''}</dd></div>`).join('')}</dl><div class="release-impact-strip">${Object.entries(counts).filter(([, count]) => count > 0).map(([key, count]) => `<button class="facet-chip" data-release-scope="${key}" type="button">${labels[key]} <b>${count}</b></button>`).join('')}</div>${issues.length ? `<details class="release-result-issues" open><summary>异常与提醒 ${issues.length}</summary><ul>${issues.map((issue) => `<li>${escapeHtml(issue.message)}${issue.file ? ` <code>${escapeHtml(issue.file)}</code>` : ''}</li>`).join('')}</ul></details>` : ''}${command ? `<details class="release-cli-details"><summary>终端命令（可选）</summary><div class="release-cli-command"><code>${escapeHtml(command)}</code><button id="copy-release-cli-command" class="button button-secondary button-small" type="button">复制</button></div></details>` : ''}`;
    if (multiLibrary) container.querySelector('.release-result-object').textContent = `多库阶段 ${plan.publish_name || '未记录'} · ${plan.link_mode === 'copy' ? '复制交付' : '链接交付'}`;
    if (plan.excluded_files) {
      container.insertAdjacentHTML('beforeend', `<details class="release-result-issues"><summary>不参与交付 ${Number(plan.excluded_files)} 个文件</summary><div class="release-link-scroll"><table><thead><tr><th>原始文件</th><th>排除原因</th></tr></thead><tbody>${(plan.excluded_rows || []).map((row) => `<tr><td><code>${escapeHtml(row.source_path)}</code></td><td>${escapeHtml(row.reason)}</td></tr>`).join('')}</tbody></table></div></details>`);
    }
    container.querySelectorAll('.release-copy-path').forEach((button) => button.addEventListener('click', async () => {
      button.textContent = await copyText(items[Number(button.dataset.pathIndex)][1]) ? '已复制' : '复制失败';
    }));
    $('copy-release-cli-command')?.addEventListener('click', async () => {
      const copied = await copyText(command);
      $('copy-release-cli-command').textContent = copied ? '已复制' : '复制失败';
    });
    if (rows.length) {
      const types = [...new Set(rows.map((row) => row.file_type || 'unknown'))].sort();
      container.insertAdjacentHTML('beforeend', `<div class="release-link-toolbar"><strong>文件核查</strong><input id="release-link-search" type="search" placeholder="搜索文件、来源版本或路径" aria-label="搜索发布链接"><select id="release-link-type" aria-label="按发布视图类型筛选"><option value="">全部类型</option>${types.map((type) => `<option value="${escapeHtml(type)}">${escapeHtml(fileTypeLabel(type))}</option>`).join('')}</select><select id="release-link-filter" aria-label="按链接操作筛选"><option value="focus">替换及异常</option><option value="all">全部文件</option><option value="exceptions">仅异常 / 提醒</option>${Object.entries(labels).map(([value, label]) => `<option value="${value}">${label}</option>`).join('')}</select><button id="release-link-export" class="button button-secondary button-small" type="button">导出筛选结果</button></div><div class="release-link-scroll"><table><thead><tr><th>链接操作</th><th>视图类型</th><th>发布文件</th><th>来源库 / 版本</th><th>旧指向</th><th>本次源文件</th><th>检查结果</th></tr></thead><tbody id="release-link-rows"></tbody></table></div><div class="release-table-footer"><span id="release-link-count"></span><button id="release-link-prev" class="button button-secondary button-small" type="button">上一页</button><button id="release-link-next" class="button button-secondary button-small" type="button">下一页</button></div>`);
      let page = tableState.page;
      $('release-link-search').value = tableState.query;
      $('release-link-type').value = tableState.type;
      $('release-link-filter').value = tableState.scope;
      const filtered = () => filterReleaseLinks(rows, $('release-link-search').value, $('release-link-type').value, $('release-link-filter').value);
      const linksVerified = verified || (plan.status === 'PARTIAL_APPLIED' && ['PASS', 'PASS_WITH_WARNING'].includes(plan.verify_status));
      const checkLabel = (row) => row.error || row.warning || (plan.dry_run ? '源文件已检查' : linksVerified ? '链接校验通过' : '未确认交付');
      const renderLinks = () => {
        const visible = filtered();
        const pages = Math.max(1, Math.ceil(visible.length / 50));
        page = Math.min(page, pages - 1);
        Object.assign(tableState, {page, query: $('release-link-search').value, type: $('release-link-type').value, scope: $('release-link-filter').value});
        const currentRows = visible.slice(page * 50, (page + 1) * 50);
        $('release-link-count').textContent = `匹配 ${visible.length} / 总计 ${rows.length} 文件 · ${page + 1} / ${pages} 页`;
        $('release-link-prev').disabled = page === 0;
        $('release-link-next').disabled = page >= pages - 1;
        $('release-link-rows').innerHTML = currentRows.length ? currentRows.map((row) => `<tr><td>${escapeHtml(labels[releaseLinkAction(row)])}</td><td>${escapeHtml(fileTypeLabel(row.file_type))}</td><td title="${escapeHtml(row.link_path)}"><code>${escapeHtml(row.relative_path)}</code></td><td>${escapeHtml(row.library_name || plan.library)}<br><code>${escapeHtml(row.version_id || plan.version)}</code></td><td><code>${escapeHtml(row.previous_target || (releaseLinkAction(row) === 'new' ? '无旧文件' : '未记录'))}</code></td><td><code>${escapeHtml(row.target_path)}</code></td><td>${escapeHtml(checkLabel(row))}</td></tr>`).join('') : '<tr><td colspan="7" class="release-empty">当前筛选没有文件；可切换“全部文件”核查完整交付清单。</td></tr>';
      };
      $('release-link-search').addEventListener('input', () => { page = 0; renderLinks(); });
      ['release-link-filter', 'release-link-type'].forEach((id) => $(id).addEventListener('change', () => { page = 0; renderLinks(); }));
      $('release-link-prev').addEventListener('click', () => { page -= 1; renderLinks(); });
      $('release-link-next').addEventListener('click', () => { page += 1; renderLinks(); });
      container.querySelectorAll('[data-release-scope]').forEach((button) => button.addEventListener('click', () => { $('release-link-filter').value = button.dataset.releaseScope; page = 0; renderLinks(); }));
      $('release-link-export').addEventListener('click', () => {
        const data = [['链接操作', '视图类型', '发布文件', '发布路径', '来源库', '来源版本', '旧指向', '本次源文件', '检查结果'], ...filtered().map((row) => [labels[releaseLinkAction(row)], fileTypeLabel(row.file_type), row.relative_path, row.link_path, row.library_name || plan.library, row.version_id || plan.version, row.previous_target, row.target_path, checkLabel(row)])];
        const url = URL.createObjectURL(new Blob(['\uFEFF' + data.map((row) => row.map(releaseCsvCell).join(',')).join('\r\n')], {type: 'text/csv;charset=utf-8'}));
        const link = document.createElement('a');
        link.href = url;
        link.download = '发布文件核查.csv';
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
      renderLinks();
    } else {
      container.insertAdjacentHTML('beforeend', '<p class="release-empty">未生成文件核查清单，请查看异常或运行日志。</p>');
    }
  }

  function renderActionDeckReadiness(item, readiness = {}) {
    const base = String(item?.adjacent_base_version || item?.base_version || '');
    const fileDiff = item
      ? { enabled: true, label: base ? '可选择文件' : '可指定文件', reason: base ? '从变化清单选择成对文件，或填写同路径文件。' : '没有基准时仍可使用任意两文件对比。' }
      : { enabled: false, label: '等待对象', reason: '选择版本后可以选择文件。' };
    const review = item
      ? { enabled: true, label: '可记录', reason: '可查看门禁、准备审查记录或记录人工结论。' }
      : { enabled: false, label: '等待对象', reason: '选择版本后可以记录审查结论。' };
    setActionDeckState('scan', readiness.scan);
    setActionDeckState('compare', readiness.compare);
    setActionDeckState('file-diff', fileDiff);
    setActionDeckState('review', review);
    setActionDeckState('release-check', readiness['release-check']);
    renderReleasePlanResult();
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

  function effectiveReadiness(item, readiness = {}) {
    const merged = { ...readiness };
    const base = String(item?.adjacent_base_version || item?.base_version || '').trim();
    const scanIfMissing = Boolean($('scan-if-missing')?.checked);
    if (
      item
      && base
      && item.scan_evidence_ready
      && scanIfMissing
      && merged.compare
      && !merged.compare.enabled
      && /基准/.test(String(merged.compare.reason || ''))
    ) {
      merged.compare = {
        ...merged.compare,
        enabled: true,
        label: '可补扫后对比',
        button_label: '补扫并对比',
        reason: `将先补齐基准 ${base} 的扫描证据，再生成对比。`,
      };
    }
    return merged;
  }

  function analysisNextStep(item) {
    if (!item) return null;
    if (!item.scan_evidence_ready) return {label: '准备扫描', target: 'scan'};
    if (!(item.adjacent_base_version || item.base_version)) return {label: '查看扫描文件', target: 'tree'};
    const hasResult = ['DIFF_DONE', 'PASS', 'PASS_WITH_WARNING', 'SAME', 'COMPLETED', 'DONE', 'DIFFED', 'COMPARED'].includes(String(item.diff_status || '').toUpperCase());
    if (item.diff_evidence_ready || item.diff_html || hasResult) return {label: '查看变化文件', target: 'changes'};
    return {label: '设置版本对比', target: 'compare'};
  }

  function renderActionDeckNavigation(item) {
    const nextButton = $('analysis-next-step');
    const next = analysisNextStep(item);
    if (nextButton) {
      nextButton.textContent = next?.label || '未选择版本';
      nextButton.dataset.target = next?.target || '';
      nextButton.disabled = !next || Boolean(state.activeAction);
    }
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

  function selectAnalysisAction(action) {
    const tabs = Array.from(document.querySelectorAll('[data-analysis-action]'));
    if (!tabs.some(tab => tab.dataset.analysisAction === action)) return;
    tabs.forEach(tab => {
      const selected = tab.dataset.analysisAction === action;
      tab.setAttribute('aria-pressed', String(selected));
      tab.classList.toggle('is-active', selected);
      const panel = $(tab.getAttribute('aria-controls'));
      if (panel) panel.hidden = !selected;
    });
  }

  function activateWorkbenchCommand(command) {
    if (command === 'release') {
      setActiveStageTab('release-workspace');
      return;
    }
    const action = ['scan', 'compare', 'file-diff', 'checks', 'review'].includes(command) ? command : '';
    if (!action) return;
    selectAnalysisAction(action);
    setActiveStageTab('action-workspace');
  }

  function openFileDiffWorkbench() {
    if (!$('open-file-diff') || $('open-file-diff').disabled) return;
    scrollToStage('evidence-workspace');
    activateWorkspaceTab('changes');
    const selection = $('file-change-selection');
    if (selection) window.requestAnimationFrame(() => selection.scrollIntoView({ behavior: 'smooth', block: 'center' }));
  }

  function openReviewActions() {
    if (!$('open-review-actions') || $('open-review-actions').disabled) return;
    selectAnalysisAction('review');
    scrollToStage('action-workspace');
    const details = $('review-actions-details');
    if (details) {
      details.open = true;
      window.requestAnimationFrame(() => details.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
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
    renderEffectiveSelection();
    const draft = effectiveSelectionDraft();
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
        || (isAccept && (!hasCandidate || !effectiveSelectionMatchesCandidate(draft, pendingWindow.candidate_effective_stack)))
        || (['next-preview', 'intake-preview'].includes(workflowAction) && !draft?.base_full)
        || (['next-apply', 'intake-apply'].includes(workflowAction)
          && !effectiveSelectionPreviewReady(draft, workflowAction.split('-')[0]));
      button.title = isReadSuggestion && !hasSuggestion
        ? '当前还没有接入建议，请先生成处理建议。'
        : isAccept && (!hasCandidate || !effectiveSelectionMatchesCandidate(draft, pendingWindow.candidate_effective_stack))
          ? '当前候选与选择不一致或尚未生成，请先预览并生成所选组合。'
          : workflowAction.endsWith('-apply') && button.disabled
            ? '请先成功预览同一组成与顺序。'
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
      renderVersionResultSummary(null);
      renderActionDeckReadiness(null);
      renderActionDeckNavigation(null);
      updateExplicitFileDiffState();
      renderEffectiveStack();
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
    const displayReadiness = effectiveReadiness(item, readiness);
    const task = deriveVersionTask(item);
    const reviewDecision = item.workflow_status || { label: '待处理', reason: '请按动作条件补齐事实。', next_action: '查看详情' };
    $('flow-object-value').textContent = item.version_id || '未选择版本';
    $('flow-facts-value').textContent = `扫描 ${scanFactLabel(item)} · 对比 ${compareFactLabel(item)}`;
    $('flow-release-value').textContent = releaseLabel(item.release_status);
    $('version-role').textContent = item.current_effective ? '当前有效' : stageLabel(item.stage);
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
    renderVersionResultSummary(item);
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
      'release-plan': ['release-plan-action-button', '↗'],
    };
    Object.entries(buttons).forEach(([action, [id, icon]]) => {
      const button = $(id);
      const stateForAction = (action === 'release-plan' ? displayReadiness['release-check'] : displayReadiness[action]) || { enabled: false, label: '不可用', reason: '当前版本缺少动作条件' };
      button.disabled = !stateForAction.enabled || Boolean(state.activeAction);
      button.title = stateForAction.reason || '';
      const label = action === 'release-plan' ? '生成发布预演' : (stateForAction.button_label || stateForAction.label || '执行');
      button.innerHTML = `<span aria-hidden="true">${icon}</span> ${escapeHtml(label)}`;
    });
    const forceButton = $('release-force-action-button');
    invalidateReleasePreview();
    const forceTarget = state.formalReleaseTarget;
    const forceReady = Boolean((displayReadiness['release-check'] || {}).enabled) && Boolean(forceTarget);
    forceButton.disabled = !forceReady || Boolean(state.activeAction);
    forceButton.title = !forceTarget
      ? '请先在正式发布库列表选择覆盖目标'
      : (displayReadiness['release-check'] || {}).reason || '强制发布仍会执行底层发布校验并写入审计记录。';
    renderActionDeckReadiness(item, displayReadiness);
    renderActionDeckNavigation(item);
    updateExplicitFileDiffState();
    renderEffectiveStack();
    $('write-action-hint').textContent = workflowWindowHint(pendingWindow);
    setActionDeckMessage(task.note);
    renderFileChangeWorkbench();
    renderFileTree();
  }

  function workflowWindowHint(windowState) {
    if (windowState.state === 'INVALID') return '已保存计划无法读取，请重新预览处理计划。';
    if (windowState.state !== 'PENDING') return '尚无待确认候选；先预览处理计划，再执行生成候选。';
    if (!windowState.candidate_effective_id) return '已有计划，但尚未生成候选组合。';
    if (windowState.candidate_manifest_exists === false) return '候选清单尚未生成，请执行处理计划。';
    return `待核对候选：${windowState.candidate_effective_id}；确认提交时仍会校验对比证据与审查记录。`;
  }

  function renderWorkspaceSettings() {
    const report = state.workspace?.catalog_report || {};
    const reportLink = $('catalog-report-link');
    if (reportLink) {
      reportLink.classList.toggle('hidden', !report.available);
      if (report.available) {
        reportLink.href = report.url;
        reportLink.title = report.path;
      } else reportLink.removeAttribute('href');
    }
    $('catalog-report-missing')?.classList.toggle('hidden', Boolean(report.available));
    const settings = state.workspace?.scan_strategy || {};
    const discovery = state.workspace?.discovery_strategy || {};
    const paths = state.workspace?.paths || {};
    if ($('release-root-display')) $('release-root-display').value = paths.release_root || '未配置';
    const releaseSettings = state.workspace?.release_settings || {};
    if ($('release-set-publish-name') && !$('release-set-publish-name').value) $('release-set-publish-name').value = releaseSettings.publish_name || '';
    if ($('release-publish-name')) $('release-publish-name').value = releaseSettings.publish_name || '';
    if ($('release-overwrite')) {
      $('release-overwrite').disabled = Boolean(releaseSettings.publish_name);
      if (releaseSettings.publish_name) $('release-overwrite').checked = true;
    }
    if ($('release-latest-name')) $('release-latest-name').value = releaseSettings.latest_name || 'latest';
    if ($('config-release-publish-name')) $('config-release-publish-name').value = releaseSettings.publish_name || '';
    if ($('config-release-latest-name')) $('config-release-latest-name').value = releaseSettings.latest_name || 'latest';
    if ($('config-raw-root')) $('config-raw-root').value = paths.raw_root || '';
    if ($('config-release-root')) $('config-release-root').value = paths.release_root || '';
    if ($('formal-release-root') && !$('formal-release-root').value.trim()) $('formal-release-root').value = paths.release_root || '';
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
    renderDefaultSettings();
    updateSettingsSummary();
    const discoverRoot = $('candidate-discover-root');
    if (discoverRoot && !discoverRoot.value.trim()) discoverRoot.value = paths.raw_root || '';
    const labels = { workspace: '工作区', raw_root: '原始库根', catalog: '目录快照', catalog_html: 'HTML 输出', reports: '扫描报告', diff: '对比报告', release_root: '正式发布根目录', release_library_index: '发布库索引' };
    $('workspace-paths').innerHTML = Object.entries(labels).map(([key, label]) => `<div><dt>${label}</dt><dd title="${escapeHtml(paths[key] || '未设置')}">${escapeHtml(paths[key] || '未设置')}</dd></div>`).join('');
  }

  function renderWorkspaceSetup() {
    const panel = $('workspace-setup-panel');
    if (!panel) return;
    const setupRequired = Boolean(state.workspace?.setup_required);
    panel.classList.toggle('hidden', !setupRequired);
    const paths = state.workspace?.paths || {};
    const feedback = $('setup-feedback');
    if (setupRequired) {
      const cwd = paths.cwd || '';
      if (!$('setup-workspace').value.trim()) $('setup-workspace').value = cwd ? `${cwd}/work/lib_guard_workspace` : '';
      if (!$('setup-raw-root').value.trim()) $('setup-raw-root').value = paths.raw_root || '';
      if (feedback) {
        feedback.textContent = state.workspaceSetupMessage || state.workspace?.message || '请先初始化工作区。';
        feedback.classList.toggle('is-error', state.workspaceSetupError);
      }
      $('catalog-source').textContent = '事实来源：尚未初始化';
      $('selected-library').textContent = '先初始化工作区';
      $('selected-library-meta').textContent = '填写工作区目录和原始库根后，才能登记库、发现候选和生成报告。';
      $('selected-library-crumb').textContent = '未连接';
      $('library-count').textContent = '0';
      $('library-list').innerHTML = '<div class="empty-note">初始化后显示已登记库。</div>';
      $('library-facet-summary').textContent = '尚未连接工作区';
      $('version-count').textContent = '未初始化';
      $('version-table-body').innerHTML = '<tr><td colspan="5" class="empty-cell">请先初始化工作区。</td></tr>';
      $('version-pagination-summary').textContent = '未初始化';
    }
    const button = $('setup-create-config');
    if (button) button.disabled = state.workspaceSetupSaving;
  }

  async function submitWorkspaceSetup() {
    if (state.workspaceSetupSaving) return;
    state.workspaceSetupSaving = true;
    state.workspaceSetupMessage = '正在创建配置并连接工作区…';
    state.workspaceSetupError = false;
    renderWorkspaceSetup();
    try {
      const payload = await getJson('/api/workspace/init', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace: $('setup-workspace').value.trim(),
          raw_root: $('setup-raw-root').value.trim(),
          library_type: $('setup-library-type').value,
        }),
      });
      state.workspace = { ...(state.workspace || {}), ...payload, setup_required: false };
      renderWorkspaceSetup();
      renderWorkspaceSettings();
      setWorkflowStatus('CONNECTED', 'status-good');
      state.workspaceSetupMessage = payload.message || '工作区已连接。';
      await Promise.all([loadLibraries(), loadLibraryCandidates()]);
    } catch (error) {
      state.workspaceSetupMessage = `初始化失败：${error.message}`;
      state.workspaceSetupError = true;
      showError(`初始化失败：${error.message}`);
    } finally {
      state.workspaceSetupSaving = false;
      renderWorkspaceSetup();
    }
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

  function openLibraryPathPicker(target = 'library-add-root') {
    const panel = $('library-path-picker');
    if (!panel) return;
    panel.classList.remove('hidden');
    state.pathBrowserTarget = target;
    $('library-path-picker-title').textContent = target === 'candidate-discover-root' ? '选择发现路径' : '选择库根目录';
    const defaultPath = state.workspace?.paths?.raw_root || state.workspace?.paths?.workspace || '';
    loadPathBrowser($(target)?.value.trim() || defaultPath).catch(() => {});
  }

  function closeLibraryPathPicker() {
    $('library-path-picker')?.classList.add('hidden');
  }

  function useCurrentLibraryPath() {
    if (!state.pathBrowserPath) return;
    const input = $(state.pathBrowserTarget || 'library-add-root');
    input.value = state.pathBrowserPath;
    input.dataset.userEdited = 'true';
    closeLibraryPathPicker();
  }

  function openLibraryAddForm() {
    const disclosure = $('library-add-disclosure');
    if (disclosure) disclosure.open = true;
    scrollToStage('version-workspace');
    window.requestAnimationFrame(() => disclosure?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
    window.requestAnimationFrame(() => $('library-add-id')?.focus());
  }

  function focusVersionActions() {
    scrollToStage('action-workspace');
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
    if (note) note.textContent = `已带入候选库“${candidate.library_id}”。请核对已登记库名和库根目录后，登记并加入目录。`;
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
      note.textContent = '尚无候选结果。选择上方发现路径，点击“重新发现候选库”，核对后勾选登记。';
      body.innerHTML = '<tr><td colspan="6" class="muted">尚未发现候选库。</td></tr>';
    } else {
      const visible = visibleLibraryCandidates();
      const registered = state.libraryCandidates.filter((candidate) => candidate.already_registered).length;
      const warning = Array.isArray(snapshot.warnings) && snapshot.warnings.length ? `；提醒：${snapshot.warnings[0]}` : '';
      note.textContent = `找到 ${state.libraryCandidates.length} 个候选库，已登记 ${registered} 个，显示 ${visible.length} 个${snapshot.start_root ? `；发现范围：${snapshot.start_root}` : ''}${snapshot.truncated ? '；搜索未完成：已达到搜索限制，请收窄发现路径或调整高级搜索限制' : ''}${warning}`;
      if (!visible.length) {
        body.innerHTML = '<tr><td colspan="6" class="muted">没有符合当前筛选条件的候选库。</td></tr>';
      } else {
        body.innerHTML = visible.map((candidate) => {
          const checked = state.selectedCandidateIds.has(candidate.candidate_id);
          const disabled = Boolean(candidate.already_registered || candidate.name_conflict);
          const versions = Number(candidate.version_count || 0);
          const singleVersion = versions === 1;
          const detail = [candidate.vendor, candidate.middle_path].filter(Boolean).join(' / ');
          const versionNames = candidate.version_names?.length ? candidate.version_names : candidate.example_versions || [];
          const versionDetail = versionNames.length ? `<details><summary>${versions} 个版本${versionNames.length < versions ? '（仅有示例）' : ''}</summary><ul class="candidate-version-list">${versionNames.map((name) => `<li><code>${escapeHtml(name)}</code></li>`).join('')}</ul></details>` : '版本明细未提供';
          const evidence = candidate.view_types?.length ? candidate.view_types.join('、') : '旧快照未提供文件类型；可重新发现补充';
          const suggestedId = candidate.suggested_library_id || candidate.library_id;
          return `<tr class="${disabled ? 'is-registered' : ''}">
            <td><input data-candidate-id="${escapeHtml(candidate.candidate_id)}" type="checkbox" ${checked ? 'checked' : ''} ${disabled ? 'disabled' : ''} aria-label="选择 ${escapeHtml(candidate.library_id)}"></td>
            <td><code title="${escapeHtml(suggestedId)}">${escapeHtml(suggestedId)}</code><small>${escapeHtml(candidate.library_id === suggestedId ? (detail || '未标注') : `候选名：${candidate.library_id}`)}</small></td>
            <td><code title="${escapeHtml(candidate.root_abs)}">${escapeHtml(candidate.root_abs)}</code></td>
            <td>${versionDetail}${singleVersion ? '<small>单版本库</small>' : ''}</td>
            <td>${escapeHtml(evidence)}</td>
            <td><span>${escapeHtml(candidateStatusLabel(candidate))}</span>${candidate.already_registered ? '' : `<button class="button button-secondary button-small candidate-use" data-candidate-use="${escapeHtml(candidate.candidate_id)}" type="button">修改库名 / 库根</button>`}</td>
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
    const selectable = visibleLibraryCandidates().filter((item) => !item.already_registered && !item.name_conflict);
    const visibleSelected = selectable.filter((item) => state.selectedCandidateIds.has(item.candidate_id)).length;
    const selectAll = $('candidate-select-all');
    selectAll.checked = selectable.length > 0 && visibleSelected === selectable.length;
    selectAll.indeterminate = visibleSelected > 0 && visibleSelected < selectable.length;
    selectAll.disabled = Boolean(state.activeAction) || state.candidateLoading || !selectable.length;
    $('select-visible-candidates').disabled = selectAll.disabled;
    $('clear-selected-candidates').disabled = Boolean(state.activeAction) || !selected.length;
    $('candidate-selection-summary').textContent = selected.length ? `已选择 ${selected.length} 个候选库（筛选外 ${selected.length - visibleSelected}）；登记将处理全部已选库。` : '尚未选择候选库；全选只勾选筛选中可登记的库。';
  }

  async function loadLibraryCandidates() {
    state.candidateLoading = true;
    state.candidateError = '';
    renderLibraryCandidates();
    try {
      const snapshot = await getJson('/api/library-candidates');
      state.candidateSnapshot = snapshot;
      const discoverInput = $('candidate-discover-root');
      if (snapshot.start_root && discoverInput.dataset.userEdited !== 'true') discoverInput.value = snapshot.start_root;
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

  function visibleFormalReleaseLibraries() {
    const query = state.formalReleaseQuery.trim().toLowerCase();
    if (!query) return state.formalReleaseLibraries;
    return state.formalReleaseLibraries.filter((row) => [row.library_id, row.current_release, row.current_version]
      .some((value) => String(value || '').toLowerCase().includes(query)));
  }

  function renderFormalReleaseLibraries() {
    const body = $('formal-release-library-table-body');
    const status = $('formal-release-library-status');
    const note = $('formal-release-library-note');
    if (!body || !status || !note) return;
    const snapshot = state.formalReleaseSnapshot;
    renderReleaseStages(snapshot);
    status.textContent = state.formalReleaseLoading ? '读取中' : snapshot?.status === 'READY' ? `发布阶段 ${(snapshot.stages || []).length}` : snapshot?.status === 'MISSING' ? '尚未读取' : '索引异常';
    status.className = `status-chip ${state.formalReleaseLoading ? 'status-neutral' : snapshot?.status === 'READY' ? 'status-good' : snapshot?.status === 'MISSING' ? 'status-neutral' : 'status-bad'}`;
    if (state.formalReleaseLoading) {
      note.textContent = '正在读取正式目录记录；不会扫描 RAW，也不会执行发布。';
      body.innerHTML = '<tr><td colspan="7" class="muted">读取正式发布库中…</td></tr>';
      return;
    }
    if (state.formalReleaseError) {
      note.textContent = state.formalReleaseError;
      body.innerHTML = '<tr><td colspan="7" class="muted">正式发布库索引暂不可用。</td></tr>';
      return;
    }
    if (!snapshot || snapshot.status === 'MISSING') {
      note.textContent = '尚无发布历史索引。没有 release_manifest.json 不影响正式目录核查；切换到“正式目录盘点”并刷新实际路径即可。';
      body.innerHTML = '<tr><td colspan="7" class="muted">尚未读取正式发布库目录。</td></tr>';
      return;
    }
    const rows = visibleFormalReleaseLibraries();
    note.textContent = `发布根目录：${snapshot.release_root || '未记录'}；历史清单阶段 ${(snapshot.stages || []).length} 个；来源明细 ${state.formalReleaseLibraries.length} 个库。当前目录结构请看上方正式目录盘点。${snapshot.truncated ? ' 已达到读取上限，请收窄目录。' : ''}`;
    body.innerHTML = rows.length ? rows.map((row) => {
      const history = Array.isArray(row.history) ? row.history : [];
      const mapped = String(row.raw_catalog_match || '');
      const mappedName = String(row.raw_catalog_name || mapped);
      return `<tr>
        <td><code title="${escapeHtml(row.library_id)}">${escapeHtml(row.library_id)}</code>${mapped ? `<small>已登记库：${escapeHtml(mappedName)}</small>` : '<small>未映射到已登记 RAW 库</small>'}</td>
        <td><code>${escapeHtml(row.current_release || '—')}</code></td>
        <td><code>${escapeHtml(row.current_version || '—')}</code></td>
        <td><code>${escapeHtml(row.current_alias || 'current')}</code><small>${escapeHtml(row.current_link_mode === 'copy' ? '复制文件' : row.current_link_mode === 'symlink' ? '符号链接' : '交付方式未记录')}</small></td>
        <td>${escapeHtml(row.current_published_at || '时间未记录')}<small>${escapeHtml(row.current_source === 'alias_link' ? 'current 链接' : '清单回退')}</small></td>
        <td><details><summary>${history.length} 条记录</summary><ul class="formal-release-history">${history.map((item) => `<li>${escapeHtml(item.release_id || '—')} / ${escapeHtml(item.version_id || '—')}</li>`).join('')}</ul></details></td>
        <td>${mapped ? `<button class="button button-secondary button-small" data-formal-release-target="${escapeHtml(row.library_id)}" type="button">选择覆盖目标</button>` : '<small>先登记对应 RAW 库</small>'}</td>
      </tr>`;
    }).join('') : '<tr><td colspan="7" class="muted">没有符合筛选条件的正式发布库。</td></tr>';
    body.querySelectorAll('[data-formal-release-target]').forEach((button) => button.addEventListener('click', async () => {
      const target = state.formalReleaseLibraries.find((row) => row.library_id === button.dataset.formalReleaseTarget);
      if (!target?.raw_catalog_match) return;
      state.formalReleaseTarget = target;
      $('release-overwrite').checked = true;
      await selectLibrary(target.raw_catalog_name || target.raw_catalog_match);
      setActiveStageTab('release-workspace');
      $('release-plan-action-button').focus();
      $('release-overwrite-target').textContent = `覆盖预演目标：${target.library_id} / ${target.current_release || '当前发布'}。`;
      $('release-action-note').textContent = `覆盖预演目标：${target.library_id} / ${target.current_release || '当前发布'}。请在顶部版本表选择新的已扫描版本后生成预演。`;
    }));
  }

  function resetFormalInventoryFilters(check = '') {
    ['formal-directory-library','formal-directory-version','formal-directory-type','formal-directory-query'].forEach(id=>{ $(id).value=''; });
    $('formal-directory-status').value=check;
    state.formalOffset=0;
    loadFormalInventory();
  }

  async function loadFormalInventory() {
    const requestId = state.formalInventoryRequestId = (state.formalInventoryRequestId || 0) + 1;
    const params = new URLSearchParams({library:$('formal-directory-library').value, version:$('formal-directory-version').value, type:$('formal-directory-type').value,
      check:$('formal-directory-status').value, query:$('formal-directory-query').value, offset:String(state.formalOffset)});
    $('formal-directory-files').setAttribute('aria-busy','true');
    $('formal-directory-count').textContent='正在读取盘点结果…';
    $('formal-directory-copy').disabled=true;
    $('formal-directory-copy-status').textContent='';
    try {
      const snapshot = await getJson(`/api/formal-directory?${params}`);
      if (requestId !== state.formalInventoryRequestId) return;
      state.formalInventory = snapshot;
      if (!$('formal-directory-root').value) $('formal-directory-root').value = state.formalInventory.root || '';
      renderFormalInventory();
    } catch (error) { if (requestId === state.formalInventoryRequestId) { $('formal-directory-summary').textContent=error.message; $('formal-directory-count').textContent='读取未完成，保留上一页结果。'; } }
    finally { if(requestId===state.formalInventoryRequestId) $('formal-directory-files').setAttribute('aria-busy','false'); }
  }

  function renderFormalInventory() {
    const snapshot = state.formalInventory || {};
    const rows = snapshot.libraries || [];
    const library = $('formal-directory-library').value, type = $('formal-directory-type').value;
    const version=$('formal-directory-version').value;
    $('formal-directory-library').innerHTML = '<option value="">全部库</option><option value="__unknown__">来源待确认</option>'+rows.map(row=>`<option value="${escapeHtml(row.library)}">${escapeHtml(row.library)}</option>`).join('');
    $('formal-directory-library').value = library;
    $('formal-directory-version').innerHTML='<option value="">全部版本</option>'+(snapshot.versions || []).map(id=>`<option value="${escapeHtml(id)}">${escapeHtml(id)}</option>`).join('');
    $('formal-directory-version').value=version;
    $('formal-directory-type').innerHTML = '<option value="">全部类型</option>'+Object.keys(snapshot.type_counts || {}).sort().map(name=>`<option value="${escapeHtml(name)}">${escapeHtml(fileTypeLabel(name))}</option>`).join('');
    $('formal-directory-type').value = type;
    const auditStatus = snapshot.audit_status || (snapshot.status === 'READY' ? '已读取' : '尚未核查');
    const pointer = snapshot.current_pointer || {};
    const pointerText = pointer.name ? `${pointer.name} → ${pointer.target || '—'}` : (pointer.target || pointer.status || '未配置');
    const summary = snapshot.status === 'READY'
      ? `${auditStatus} · ${snapshot.package_count || 0} 个正式包 · 最近盘点 ${new Date(snapshot.refreshed_at).toLocaleString('zh-CN',{hour12:false})}${snapshot.manifest_present ? ' · 检测到可选来源清单' : ' · 未要求来源清单'}`
      : '指定实际正式目录后刷新；无需发布清单。临时发布输出路径不会被修改。';
    $('formal-directory-summary').textContent = summary;
    $('formal-directory-current-root').textContent = snapshot.root || '尚未盘点';
    $('formal-audit-status').textContent = auditStatus;
    $('formal-audit-status').className = auditStatus === '可用' ? 'status-good' : auditStatus === '不可用' ? 'status-bad' : 'status-warn';
    $('formal-package-count').textContent = snapshot.package_count ?? 0;
    $('formal-current-pointer').textContent = pointerText;
    $('formal-file-view-count').textContent = `${snapshot.file_count || 0} / ${Object.keys(snapshot.view_counts || {}).length}`;
    $('formal-anomaly-count').textContent = `${snapshot.broken_count || 0} / ${(snapshot.extra_paths || []).length}`;
    $('formal-directory-policy').textContent = snapshot.comparison_policy || '正式目录只核查当前交付结构，不比较历史版本；来源版本需要清单或链接目标支持。';
    [['formal-files-all','全部文件',snapshot.file_count || 0,''],['formal-files-unknown','来源待确认',snapshot.unknown_count || 0,'unknown'],['formal-files-broken','断链',snapshot.broken_count || 0,'broken']].forEach(([id,label,count,check])=>{
      $(id).innerHTML=`${label} <b>${count}</b>`;
      $(id).setAttribute('aria-pressed',String(!library && !version && !type && !$('formal-directory-query').value && $('formal-directory-status').value===check));
    });
    $('formal-directory-packages').innerHTML = (snapshot.packages || []).map(row => `<tr><td><strong>${escapeHtml(row.name)}</strong><small><code>${escapeHtml(row.path)}</code></small></td><td>${row.file_count || 0}</td><td>${escapeHtml(Object.entries(row.views || {}).map(([name,count]) => `${name} ${count}`).join(' / ') || '未发现视图文件')}</td><td>${pointer.target === row.name && pointer.status === '正常' ? '<span class="status-chip status-good">当前入口</span>' : '<span class="status-chip status-neutral">正式包</span>'}</td></tr>`).join('') || '<tr><td colspan="4">没有发现 lib_NL* 正式包。若输入的是单个 lib_NL* 目录，它本身会被作为一个正式包核查。</td></tr>';
    $('formal-directory-libraries').innerHTML = rows.map(row=>`<tr><td><button class="button button-quiet" type="button" data-formal-library="${escapeHtml(row.library)}">${escapeHtml(row.library)}</button></td><td>${escapeHtml(row.versions.join('、'))}</td><td>${row.file_count}</td><td>${escapeHtml(Object.entries(row.types).map(([name,count])=>`${fileTypeLabel(name)} ${count}`).join(' / '))}</td><td>${row.broken_count ? `<span class="status-chip status-bad">${row.broken_count}</span>` : '0'}</td></tr>`).join('') || '<tr><td colspan="5">尚无已识别来源库；来源待确认的文件仍在下方保留。</td></tr>';
    $('formal-directory-libraries').querySelectorAll('[data-formal-library]').forEach(button=>button.addEventListener('click',()=>{ $('formal-directory-library').value=button.dataset.formalLibrary; $('formal-directory-version').value=''; state.formalOffset=0; loadFormalInventory(); }));
    $('formal-directory-files').innerHTML = (snapshot.files || []).map(row=>`<tr class="${row.link_status==='链接失效' ? 'formal-link-broken' : ''}"><td><code>${escapeHtml(row.path)}</code></td><td>${escapeHtml(row.library || '待确认')}<br>${escapeHtml(row.version || '版本待确认')}</td><td><code>${escapeHtml(row.source_path || '普通文件，无链接来源')}</code></td><td>${escapeHtml(fileTypeLabel(row.file_type))}</td><td>${escapeHtml(row.corner || '未记录')}</td><td><span class="status-chip ${row.link_status==='链接失效' ? 'status-bad' : row.link_status==='链接正常' ? 'status-good' : 'status-neutral'}">${escapeHtml(row.link_status)}</span><br>${escapeHtml(row.source_status)}</td></tr>`).join('') || '<tr><td colspan="6">没有匹配文件。<br>可清除筛选条件重新查看。</td></tr>';
    $('formal-directory-count').textContent = `第 ${Math.floor(state.formalOffset/100)+1} 页 · 显示 ${snapshot.files?.length || 0} / ${snapshot.matched_count || 0} 个文件`;
    $('formal-directory-copy').disabled=!(snapshot.files?.length);
    $('formal-directory-prev').disabled = !state.formalOffset;
    $('formal-directory-next').disabled = state.formalOffset + 100 >= (snapshot.matched_count || 0);
    if (state.directoryMode === 'published' && state.formalDirectoryMode) {
      const queryText = state.publishedQuery.toLowerCase();
      const visible = rows.filter(row=>row.library.toLowerCase().includes(queryText));
      const packages = (snapshot.packages || []).filter(row=>String(row.name || '').toLowerCase().includes(queryText));
      $('library-count').textContent = rows.length || packages.length;
      $('library-facet-summary').textContent = rows.length ? `${rows.length} 个正式来源库 · ${snapshot.unknown_count || 0} 个文件待确认` : `${packages.length} 个正式包 · 来源版本未记录`;
      $('library-list').innerHTML = rows.length
        ? visible.map(row=>`<button class="library-item ${library===row.library ? 'selected' : ''}" type="button" aria-pressed="${library===row.library}" data-formal-select="${escapeHtml(row.library)}"><strong>${escapeHtml(row.library)}</strong><small>${row.versions.length} 个来源版本 / ${row.file_count} 个文件</small></button>`).join()
        : packages.map(row=>`<button class="library-item" type="button" data-formal-package="${escapeHtml(row.name)}"><strong>${escapeHtml(row.name)}</strong><small>${row.file_count || 0} 个文件 · ${escapeHtml(Object.keys(row.views || {}).join(' / ') || '未记录视图')}</small></button>`).join() || '<p class="empty-note">填写右侧正式目录路径并刷新。</p>';
      $('library-list').querySelectorAll('[data-formal-select]').forEach(button=>button.addEventListener('click',()=>{ $('formal-directory-library').value=button.dataset.formalSelect; $('formal-directory-version').value=''; state.formalOffset=0; loadFormalInventory(); }));
      $('library-list').querySelectorAll('[data-formal-package]').forEach(button=>button.addEventListener('click',()=>{ $('formal-directory-library').value=''; $('formal-directory-version').value=''; $('formal-directory-type').value=''; $('formal-directory-status').value=''; $('formal-directory-query').value=button.dataset.formalPackage; state.formalOffset=0; loadFormalInventory(); }));
    }
  }

  async function refreshFormalInventory() {
    const button=$('formal-directory-refresh');
    button.disabled=true;
    $('formal-directory-summary').textContent='正在盘点实际文件与链接，不读取文件内容…';
    try {
      await getJson('/api/formal-directory/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({root:$('formal-directory-root').value.trim()})});
      state.formalOffset=0;
      $('formal-directory-library').value=''; $('formal-directory-version').value=''; $('formal-directory-type').value=''; $('formal-directory-status').value=''; $('formal-directory-query').value='';
      await loadFormalInventory();
    } catch (error) { $('formal-directory-summary').textContent=`刷新未完成，原快照保留：${error.message}`; }
    finally { button.disabled=false; }
  }

  function setDirectoryMode(mode) {
    state.directoryMode = mode;
    state.publishedRequestId += 1;
    const published = mode === 'published';
    $('directory-source').setAttribute('aria-pressed', String(!published));
    $('directory-published').setAttribute('aria-pressed', String(published));
    $('directory-note').textContent = published ? '正式目录与临时发布记录' : '只显示已登记源库';
    $('directory-boundary').textContent = published ? '正式目录按实际文件盘点；临时输出单独查看。刷新不修改交付链接。' : '源库来自已登记目录；查看不扫描、不发布。';
    $('library-filter').value = published ? state.publishedQuery : state.libraryQuery;
    $('library-filter').placeholder = published ? state.formalDirectoryMode ? '搜索正式来源库' : '搜索发布阶段或包含的库' : '搜索库名称';
    setActiveStageTab(published ? 'published-release-inspector' : 'version-workspace');
    renderLibraries();
    updateRouteState();
    if (published) loadPublishedDetail();
  }

  function renderPublishedDirectory() {
    if (state.formalDirectoryMode) { renderFormalInventory(); return; }
    const stages = state.formalReleaseSnapshot?.stages || [];
    const query = state.publishedQuery.toLowerCase();
    const visible = stages.filter(row => [row.publish_name, ...(row.libraries || []).map(item => item.library_id || item.library_name)].join(' ').toLowerCase().includes(query));
    const missingCount = state.formalReleaseSnapshot?.unregistered_deliveries?.length || 0;
    $('library-count').textContent = stages.length + missingCount;
    $('library-facet-summary').textContent = `已登记 ${stages.length} · 待补登记 ${missingCount}；匹配 ${visible.length}`;
    $('library-list').innerHTML = visible.map(row => `<button type="button" class="library-item ${row.publish_name === state.selectedPublishedStage ? 'selected' : ''}" data-published-stage="${escapeHtml(row.publish_name)}"><strong>${escapeHtml(row.publish_name)}</strong><small>${row.library_count} 库 / ${row.file_count} 文件 · ${row.is_latest ? '当前交付指向此目录' : '其他发布目录'}</small></button>${row.publish_name === state.selectedPublishedStage ? (row.libraries || []).map(item => `<button type="button" class="release-directory-component" aria-current="${state.publishedLibrary === item.library_id}" data-published-library="${escapeHtml(item.library_id || '')}">${escapeHtml(item.library_name || item.library_id)} · ${escapeHtml(item.base_full_version || item.version_id || '版本未登记')}</button>`).join('') : ''}`).join('') || `<p class="empty-note">${escapeHtml(state.formalReleaseError || (state.formalReleaseLoading ? '正在读取发布目录' : missingCount ? '现有目录的来源待登记，见右侧目录表。' : query ? '没有匹配的发布目录，请清除搜索条件。' : '尚无已登记发布目录，请核对发布根目录。'))}</p>`;
    $('library-list').querySelectorAll('[data-published-stage]').forEach(button => button.addEventListener('click', () => {
      state.selectedPublishedStage = button.dataset.publishedStage;
      state.publishedLibrary = '';
      state.publishedOffset = 0;
      $('published-view').value = ''; $('published-link-status').value = '';
      renderPublishedDirectory(); updateRouteState(); loadPublishedDetail();
    }));
    $('library-list').querySelectorAll('[data-published-library]').forEach(button => button.addEventListener('click', () => {
      selectPublishedFiles(button.dataset.publishedLibrary);
    }));
    const unregistered = state.formalReleaseSnapshot?.unregistered_deliveries || [];
    $('published-registration-panel').classList.toggle('hidden', !unregistered.length);
    $('published-unregistered').innerHTML = unregistered.map(item => `<tr><td>${escapeHtml(item.name)}</td><td><code>${escapeHtml(item.path)}</code></td><td>${escapeHtml((item.pointers || []).join('、') || '无')}</td><td><span class="status-chip status-warn">缺交付清单</span></td></tr>`).join('');
  }

  async function selectPublishedFiles(library = '', view = '') {
    state.publishedLibrary = library;
    state.publishedOffset = 0;
    state.publishedFileQuery = '';
    $('published-file-query').value = '';
    $('published-view').value = view;
    $('published-link-status').value = '';
    renderPublishedDirectory(); updateRouteState();
    await loadPublishedDetail();
    if (state.directoryMode === 'published') {
      $('published-file-workbench').scrollIntoView({block: 'start', behavior: 'smooth'});
      $('published-file-query').focus({preventScroll: true});
    }
  }

  async function loadPublishedDetail() {
    if (state.formalDirectoryMode) return;
    const id = ++state.publishedRequestId;
    $('published-update').disabled = true;
    if (state.publishedRenderedStage !== state.selectedPublishedStage || !$('published-components').innerHTML) {
      $('published-components').innerHTML = '<tr><td colspan="6">正在读取交付来源…</td></tr>';
    }
    $('published-files').innerHTML = '<tr><td colspan="4">正在核查交付文件…</td></tr>';
    $('published-previous').disabled = true;
    $('published-next').disabled = true;
    const stages = state.formalReleaseSnapshot?.stages || [];
    const row = stages.find(item => item.publish_name === state.selectedPublishedStage)
      || stages.find(item => item.is_latest) || stages[0];
    $('published-file-workbench').hidden = !row;
    if (row && state.selectedPublishedStage !== row.publish_name) {
      state.selectedPublishedStage = row.publish_name;
      state.publishedLibrary = ''; state.publishedOffset = 0;
      renderPublishedDirectory(); updateRouteState();
    }
    $('published-stage-title').textContent = row?.publish_name || '选择发布阶段';
    $('published-stage-meta').textContent = row?.path || state.formalReleaseSnapshot?.release_root || state.formalReleaseError || '尚未读取发布根目录';
    $('published-stage-summary').textContent = row ? '正在核查交付文件…' : '';
    $('published-file-count').textContent = '';
    $('published-check-scope').textContent = row ? '正在核查当前筛选范围…' : '';
    if (!row) {
      const missing = state.formalReleaseSnapshot?.unregistered_deliveries?.length || 0;
      $('published-stage-summary').textContent = missing ? `已有 ${missing} 个交付目录缺少清单，不能展示来源版本。` : '尚无已登记阶段交付';
      const message = escapeHtml(state.formalReleaseError || (missing ? '已有交付但缺少来源登记。补齐对应 release_manifest.json 后刷新，现有链接不会被修改。' : '暂无已发布阶段，请核对发布根目录并刷新发布目录。'));
      $('published-components').innerHTML = `<tr><td colspan="6">${message}</td></tr>`;
      $('published-view-inventory').innerHTML = '<tr><td colspan="5">视图统计未登记</td></tr>';
      $('published-files').innerHTML = `<tr><td colspan="4">${message}</td></tr>`;
      return;
    }
    try {
      const view = $('published-view').value || '';
      const linkStatus = $('published-link-status').value || '';
      const params = new URLSearchParams({query:state.publishedFileQuery, library:state.publishedLibrary, view, link_status:linkStatus, offset:state.publishedOffset, limit:100});
      const result = await getJson(`/api/release-stages/${encodeURIComponent(row.publish_name)}/files?${params}`);
      if (id !== state.publishedRequestId || state.directoryMode !== 'published') return;
      Object.assign(row, result.stage);
      state.publishedOffset = result.offset;
      renderPublishedDirectory();
      $('published-library-filter').innerHTML = '<option value="">全部库</option>' + (row.libraries || []).map(item => `<option value="${escapeHtml(item.library_id)}">${escapeHtml(item.library_id || item.library_name)}</option>`).join('');
      $('published-library-filter').value = state.publishedLibrary;
      $('published-view').innerHTML = '<option value="">全部类型</option>' + (result.views || []).map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
      $('published-view').value = view;
      const check = result.check;
      $('published-check-scope').textContent = check ? `本次核查 ${check.checked_count} / ${check.scope_count} 项 · 异常 ${check.abnormal_count} · ${check.complete ? '筛选范围已覆盖' : '仅当前页'}；未验证内容` : '仅核查当前页链接，不读取内容';
      if (row.skipped_count) $('published-check-scope').textContent += `；同名冲突跳过 ${row.skipped_count} 个文件，未交付`;
      const publishedDate = row.published_at ? new Date(row.published_at) : null;
      const publishedTime = publishedDate && !Number.isNaN(publishedDate.getTime()) ? publishedDate.toLocaleString('zh-CN', {timeZone:'Asia/Singapore',hour12:false}) + '（UTC+8）' : '未记录';
      $('published-stage-summary').innerHTML = `<span><strong>${row.library_count}</strong> 个库 · <strong>${row.file_count}</strong> 个交付文件</span><span class="status-chip status-neutral">当前交付指针 ${escapeHtml(row.latest_name)}：${row.is_latest ? '指向此目录' : '未指向此目录'}</span><span title="${escapeHtml(row.published_at || '')}">发布时间 ${escapeHtml(publishedTime)}</span>`;
      if (row.skipped_count) $('published-stage-summary').insertAdjacentHTML('beforeend', `<span class="status-chip status-warn">部分发布 · 同名跳过 ${row.skipped_count}</span>`);
      $('published-components').innerHTML = (result.inventory || row.libraries || []).map(item => {
        const source = state.libraries.find(lib => lib.library_id === item.library_id || lib.typed_library_id === item.library_id);
        const kind = source?.library_kind || source?.kind || '未分类';
        const actionNames = {LINK:'新建',REPLACE:'替换目标',KEEP:'保留',UNRECORDED:'无历史记录'};
        const actions = Object.entries(item.delivery_actions || {});
        item.overwrite_summary = actions.length === 1 && actions[0][0] === 'UNRECORDED' ? '覆盖历史未提供' : actions.map(([key, count]) => `${actionNames[key] || '未记录'} ${count}`).join(' / ');
        return `<tr><td><strong>${escapeHtml(item.library_name || item.library_id)}</strong><small>${escapeHtml(kind)}</small></td><td>${escapeHtml(item.base_full_version || '完整包未登记')}<small>修订包：${escapeHtml((item.accepted_updates || []).join(' + ') || '无')}</small><details><summary>组合编号</summary>${escapeHtml(item.version_id || '未记录')}</details></td><td><strong>${item.file_count ?? '未记录'}</strong><small>${escapeHtml((item.views || []).map(view => `${view.view} ${view.count}`).join(' / ') || '类型未记录')}</small></td><td title="${escapeHtml((item.corners || []).join(' / '))}"><div class="published-corner-values">${escapeHtml((item.corners || []).join(' / ') || '未提供')}</div>${item.corners?.length && item.corner_unrecorded ? `<small>另 ${item.corner_unrecorded} 个文件未提供</small>` : ''}</td><td>${escapeHtml(item.overwrite_summary || '覆盖历史未提供')}</td><td><div class="published-row-actions"><button type="button" class="button button-secondary button-small" data-delivery-library="${escapeHtml(item.library_id)}">查看文件</button>${source ? `<button type="button" class="button button-secondary button-small" data-open-source="${escapeHtml(source.library_name)}">源库</button>` : ''}</div></td></tr>`;
      }).join('') || '<tr><td colspan="6">交付清单未记录库与来源版本，不能根据文件路径推断。</td></tr>';
      $('published-components').querySelectorAll('[data-delivery-library]').forEach(button => button.addEventListener('click', () => {
        selectPublishedFiles(button.dataset.deliveryLibrary);
      }));
      $('published-view-inventory').innerHTML = (result.view_inventory || []).map(item => `<tr><td>${escapeHtml(item.view)}</td><td>${item.file_count}</td><td>${item.libraries.length}</td><td><div class="published-corner-values">${escapeHtml(item.corners.join(' / ') || '未提供')}</div></td><td><button type="button" class="button button-secondary button-small" data-delivery-view="${escapeHtml(item.view)}">查看文件</button></td></tr>`).join('') || '<tr><td colspan="5">视图统计未记录</td></tr>';
      $('published-view-inventory').querySelectorAll('[data-delivery-view]').forEach(button => button.addEventListener('click', () => {
        selectPublishedFiles('', button.dataset.deliveryView);
      }));
      state.publishedRenderedStage = row.publish_name;
      $('published-components').querySelectorAll('[data-open-source]').forEach(button => button.addEventListener('click', () => { setDirectoryMode('source'); selectLibrary(button.dataset.openSource); }));
      const labels = {READY:'目标一致', COPIED:'复制文件可读取，未核对内容', MISMATCH:'目标不一致', MISSING:'文件缺失 / 链接失效'};
      $('published-files').innerHTML = result.files.map((item, index) => `<tr><td><code>${escapeHtml(item.target_relpath)}</code><button type="button" class="button button-secondary button-small" data-copy-delivery-path="${index}">复制交付路径</button></td><td>${escapeHtml(item.library_id)}<small>原始版本：${escapeHtml(item.source_version || '未记录')}</small><small>发布组合：${escapeHtml(item.version_id || '未记录')}</small></td><td><code title="${escapeHtml(item.actual_target)}">${escapeHtml(item.actual_target)}</code><small>${item.is_symlink ? '符号链接' : '非链接文件'}</small>${['MISMATCH', 'MISSING'].includes(item.link_status) ? `<small>应指向：${escapeHtml(item.source_abs)}</small>` : ''}</td><td><span class="status-chip ${item.link_status === 'READY' ? 'status-good' : ['MISMATCH', 'MISSING'].includes(item.link_status) ? 'status-bad' : 'status-neutral'}">${labels[item.link_status] || '待核查'}</span></td></tr>`).join('') || '<tr><td colspan="4">没有符合条件的交付文件，请调整库筛选或搜索条件。</td></tr>';
      $('published-files').querySelectorAll('[data-copy-delivery-path]').forEach(button => button.addEventListener('click', async () => {
        button.textContent = await copyText(result.files[Number(button.dataset.copyDeliveryPath)].target_abs) ? '已复制' : '复制失败';
      }));
      $('published-file-count').textContent = `${state.publishedLibrary || '全部库'}${view ? ' · ' + view : ''}：${result.total ? `第 ${result.offset + 1}–${result.offset + result.files.length} 项 · 筛选命中 ${result.total} / 交付总数 ${row.file_count}` : '无匹配文件，请清除筛选重试'}`;
      $('published-previous').disabled = state.publishedOffset === 0;
      $('published-next').disabled = !result.has_more;
      $('published-update').disabled = Boolean(state.activeAction);
    } catch (error) {
      if (id === state.publishedRequestId && state.directoryMode === 'published') {
        const message = `交付读取失败：${error.message}`;
        $('published-stage-summary').textContent = message;
        $('published-components').innerHTML = `<tr><td colspan="6">${escapeHtml(message)}</td></tr>`;
        $('published-view-inventory').innerHTML = `<tr><td colspan="5">${escapeHtml(message)}</td></tr>`;
        $('published-files').innerHTML = `<tr><td colspan="4">${escapeHtml(message)}</td></tr>`;
      }
    }
  }

  function loadReleaseStageConfiguration(row) {
      $('release-set-publish-name').value = row.publish_name;
      $('release-set-latest-name').value = row.latest_name;
      $('release-set-acknowledged').checked = false;
      state.selectedReleaseSetLibraries.clear();
      const unmatched = [];
      (row.libraries || []).forEach(component => {
        const item = state.libraries.find(item => item.library_id === component.library_id || item.typed_library_id === component.library_id);
        if (item && releaseSetLibraryAvailable(item)) state.selectedReleaseSetLibraries.add(item.library_name);
        else unmatched.push(component.library_id || component.library_name);
      });
      state.releaseSetResultHtml = escapeHtml(unmatched.length ? `无法载入当前有效组合：${unmatched.join('、')}。请核对勾选，移出库会从本阶段交付移除。` : '已载入阶段配置；预演使用所选库现在的有效组合，不自动发布。');
      renderReleaseSetWorkbench();
  }

  function renderReleaseStages(snapshot) {
    const body = $('release-stage-body');
    if (!body) return;
    const query = state.formalReleaseQuery.trim().toLowerCase();
    const stages = (snapshot?.stages || []).filter(row => [row.publish_name, row.path, ...(row.libraries || []).map(item => item.library_id || item.library_name)].some(value => String(value || '').toLowerCase().includes(query)));
    body.innerHTML = state.formalReleaseLoading ? '<tr><td colspan="5">读取中…</td></tr>' : stages.map(row => `<tr>
      <td><strong>${escapeHtml(row.publish_name)}</strong><small>${escapeHtml(row.path)}</small></td>
      <td>${Number(row.library_count || 0)} 库 / ${Number(row.file_count || 0)} 文件<details><summary>库与来源版本</summary>${(row.libraries || []).map(item => `<p>${escapeHtml(item.library_id || item.library_name)} / ${escapeHtml(item.version_id || '未记录')}</p>`).join('')}</details></td>
      <td>${escapeHtml(row.latest_name)}：${row.is_latest ? '指向本阶段' : '未指向本阶段'}</td>
      <td>${Number(row.broken_links || 0) ? `失效 ${Number(row.broken_links)} 个` : '链接可读取'}${row.skipped_count ? `<small class="status-warn">部分发布 · 同名跳过 ${Number(row.skipped_count)}</small>` : ''}</td>
      <td><button type="button" class="button button-secondary button-small" data-release-stage="${escapeHtml(row.publish_name)}">载入阶段配置</button></td></tr>`).join('') || '<tr><td colspan="5">尚无符合筛选的阶段交付；先实际发布或刷新目录。</td></tr>';
    body.querySelectorAll('[data-release-stage]').forEach(button => button.addEventListener('click', () => {
      if (state.activeAction) return;
      const row = snapshot.stages.find(item => item.publish_name === button.dataset.releaseStage);
      loadReleaseStageConfiguration(row);
    }));
  }

  async function loadFormalReleaseLibraries() {
    state.formalReleaseLoading = true;
    state.formalReleaseError = '';
    renderFormalReleaseLibraries();
    try {
      const snapshot = await getJson('/api/release-libraries');
      state.formalReleaseSnapshot = snapshot;
      state.formalReleaseLibraries = Array.isArray(snapshot.libraries) ? snapshot.libraries : [];
      await loadFormalInventory();
    } catch (error) {
      state.formalReleaseSnapshot = null;
      state.formalReleaseLibraries = [];
      state.formalReleaseError = `读取正式发布库失败：${error.message}`;
    } finally {
      state.formalReleaseLoading = false;
      renderFormalReleaseLibraries();
      if (state.directoryMode === 'published') { renderPublishedDirectory(); loadPublishedDetail(); }
    }
  }

  async function refreshFormalReleaseLibraries() {
    if (state.formalReleaseLoading || state.activeAction) return;
    state.formalReleaseLoading = true;
    state.formalReleaseError = '';
    renderFormalReleaseLibraries();
    try {
      const result = await getJson('/api/release-libraries/refresh', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: $('formal-release-root').value.trim() }),
      });
      $('formal-release-root').value = result.release_root || $('formal-release-root').value;
      state.formalReleaseLoading = false;
      await loadFormalReleaseLibraries();
    } catch (error) {
      state.formalReleaseLoading = false;
      state.formalReleaseError = `刷新正式发布库失败：${error.message}`;
      renderFormalReleaseLibraries();
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

  function renderDefaultSettings() {
    const settings = state.workspace?.scan_strategy || {};
    const paths = state.workspace?.paths || {};
    const release = state.workspace?.release_settings || {};
    const discovery = state.workspace?.discovery_strategy || {};
    for (const kind of ['force', 'skip']) {
      const container = $(`default-${kind}-hash-types`);
      if (!container.children.length) container.innerHTML = Array.from(document.querySelectorAll(`[data-${kind}-hash-type]`)).map(input =>
        `<label class="toggle-field"><input type="checkbox" value="${escapeHtml(input.value)}" data-default-${kind}-hash-type>${escapeHtml(input.parentElement.textContent.trim())}</label>`).join('');
    }
    for (const key of ['raw_root', 'release_root']) $(`config-${key.replaceAll('_', '-')}`).value = paths[key] || '';
    $('config-release-publish-name').value = release.publish_name || '';
    $('config-release-latest-name').value = release.latest_name || 'latest';
    $('config-hash-policy').value = settings.hash_policy || 'smart';
    $('config-parse-jobs').value = String(settings.parse_jobs || 8);
    for (const key of ['parse_file_types', 'parse_exclude_file_types']) $(`config-${key.replaceAll('_', '-')}`).value = settings[key] || '';
    setHashTypeChecks('[data-default-force-hash-type]', settings.force_hash_file_types || '');
    setHashTypeChecks('[data-default-skip-hash-type]', settings.skip_hash_file_types || '');
    $('config-render-detail').checked = settings.render_detail !== false;
    for (const [key, fallback] of Object.entries({max_depth: 4, min_versions: 1, max_dirs: 5000, max_candidates: 200})) {
      $(`config-discover-${key.replaceAll('_', '-')}`).value = String(discovery[key] || fallback);
    }
  }

  function workspaceConfigPayload(group = 'directories') {
    if (group === 'directories') return {
      raw_root: $('config-raw-root')?.value.trim() || '',
      release_root: $('config-release-root')?.value.trim() || '',
      release_publish_name: $('config-release-publish-name')?.value.trim() || '',
      release_latest_name: $('config-release-latest-name')?.value.trim() || 'latest',
    };
    if (group === 'scan') return {
      parse_jobs: $('config-parse-jobs').value,
      hash_policy: $('config-hash-policy').value,
      force_hash_file_types: Array.from(document.querySelectorAll('[data-default-force-hash-type]:checked')).map((input) => input.value),
      skip_hash_file_types: Array.from(document.querySelectorAll('[data-default-skip-hash-type]:checked')).map((input) => input.value),
      parse_file_types: $('config-parse-file-types').value.trim(),
      parse_exclude_file_types: $('config-parse-exclude-file-types').value.trim(),
      render_detail: $('config-render-detail').checked,
    };
    if (group !== 'discovery') throw new Error('未知配置分组');
    return {
      discover_max_depth: $('config-discover-max-depth').value,
      discover_min_versions: $('config-discover-min-versions').value,
      discover_max_dirs: $('config-discover-max-dirs').value,
      discover_max_candidates: $('config-discover-max-candidates').value,
    };
  }

  function showSettingsFeedback(message = '', kind = 'info') {
    const feedback = $('settings-save-feedback');
    if (!feedback) return;
    feedback.textContent = message;
    feedback.classList.toggle('hidden', !message);
    feedback.classList.toggle('is-error', kind === 'error');
  }

  async function saveWorkspaceSettings(group = 'directories') {
    if (state.settingsSaving) return;
    state.settingsSaving = true;
    const button = $(group === 'directories' ? 'save-settings' : `save-${group}-settings`);
    if (button) button.disabled = true;
    showSettingsFeedback('正在保存工作区默认配置…');
    try {
      const payload = await getJson('/api/workspace/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(workspaceConfigPayload(group)),
      });
      state.workspace = { ...(state.workspace || {}), paths: payload.paths, scan_strategy: payload.scan_strategy, discovery_strategy: payload.discovery_strategy, release_settings: payload.release_settings };
      if (group === 'directories') {
        $('release-root-display').value = payload.paths.release_root || '未配置';
        invalidateReleasePreview();
      }
      showSettingsFeedback(`已保存${{directories: '目录', scan: '扫描默认值', discovery: '发现默认值'}[group]}；本次任务参数保持不变。备份：${payload.backup || '已生成'}`);
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
    // A catalog reload keeps the same version-focused results visible. Only a
    // real version switch invalidates file evidence, notes, and release preview.
    if (selectedChanged) resetSelectedVersionEvidence();
    renderVersions();
    renderVersionFacts();
    if (!append || selectedChanged) {
      await refreshActiveEvidenceForSelectedVersion(requestId);
      await loadUpdateNoteForSelectedVersion();
      await loadRepresentativeFiles();
    }
  }

  async function selectLibrary(name) {
    // Reloading the currently selected library must keep its version context.
    // Jobs use this path after completion, so clearing here would hide the
    // just-produced release preview and other current-version projections.
    if (name === state.selectedLibrary && state.versions.length) {
      await refreshVersionsForSelectedLibrary(++state.libraryRequestId);
      return loadSemanticReviewOptions();
    }
    if (state.formalReleaseTarget && (state.formalReleaseTarget.raw_catalog_name || state.formalReleaseTarget.raw_catalog_match) !== name) {
      state.formalReleaseTarget = null;
      $('release-overwrite').checked = true;
      $('release-overwrite-target').textContent = '已切换到其他库；覆盖目标已清除。';
    }
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
      state.versionFilter = 'focus';
      $('version-filter').value = '';
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
      await loadSemanticReviewOptions();
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
    loadUpdateNoteForSelectedVersion().catch(() => {});
    loadRepresentativeFiles().catch((error) => { $('representative-feedback').textContent = `读取核查记录失败：${error.message}`; });
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
        $('selected-library').textContent = '选择一个已登记库';
        $('selected-library-crumb').textContent = '未选择';
        $('selected-library-meta').textContent = '目录中没有可查看的已登记库。';
        renderMetrics(null);
        renderVersions();
        renderVersionFacts();
        await loadSemanticReviewOptions();
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
    renderWorkspaceSetup();
    if (state.workspace?.setup_required) {
      setWorkflowStatus('未初始化', 'status-warn');
    } else {
      setWorkflowStatus('CONNECTED', 'status-good');
    }
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
    renderEffectiveSelection();
    renderSemanticReviewReadiness();
  }

  function clearActionBusy() {
    state.activeAction = null;
    document.querySelectorAll('[data-action], [data-workflow-action], [data-correction-action], [data-command-action]').forEach((button) => button.classList.remove('is-busy'));
    renderVersionFacts();
    renderLibraryCandidates();
    renderSemanticReviewReadiness();
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
    if (['release-plan', 'release-apply'].includes(action)) return {
      alias: $('release-alias').value,
      publish_name: $('release-publish-name').value.trim(),
      latest_name: $('release-latest-name').value.trim(),
      link_mode: $('release-link-mode').value,
      overwrite: $('release-overwrite').checked,
    };
    if (action === 'release-force') return {
      alias: $('release-alias').value,
      publish_name: $('release-publish-name').value.trim(),
      latest_name: $('release-latest-name').value.trim(),
      link_mode: $('release-link-mode').value,
      force_by: $('release-force-by').value.trim(),
      force_reason: $('release-force-reason').value.trim(),
      acknowledged: $('release-force-acknowledged').checked,
    };
    return {};
  }

  function releasePreviewKey() {
    return JSON.stringify([state.selectedLibrary, state.selectedVersion?.version_id,
      $('release-root-display').value, state.formalReleaseTarget?.library_id || '', actionPayload('release-plan')]);
  }

  function releasePreviewReady() {
    const plan = state.releasePlan;
    return Boolean(plan?.dry_run && ['DRY_RUN', 'PARTIAL_DRY_RUN'].includes(plan.status)
      && plan.library === state.selectedLibrary && plan.version === state.selectedVersion?.version_id
      && state.releasePreviewKey === releasePreviewKey());
  }

  function invalidateReleasePreview() {
    const stale = Boolean(state.releasePlan?.dry_run && state.releasePreviewKey && state.releasePreviewKey !== releasePreviewKey());
    $('release-preview-stale').classList.toggle('hidden', !stale);
    const ready = releasePreviewReady();
    $('release-apply-action-button').classList.toggle('hidden', !ready);
    $('release-apply-action-button').disabled = !ready || Boolean(state.activeAction);
    return stale;
  }

  function webActionSpec(action) {
    return state.workspace?.web_actions?.[action] || {};
  }

  function commandLabel(action) {
    const labels = {
      compare: '对比',
      'next-preview': '处理建议',
      'next-apply': '处理建议',
      'intake-preview': '处理计划',
      'intake-apply': '处理计划',
    };
    return webActionSpec(action).label || labels[action] || action;
  }

  function actionLabel(action) {
    return commandLabel(action === 'compare' ? 'cmp' : action === 'release-check' ? 'rel' : action);
  }

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
    if (webActionSpec(action).requires_confirmation === true) return true;
    if (action === 'review-gate') return ['accept', 'waive'].includes($('review-gate-operation').value);
    if (action === 'review-packet') return $('review-packet-operation').value === 'submit';
    return false;
  }

  function commandConfirmation(action) {
    if (action === 'library-add') {
      const id = $('library-add-id').value.trim();
      const root = $('library-add-root').value.trim();
      const existing = state.libraries.find((item) => item.library_name === id || item.library_id === id);
      return existing
        ? `修改已登记库：${id}\n原库根：${existing.root_abs || existing.root_display || '未记录'}\n新库根：${root}\n将更新登记并刷新该库目录，不扫描、不切换当前有效组合。是否继续？`
        : `登记新库：${id}\n库根：${root}\n将登记并刷新目录，不扫描、不切换当前有效组合。是否继续？`;
    }
    if (action === 'effective-rollback') {
      const current = currentEffectiveStack();
      return `回退当前有效组合\n库：${state.selectedLibrary}\n当前：${current.current_effective_id || '未设置'}\n目标：${$('rollback-to').value}\n回退人：${$('rollback-by').value.trim()}\n原因：${$('rollback-reason').value.trim()}\n不修改原始文件或发布链接。是否继续？`;
    }
    const configured = webActionSpec(action).confirmation;
    if (configured) return configured;
    if (action === 'library-accept') return `即将登记已勾选的 ${state.selectedCandidateIds.size} 个候选库，并自动刷新已登记库列表。原始候选快照不会被改写。是否继续？`;
    return `即将执行${commandLabel(action)}，结果会写入工作区运行记录。是否继续？`;
  }

  async function runCommand(action) {
    const endpoint = commandEndpoint(action);
    if (!endpoint || state.activeAction) return;
    if (action === 'library-add') showLibraryAddFeedback();
    if (action === 'library-accept' && state.selectedCandidateIds.size === 0) {
      showError('请先在候选库表中勾选至少一个确认的库根。', { action: true });
      return;
    }
    if (action === 'effective-rollback' && (!$('rollback-to').value || !$('rollback-by').value.trim() || !$('rollback-reason').value.trim())) {
      showError('请先选择已保存组合，并填写回退人和原因。', { action: true });
      return;
    }
    if (commandNeedsConfirmation(action) && !window.confirm(commandConfirmation(action))) return;
    const payload = commandPayload(action);
    setActionBusy(action);
    try {
      const result = await getJson(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      await startJob(result, commandLabel(action), null, action, {
        registeredLibrary: action === 'library-add' ? payload.library_id : '',
      });
    } catch (error) {
      clearActionBusy();
      if (action === 'library-add') showLibraryAddFeedback(error.message);
      showError(`${commandLabel(action)}失败：${error.message}`, { action: true });
    }
  }

  function releaseSetSelectedLibraries() {
    const available = new Set(state.libraries.filter(releaseSetLibraryAvailable).map((item) => item.library_name));
    return Array.from(state.selectedReleaseSetLibraries).filter((name) => available.has(name));
  }

  function releaseSetSummaryText(manifest) {
    const summary = manifest?.summary || {};
    const libraries = Number(summary.library_count || 0);
    const missing = Number(summary.missing_current_effective || 0);
    return `清单 ${manifest?.set_id || '未命名'} 已生成，尚未发布：${libraries} 个库，缺少当前有效组合 ${missing} 个。`;
  }

  async function buildReleaseSet() {
    if (state.activeAction) return;
    const libraries = releaseSetSelectedLibraries();
    if (!libraries.length) {
      state.releaseSetResultHtml = '请先勾选至少一个已有当前有效组合的库。';
      renderReleaseSetWorkbench();
      return;
    }
    state.activeAction = 'release-set-build';
    state.releaseSetResultHtml = '正在生成多库组合清单…';
    renderReleaseSetWorkbench();
    try {
      const payload = await getJson('/api/release-set/build', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          libraries,
          set_id: $('release-set-id').value.trim(),
          note: $('release-set-note').value.trim(),
        }),
      });
      state.releaseSetLastManifest = payload.manifest_path || '';
      state.releaseSetResultHtml = `${escapeHtml(releaseSetSummaryText(payload.manifest))}<br><code>${escapeHtml(payload.manifest_path || '')}</code>`;
      if ($('release-set-new-manifest') && payload.manifest_path) $('release-set-new-manifest').value = payload.manifest_path;
    } catch (error) {
      state.releaseSetResultHtml = escapeHtml(`生成多库组合清单失败：${error.message}`);
      showError(`生成多库组合清单失败：${error.message}`, { action: true });
    } finally {
      state.activeAction = null;
      renderReleaseSetWorkbench();
    }
  }

  function releaseSetCompareText(compare) {
    const summary = compare?.summary || {};
    const actions = summary.actions || {};
    const parts = [
      `组合变化库 ${Number(summary.changed_libraries || 0)}`,
      `新增 ${Number(actions.ADD_LIBRARY || 0)}`,
      `移出清单 ${Number(actions.REMOVE_LIBRARY || 0)}`,
      `组合变化 ${Number(actions.CHANGE_EFFECTIVE || 0)}`,
      `保持 ${Number(actions.KEEP_LIBRARY || 0)}`,
    ];
    return `${parts.join(' / ')}。只做库级摘要比较；变化库再下钻到版本详情。`;
  }

  function releaseSetCompareHtml(compare, resultPath) {
    const labels = { ADD_LIBRARY: '新增库', REMOVE_LIBRARY: '移出清单', CHANGE_EFFECTIVE: '组合变化', KEEP_LIBRARY: '保持' };
    const rows = Array.isArray(compare?.libraries) ? compare.libraries : [];
    const table = rows.length
      ? `<div class="release-set-compare-wrap" tabindex="0" aria-label="多库组合对比明细"><table><caption class="sr-only">多库组合对比明细</caption><thead><tr><th>库</th><th>变化</th><th>旧组合</th><th>新组合</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${escapeHtml(row.library_id || '未命名')}</td><td>${escapeHtml(labels[row.action] || '待核查')}</td><td>${escapeHtml(row.old_effective_id || '—')}</td><td>${escapeHtml(row.new_effective_id || '—')}</td></tr>`).join('')}</tbody></table></div>`
      : '<p>没有库级对比明细。</p>';
    const evidence = resultPath ? `<details><summary>结果文件</summary><code title="${escapeHtml(resultPath)}">${escapeHtml(resultPath)}</code></details>` : '';
    return `<p>${escapeHtml(releaseSetCompareText(compare))}</p>${table}${evidence}`;
  }

  async function compareReleaseSet() {
    if (state.activeAction) return;
    const oldManifest = $('release-set-old-manifest').value.trim();
    const newManifest = $('release-set-new-manifest').value.trim();
    if (!oldManifest || !newManifest) {
      state.releaseSetResultHtml = '请填写旧组合清单和新组合清单路径。';
      renderReleaseSetWorkbench();
      return;
    }
    state.activeAction = 'release-set-compare';
    state.releaseSetResultHtml = '正在比较两个组合清单…';
    renderReleaseSetWorkbench();
    try {
      const payload = await getJson('/api/release-set/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_manifest: oldManifest, new_manifest: newManifest }),
      });
      state.releaseSetResultHtml = releaseSetCompareHtml(payload.compare, payload.compare_path || '');
    } catch (error) {
      state.releaseSetResultHtml = escapeHtml(`比较两个组合清单失败：${error.message}`);
      showError(`比较两个组合清单失败：${error.message}`, { action: true });
    } finally {
      state.activeAction = null;
      renderReleaseSetWorkbench();
    }
  }

  async function runReleaseSet(apply) {
    if (state.activeAction) return;
    const libraries = releaseSetSelectedLibraries();
    const publish_name = $('release-set-publish-name').value.trim();
    const latest_name = $('release-set-latest-name').value.trim();
    if (!libraries.length || !publish_name || !latest_name) {
      state.releaseSetResultHtml = '请勾选库，并填写阶段目录和最新指针名。';
      renderReleaseSetWorkbench();
      return;
    }
    if (apply && !$('release-set-acknowledged').checked) return;
    const action = apply ? 'release-set-apply' : 'release-set-plan';
    setActionBusy(action);
    renderReleaseSetWorkbench();
    try {
      const result = await getJson(`/api/release-set/${apply ? 'apply' : 'plan'}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({libraries,publish_name,latest_name,acknowledged:apply})});
      await startJob(result, apply ? '多库实际发布' : '多库发布预演', null, action);
    } catch (error) {
      clearActionBusy();
      state.releaseSetResultHtml = escapeHtml(`多库发布未执行：${error.message}`);
      renderReleaseSetWorkbench();
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
    const target = action === 'accept-window' ? `设为当前有效版本：${candidate || '未生成'}` : action === 'intake-apply' ? '执行完整处理计划' : '按处理建议执行';
    const composition = (stack) => `${stack?.base_full_version || '未设置'} + ${(stack?.accepted_updates || []).join(' + ') || '无叠加更新'}`;
    const current = library?.current_effective_stack || {};
    const next = library?.pending_window?.candidate_effective_stack || {};
    const detail = action === 'accept-window'
      ? `当前组合：${current.current_effective_id || '未设置'}\n当前组成：${composition(current)}\n候选组合：${candidate || '未生成'}\n候选组成：${composition(next)}\n确认人：${$('accepted-by').value.trim() || '未填写'}\n确认说明：${$('accept-note').value.trim() || '未填写'}\n只切换当前有效组合，不创建发布链接。`
      : `所选完整包：${effectiveSelectionDraft()?.base_full || '未设置'}\n叠加顺序：${(effectiveSelectionDraft()?.includes || []).join(' → ') || '无叠加更新'}\n按已预览策略执行扫描、组合和对比，不切换当前有效组合，不创建发布链接。`;
    return `即将${target}\n库：${state.selectedLibrary}\n${detail}\n是否继续？`;
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
    $('run-workspace')?.classList.add('has-live-job');
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
    if (logDetails && terminal) logDetails.open = false;
    $('job-log-size').textContent = `原文 ${formatBytes(result.log_bytes)}，已显示 ${formatBytes((result.log_tail || '').length)}`;
  }

  function renderJobArtifacts(artifacts = []) {
    const container = $('job-artifacts');
    if (!container) return;
    const rows = Array.isArray(artifacts) ? artifacts.filter((item) => item && item.url && item.label) : [];
    container.classList.toggle('hidden', rows.length === 0);
    if (!rows.length) {
      container.innerHTML = '';
      return;
    }
    container.innerHTML = `<strong>运行产物</strong>${rows.map((item) => {
      const suffix = item.kind === 'html' ? ' ↗' : '';
      const mode = item.download ? 'download' : 'target="_blank" rel="noreferrer"';
      return `<a href="${escapeHtml(item.url)}" ${mode} title="${escapeHtml(item.path || '')}">${escapeHtml(item.label)}${suffix}</a>`;
    }).join('')}`;
  }

  function renderJobQualitySummary(summary = null) {
    const container = $('job-quality-summary');
    if (!container) return;
    if (!summary || !summary.verdict) {
      container.classList.add('hidden');
      return;
    }
    const verdictClass = summary.verdict === 'PASS'
      ? 'status-good'
      : ['FAIL'].includes(summary.verdict)
        ? 'status-bad'
        : ['INCOMPLETE', 'REVIEW_REQUIRED'].includes(summary.verdict)
          ? 'status-warn'
          : 'status-neutral';
    const labels = {PASS: '通过', REVIEW_REQUIRED: '需人工确认', INCOMPLETE: '未完成', NOT_CHECKED: '未检查', UNKNOWN: '无法判定', FAIL: '发现问题', CHANGED: '有变化', UNCHANGED: '无变化', NOT_APPLICABLE: '不适用'};
    const counts = summary.counts || {};
    const countOrder = ['PASS', 'REVIEW_REQUIRED', 'INCOMPLETE', 'NOT_CHECKED', 'UNKNOWN', 'FAIL', 'CHANGED', 'UNCHANGED', 'NOT_APPLICABLE'];
    const countRows = countOrder.filter((key) => Number(counts[key] || 0) > 0);
    $('job-quality-verdict').className = `status-chip ${verdictClass}`;
    $('job-quality-verdict').textContent = summary.verdict_label || '未形成结论';
    $('job-quality-counts').innerHTML = countRows.length
      ? countRows.map((key) => `<span>${labels[key] || escapeHtml(key)} ${Number(counts[key])}</span>`).join('')
      : '<span>暂无可展示的检查项结果</span>';
    const coverage = summary.coverage || {};
    $('job-quality-coverage').textContent = `检查范围：已选 ${Number(coverage.selected_files || 0)} / 交付文件 ${Number(coverage.effective_files || 0)}；${summary.base_selected ? '已选择变化基准。' : '未选择变化基准。'}`;
    $('job-quality-next').textContent = `下一步：${summary.next_action || '查看报告文件。'}`;
    $('job-quality-note').textContent = summary.note || '任务完成不等于质量通过。';
    container.classList.remove('hidden');
  }

  async function startJob(result, label, workflowAction = null, commandAction = null, context = {}) {
    state.activeJob = { label, workflowAction, commandAction, ...context };
    state.pollStartedAt = Date.now();
    state.pollInFlight = false;
    $('job-status').textContent = statusLabel(result.status);
    $('job-status').className = `status-chip ${statusClass(result.status)}`;
    $('job-summary').textContent = `${label}已提交，任务 ${result.job_id} 正在等待运行结果。`;
    $('run-workspace')?.classList.add('has-live-job');
    if ($('run-workspace')) $('run-workspace').open = true;
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
    renderJobQualitySummary(null);
    renderJobArtifacts([]);
    if (state.pollTimer) clearInterval(state.pollTimer);
    const completion = new Promise((resolve, reject) => { state.jobWaiter = { resolve, reject }; });
    state.pollTimer = setInterval(() => pollJob(result.job_id), 1000);
    await pollJob(result.job_id);
    return completion;
  }

  async function runAction(action, payloadOverrides = null) {
    if (!state.selectedLibrary || !state.selectedVersion || state.activeAction) return;
    const payload = { ...actionPayload(action), ...(payloadOverrides || {}) };
    if (action === 'release-apply') {
      if (!releasePreviewReady()) {
        invalidateReleasePreview();
        showError('请先为当前版本和当前发布设置生成有效预演，核对结果后再创建链接。', { action: true });
        return null;
      }
      const layout = payload.publish_name ? `正式目录：${payload.publish_name}\n最新指针：${payload.latest_name || 'latest'}\n覆盖前备份：history/${payload.publish_name}_日期（同日覆盖）` : `发布别名：${payload.alias}`;
      const message = `实际发布：${state.selectedLibrary} / ${state.selectedVersion.version_id}\n目标：${$('release-root-display').value}\n${layout}\n方式：${payload.link_mode}\n允许覆盖：${payload.publish_name || payload.overwrite ? '是' : '否'}\n将创建交付文件并更新发布入口；不会跳过门禁或校验。是否继续？`;
      if (!window.confirm(message)) return null;
      payload.acknowledged = true;
    }
    const version = state.selectedVersion.version_id;
    let requestAction = action;
    let url = `/api/libraries/${encodeURIComponent(state.selectedLibrary)}/versions/${encodeURIComponent(version)}/${action}`;
    if (action === 'release-plan' && state.formalReleaseTarget) {
      payload.overwrite = true;
      requestAction = 'release-overwrite-preview';
      url = `/api/release-libraries/${encodeURIComponent(state.formalReleaseTarget.library_id)}/versions/${encodeURIComponent(version)}/preview-overwrite`;
    }
    if (action === 'release-force') {
      if (!state.formalReleaseTarget) throw new Error('请先在正式发布库列表选择覆盖目标');
      requestAction = 'release-force';
      url = `/api/release-libraries/${encodeURIComponent(state.formalReleaseTarget.library_id)}/versions/${encodeURIComponent(version)}/force-overwrite`;
    }
    setActionBusy(action);
    const previewKey = releasePreviewKey();
    try {
      const result = await getJson(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      return await startJob(result, actionLabel(action), null, requestAction, {previewKey});
    } catch (error) {
      clearActionBusy();
      showError(`${actionLabel(action)}失败：${error.message}`, { action: true });
      return null;
    }
  }

  function workflowRequest(action) {
    if (action === 'accept-window') return { accepted_by: $('accepted-by').value.trim(), note: $('accept-note').value.trim(), expected_effective_id: selectedLibraryRow()?.pending_window?.candidate_effective_id || '' };
    if (action === 'window') return {};
    const draft = effectiveSelectionDraft();
    const common = { ...strategyPayload(), since: $('since-version').value.trim(), rebuild: $('rebuild-workflow').checked,
      base_full: draft?.base_full || '', includes: [...(draft?.includes || [])] };
    if (action === 'next-preview') return { ...common, plan_only: true };
    if (action === 'next-apply') return { ...draft.preview.payload, includes: [...draft.preview.payload.includes], apply: true, plan_only: false };
    if (action === 'intake-preview') return { ...common, plan_only: true };
    if (action === 'intake-apply') return { ...draft.preview.payload, includes: [...draft.preview.payload.includes], plan_only: false };
    return {};
  }

  async function runWorkflow(action) {
    if (!state.selectedLibrary || state.activeAction) return;
    const hasEdits = action.endsWith('-preview') && effectiveVersionEdits().size > 0;
    const writeAction = ['next-apply', 'intake-apply', 'accept-window'].includes(action);
    const draft = effectiveSelectionDraft();
    const endpoint = action.split('-')[0];
    if ((['next-apply', 'intake-apply'].includes(action) && !effectiveSelectionPreviewReady(draft, endpoint))
      || (['next-preview', 'intake-preview'].includes(action) && !draft?.base_full)
      || (action === 'accept-window' && !effectiveSelectionMatchesCandidate(draft, selectedLibraryRow()?.pending_window?.candidate_effective_stack))) {
      $('workflow-summary').textContent = '所选组合尚未预览或与候选不一致，请重新预览并生成候选。';
      return;
    }
    if (action === 'accept-window' && !$('accepted-by').value.trim()) {
      setWorkflowStatus('FAILED', 'status-bad');
      $('workflow-summary').textContent = '确认当前有效版本前必须填写确认人。';
      return;
    }
    if (writeAction && !window.confirm(writeConfirmation(action))) return;
    const endpointAction = action === 'next-preview' || action === 'next-apply' ? 'next' : action === 'intake-preview' || action === 'intake-apply' ? 'intake' : action;
    const payload = workflowRequest(action);
    const libraryName = state.selectedLibrary;
    const selectionKey = draft && effectiveSelectionKey(draft);
    if (action.endsWith('-preview')) draft.preview = null;
    setActionBusy(action);
    try {
      if (hasEdits) await saveEffectiveVersionEdits(libraryName);
      setActionBusy(action);
      const result = await getJson(`/api/libraries/${encodeURIComponent(state.selectedLibrary)}/${endpointAction}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      setWorkflowStatus(result.status, statusClass(result.status));
      $('workflow-summary').textContent = `${endpointAction === 'window' ? '读取已保存建议' : ['next-preview', 'intake-preview'].includes(action) ? '预览处理计划' : action === 'accept-window' ? '确认当前有效版本' : '执行并生成候选'}已提交。详情将在运行记录中更新。`;
      const completed = await startJob(result, endpointAction === 'next' ? '处理建议' : endpointAction === 'intake' ? '处理计划' : endpointAction === 'accept-window' ? '确认当前有效版本' : '查看建议', action);
      if (completed?.return_code === 0 && action.endsWith('-preview') && effectiveSelectionKey(draft) === selectionKey) {
        draft.preview = {key: selectionKey, endpoint: endpointAction, payload: {...payload, includes: [...payload.includes]}};
      }
      if (libraryName === state.selectedLibrary) {
        const workflowSummary = completed?.workflow_summary || completed?.result_summary;
        if (workflowSummary) $('workflow-summary').textContent = typeof workflowSummary === 'string' ? workflowSummary : JSON.stringify(workflowSummary);
        renderVersionFacts();
      }
    } catch (error) {
      clearActionBusy();
      setWorkflowStatus('FAILED', 'status-bad');
      $('workflow-summary').textContent = error.message;
    }
  }

  function workflowSuccessMessage(action) {
    const messages = {
      'next-preview': '计划预览已完成。核对运行记录中的基线与更新包，再点击“执行并生成候选”。',
      'intake-preview': '完整计划预览已完成。核对计划后，可在高级计划设置中执行完整计划。',
      'next-apply': '处理建议已执行，工作区状态已重新读取。候选组合生成后，可继续核对或确认当前有效版本。',
      'intake-apply': '处理计划已执行，工作区状态已重新读取。候选组合生成后，可继续核对或确认当前有效版本。',
      window: '已读取接入建议，页面已重新读取候选组合和当前有效版本。',
      'accept-window': '当前有效版本已确认，页面已重新读取有效组合。',
    };
    return messages[action] || '库级流程已完成，工作区状态已重新读取。';
  }

  async function runCorrection(action) {
    if (!state.selectedLibrary || !state.selectedVersion || state.activeAction) return;
    if (!window.confirm('这一步会修改目录中的人工确认信息，是否继续？')) return;
    const version = state.selectedVersion.version_id;
    const payload = action === 'mark'
      ? { type: $('mark-type').value, note: $('override-note').value.trim() }
      : { stage: $('stage').value, compare_default: $('compare-default').value, note: $('override-note').value.trim() };
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
      renderJobQualitySummary(result.quality_summary || null);
      renderJobArtifacts(result.artifacts || []);
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
      if ((terminal || elapsed >= JOB_TIMEOUT_MS) && state.pollTimer) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        const completedJob = state.activeJob;
        if (completedJob?.commandAction === 'file-diff') {
          representativeCandidate = {...(result.file_diff_review || {}), job_id:jobId};
          $('representative-feedback').textContent = representativeCandidate.eligible ? `${fileTypeLabel(representativeCandidate.file_type)} 对比已完成；保存后替换该类型的当前核查结果。` : '此任务未产生可保存的对比结果，请先核对日志。';
          updateRepresentativeButton();
        }
        state.activeJob = null;
        if (['release-plan', 'release-overwrite-preview', 'release-force', 'release-apply', 'release-set-plan', 'release-set-apply'].includes(completedJob?.commandAction)) {
          state.releasePlan = result.release_plan || null;
          state.releasePreviewKey = completedJob.previewKey || '';
          renderReleasePlanResult();
          invalidateReleasePreview();
        }
        if (completedJob?.workflowAction) {
          setWorkflowStatus(elapsed >= JOB_TIMEOUT_MS && !terminal ? 'RUNNING' : result.status, statusClass(result.status));
          $('workflow-summary').textContent = result.return_code === 0
            ? workflowSuccessMessage(completedJob.workflowAction)
            : elapsed >= JOB_TIMEOUT_MS && !terminal
              ? `${completedJob.label}运行时间过长，已停止页面轮询，请查看日志。`
              : `${completedJob.label}未成功完成，请查看最近运行中的日志和返回码。`;
        }
        clearActionBusy();
        if (terminal) {
          await loadLibraries(result.return_code === 0 ? completedJob?.registeredLibrary : '');
          if (['release-apply', 'release-force', 'release-set-apply'].includes(completedJob?.commandAction) && result.return_code === 0) await refreshFormalReleaseLibraries();
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
    if (state.directoryMode === 'published') { state.publishedQuery = event.target.value; renderPublishedDirectory(); return; }
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
  $('version-sort').addEventListener('change', (event) => { state.versionSort = event.target.value; state.versionRenderLimit = VERSION_RENDER_BATCH; updateRouteState(); renderVersions(); renderVersionFacts(); });
  document.querySelectorAll('[data-version-focus-action]').forEach((button) => button.addEventListener('click', () => {
    const action = button.dataset.versionFocusAction;
    if (action === 'open') openVersionDetail();
    if (action === 'next') {
      const next = versionPrimaryAction(state.selectedVersion);
      if (next.kind === 'scan' || next.kind === 'compare') runAction(next.kind);
      if (next.kind === 'open') openVersionDetail();
      if (next.kind === 'settings') setActiveStageTab('management-workspace');
      if (next.kind === 'analysis') {
        setActiveStageTab('action-workspace');
        selectAnalysisAction('review');
      }
    }
  }));
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
    renderVersionFacts();
  });
  $('rescan').addEventListener('change', () => {
    if ($('rescan').checked) $('scan-if-missing').checked = false;
    updateSettingsSummary();
    renderVersionFacts();
  });
  let fileChangeFilterTimer = null;
  $('reset-file-tree-filters').addEventListener('click', () => {
    $('file-tree-filter').value = '';
    $('file-tree-type-filter').value = 'all';
    renderFileTree();
  });
  $('reset-file-change-filters').addEventListener('click', () => {
    clearTimeout(fileChangeFilterTimer);
    state.fileChangeQuery = '';
    state.fileChangeKind = 'all';
    state.fileChangeType = 'all';
    $('file-change-filter').value = '';
    $('file-change-kind-filter').value = 'all';
    $('file-change-type-filter').value = 'all';
    resetFileChangePageAndRefresh();
  });
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
  ['file-diff-old-file', 'file-diff-new-file', 'file-diff-explicit-type'].forEach((id) => {
    $(id).addEventListener('input', updateExplicitFileDiffState);
  });
  $('file-diff-explicit-force-large').addEventListener('change', updateExplicitFileDiffState);
  $('run-explicit-file-diff').addEventListener('click', runExplicitFileDiff);
  $('save-representative-file').addEventListener('click', saveRepresentativeFile);
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
  document.querySelectorAll('[data-primary-target]').forEach((tab) => {
    tab.addEventListener('click', () => {
      if (tab.dataset.primaryTarget === 'release') {
        state.directoryMode = 'source';
        setDirectoryMode('source');
        setActiveStageTab('release-workspace');
      } else {
        setDirectoryMode('source');
        setActiveStageTab('version-workspace');
      }
    });
  });
  document.querySelectorAll('[data-release-subview]').forEach((tab) => {
    tab.addEventListener('click', () => setReleaseSubview(tab.dataset.releaseSubview));
    tab.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const tabs = Array.from(document.querySelectorAll('[data-release-subview]'));
      const current = tabs.indexOf(tab);
      const offset = event.key === 'ArrowRight' ? 1 : -1;
      const next = tabs[(current + offset + tabs.length) % tabs.length];
      setReleaseSubview(next.dataset.releaseSubview);
      next.focus();
    });
  });
  document.querySelectorAll('[data-stage-target]').forEach((tab) => {
    tab.addEventListener('click', () => scrollToStage(tab.dataset.stageTarget));
    tab.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const tabs = Array.from(tab.closest('[role="tablist"]').querySelectorAll('[data-stage-target]'));
      const current = tabs.indexOf(tab);
      const offset = event.key === 'ArrowRight' ? 1 : -1;
      const next = tabs[(current + offset + tabs.length) % tabs.length];
      if (!next) return;
      next.focus();
      scrollToStage(next.dataset.stageTarget);
    });
  });
  document.querySelectorAll('[data-analysis-action]').forEach((tab, index, tabs) => {
    tab.addEventListener('click', () => activateWorkbenchCommand(tab.dataset.workbenchCommand || tab.dataset.analysisAction));
    tab.addEventListener('keydown', event => {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[tabs.length - 1] : tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
      activateWorkbenchCommand(next.dataset.workbenchCommand || next.dataset.analysisAction);
      next.focus();
    });
  });
  $('analysis-next-step').addEventListener('click', () => {
    const next = analysisNextStep(state.selectedVersion);
    if (!next || state.activeAction) return;
    if (['tree', 'changes'].includes(next.target)) {
      activateWorkspaceTab(next.target, {focus: true});
      scrollToStage('evidence-workspace');
      $('evidence-workspace').scrollIntoView({block: 'start', behavior: 'auto'});
    } else {
      selectAnalysisAction(next.target);
      scrollToStage('action-workspace');
      if (next.target === 'scan') $('scan-options').open = true;
      if (next.target === 'compare') $('base-version').focus();
    }
  });
  $('show-settings-button').addEventListener('click', () => {
    selectAnalysisAction('scan');
    const settings = $('scan-options');
    settings.open = true;
    scrollToStage('action-workspace');
    window.requestAnimationFrame(() => settings.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
  });
  $('workspace-settings-button').addEventListener('click', () => $('settings-disclosure').open = true);
  $('open-file-diff').addEventListener('click', openFileDiffWorkbench);
  $('open-review-actions').addEventListener('click', openReviewActions);
  $('load-update-note').addEventListener('click', () => loadUpdateNoteForSelectedVersion().catch((error) => setUpdateNoteFeedback(`读取备注失败：${error.message}`, 'error')));
  $('save-update-note-draft').addEventListener('click', () => saveUpdateNote('draft'));
  $('publish-update-note').addEventListener('click', () => saveUpdateNote('published'));
  $('browse-library-root').addEventListener('click', () => openLibraryPathPicker('library-add-root'));
  $('browse-discover-root').addEventListener('click', () => openLibraryPathPicker('candidate-discover-root'));
  $('candidate-discover-root').addEventListener('input', () => { $('candidate-discover-root').dataset.userEdited = 'true'; });
  $('close-library-path-picker').addEventListener('click', closeLibraryPathPicker);
  $('path-browser-up').addEventListener('click', () => loadPathBrowser(state.pathBrowserParent));
  $('use-library-path').addEventListener('click', useCurrentLibraryPath);
  $('library-add-root').addEventListener('input', () => showLibraryAddFeedback());
  $('candidate-filter').addEventListener('input', (event) => { state.candidateQuery = event.target.value; renderLibraryCandidates(); });
  $('registered-library-filter').addEventListener('input', renderRegisteredLibraries);
  $('reset-registered-filter').addEventListener('click', () => { $('registered-library-filter').value = ''; renderRegisteredLibraries(); });
  $('reset-candidate-filters').addEventListener('click', () => {
    state.candidateQuery = ''; state.candidateStatus = 'all';
    $('candidate-filter').value = ''; $('candidate-status-filter').value = 'all';
    renderLibraryCandidates();
  });
  $('candidate-select-all').addEventListener('change', (event) => {
    visibleLibraryCandidates().filter((item) => !item.already_registered && !item.name_conflict).forEach((item) => {
      if (event.target.checked) state.selectedCandidateIds.add(item.candidate_id);
      else state.selectedCandidateIds.delete(item.candidate_id);
    });
    renderLibraryCandidates();
  });
  $('candidate-status-filter').addEventListener('change', (event) => { state.candidateStatus = event.target.value; renderLibraryCandidates(); });
  $('refresh-candidates').addEventListener('click', () => loadLibraryCandidates());
  $('formal-release-library-filter').addEventListener('input', (event) => { state.formalReleaseQuery = event.target.value; renderFormalReleaseLibraries(); });
  $('refresh-formal-release-libraries').addEventListener('click', () => refreshFormalReleaseLibraries());
  $('select-visible-candidates').addEventListener('click', () => {
    visibleLibraryCandidates().filter((candidate) => !candidate.already_registered && !candidate.name_conflict).forEach((candidate) => state.selectedCandidateIds.add(candidate.candidate_id));
    renderLibraryCandidates();
  });
  $('clear-selected-candidates').addEventListener('click', () => {
    state.selectedCandidateIds = new Set();
    renderLibraryCandidates();
  });
  $('register-selected-candidates').addEventListener('click', () => runCommand('library-accept'));
  $('reload-button').addEventListener('click', () => {
    loadWorkspace()
      .then(() => {
        if (state.workspace?.setup_required) return null;
        return Promise.all([loadLibraries(), loadLibraryCandidates(), loadFormalReleaseLibraries()]);
      })
      .catch((error) => showError(error.message));
  });
  $('reset-settings').addEventListener('click', () => {
    renderDefaultSettings();
    showSettingsFeedback();
  });
  $('save-settings').addEventListener('click', () => saveWorkspaceSettings());
  $('save-scan-settings').addEventListener('click', () => saveWorkspaceSettings('scan'));
  $('save-discovery-settings').addEventListener('click', () => saveWorkspaceSettings('discovery'));
  $('setup-create-config').addEventListener('click', () => submitWorkspaceSetup());
  $('release-set-build').addEventListener('click', () => buildReleaseSet());
  $('release-set-filter').addEventListener('input', renderReleaseSetWorkbench);
  $('release-set-availability').addEventListener('change', renderReleaseSetWorkbench);
  $('select-visible-release-set').addEventListener('click', () => {
    $('release-set-acknowledged').checked = false;
    visibleReleaseSetLibraries().filter(releaseSetLibraryAvailable)
      .forEach((item) => state.selectedReleaseSetLibraries.add(item.library_name));
    renderReleaseSetWorkbench();
  });
  $('clear-release-set').addEventListener('click', () => { state.selectedReleaseSetLibraries.clear(); $('release-set-acknowledged').checked = false; renderReleaseSetWorkbench(); });
  $('release-set-compare').addEventListener('click', () => compareReleaseSet());
  $('release-set-plan').addEventListener('click', () => runReleaseSet(false));
  $('release-set-apply').addEventListener('click', () => runReleaseSet(true));
  $('release-set-acknowledged').addEventListener('change', renderReleaseSetWorkbench);
  ['release-set-publish-name', 'release-set-latest-name'].forEach(id => $(id).addEventListener('input', () => {
    $('release-set-acknowledged').checked = false;
    renderReleaseSetWorkbench();
  }));
  document.querySelectorAll('[data-action]').forEach((button) => button.addEventListener('click', () => runAction(button.dataset.action)));
  $('release-publish-name')?.addEventListener('input', () => {
    const named = Boolean($('release-publish-name').value.trim());
    $('release-overwrite').disabled = named;
    if (named) $('release-overwrite').checked = true;
  });
  ['release-publish-name', 'release-latest-name', 'release-alias', 'release-link-mode', 'release-overwrite'].forEach(id => {
    $(id).addEventListener('input', () => { renderVersionFacts(); invalidateReleasePreview(); });
    $(id).addEventListener('change', () => { renderVersionFacts(); invalidateReleasePreview(); });
  });
  ['release-force-by', 'release-force-reason', 'release-force-acknowledged'].forEach((id) => {
    $(id).addEventListener('input', renderVersionFacts);
    $(id).addEventListener('change', renderVersionFacts);
  });
  $('open-version-detail-button').addEventListener('click', openVersionDetail);
  $('semantic-review-run').addEventListener('click', runSemanticReview);
  $('semantic-review-refresh').addEventListener('click', loadSemanticReviewOptions);
  $('semantic-review-profile').addEventListener('change', () => renderSemanticReviewChecks());
  $('semantic-review-target').addEventListener('change', renderSemanticReviewReadiness);
  $('semantic-review-base').addEventListener('change', renderSemanticReviewReadiness);
  document.querySelectorAll('[data-workflow-action]').forEach((button) => button.addEventListener('click', () => runWorkflow(button.dataset.workflowAction)));
  $('effective-composition-query').addEventListener('input', renderEffectiveCompositionTable);
  $('effective-selection-load-all').addEventListener('click', loadAllEffectiveVersions);
  $('effective-composition-scope').addEventListener('change', renderEffectiveCompositionTable);
  $('effective-composition-reset').addEventListener('click', () => {
    $('effective-composition-query').value = '';
    $('effective-composition-scope').value = 'all';
    renderEffectiveCompositionTable();
  });
  document.querySelectorAll('[data-correction-action]').forEach((button) => button.addEventListener('click', () => runCorrection(button.dataset.correctionAction)));
  document.querySelectorAll('[data-command-action]').forEach((button) => button.addEventListener('click', () => runCommand(button.dataset.commandAction)));
  document.querySelectorAll('[data-ui-action]').forEach((button) => {
    button.addEventListener('click', () => {
      if (button.dataset.uiAction === 'open-library-add') openLibraryAddForm();
      if (button.dataset.uiAction === 'focus-version-actions') focusVersionActions();
    });
  });
  $('directory-source').addEventListener('click', () => { setDirectoryMode('source'); setActiveStageTab('release-workspace'); });
  $('directory-published').addEventListener('click', () => { state.directoryMode = 'published'; setDirectoryMode('published'); });
  $('published-refresh').addEventListener('click', () => refreshFormalReleaseLibraries());
  $('published-root-settings').addEventListener('click', () => {
    setDirectoryMode('source'); setActiveStageTab('management-workspace');
    $('settings-disclosure').open = true;
    $('config-release-root').scrollIntoView({block:'center'});
    $('config-release-root').focus();
  });
  $('published-search').addEventListener('click', () => { state.publishedFileQuery = $('published-file-query').value; state.publishedOffset = 0; loadPublishedDetail(); });
  $('published-clear').addEventListener('click', () => {
    state.publishedLibrary = ''; state.publishedFileQuery = ''; state.publishedOffset = 0;
    $('published-file-query').value = '';
    $('published-view').value = ''; $('published-link-status').value = '';
    renderPublishedDirectory(); updateRouteState(); loadPublishedDetail();
  });
  ['published-library-filter', 'published-view', 'published-link-status'].forEach(id => $(id).addEventListener('change', () => {
    if (id === 'published-library-filter') state.publishedLibrary = $(id).value;
    state.publishedOffset = 0;
    renderPublishedDirectory(); updateRouteState(); loadPublishedDetail();
  }));
  $('published-file-query').addEventListener('keydown', event => { if (event.key === 'Enter') { state.publishedFileQuery = event.target.value; state.publishedOffset = 0; loadPublishedDetail(); } });
  $('published-previous').addEventListener('click', () => { state.publishedOffset = Math.max(0, state.publishedOffset - 100); loadPublishedDetail(); });
  $('published-next').addEventListener('click', () => { state.publishedOffset += 100; loadPublishedDetail(); });
  $('published-update').addEventListener('click', () => {
    if (state.activeAction) return;
    const row = state.formalReleaseSnapshot?.stages?.find(item => item.publish_name === state.selectedPublishedStage);
    if (!row) return;
    setDirectoryMode('source'); setActiveStageTab('release-workspace'); loadReleaseStageConfiguration(row);
    $('release-set-publish-name').focus();
  });
  $('formal-directory-refresh').addEventListener('click', refreshFormalInventory);
  ['formal-directory-library','formal-directory-version','formal-directory-type','formal-directory-status'].forEach(id=>$(id).addEventListener('change',()=>{if(id==='formal-directory-library') $('formal-directory-version').value=''; state.formalOffset=0; loadFormalInventory();}));
  $('formal-directory-clear').addEventListener('click',()=>resetFormalInventoryFilters());
  [['formal-files-all',''],['formal-files-unknown','unknown'],['formal-files-broken','broken']].forEach(([id,check])=>$(id).addEventListener('click',()=>resetFormalInventoryFilters(check)));
  $('formal-directory-copy').addEventListener('click',async()=>{
    const paths=(state.formalInventory?.files || []).map(row=>row.path);
    const copied=await copyText(paths.join('\n'));
    $('formal-directory-copy-status').textContent=copied ? `已复制 ${paths.length} 条正式路径` : '复制未完成，可直接选中表格路径复制。';
  });
  $('formal-directory-search').addEventListener('click',()=>{state.formalOffset=0; loadFormalInventory();});
  $('formal-directory-query').addEventListener('keydown',event=>{if(event.key==='Enter'){state.formalOffset=0; loadFormalInventory();}});
  $('formal-directory-prev').addEventListener('click',()=>{state.formalOffset=Math.max(0,state.formalOffset-100); loadFormalInventory();});
  $('formal-directory-next').addEventListener('click',()=>{state.formalOffset+=100; loadFormalInventory();});
  ['formal-directory-tab','temporary-directory-tab'].forEach(id=>$(id).addEventListener('click',()=>{
    state.formalDirectoryMode=id==='formal-directory-tab';
    $('library-filter').placeholder=state.formalDirectoryMode ? '搜索正式来源库' : '搜索发布阶段或包含的库';
    ['formal-directory-tab','temporary-directory-tab'].forEach(tab=>{ $(tab).setAttribute('aria-pressed',String(tab===id)); $(tab).classList.toggle('button-primary',tab===id); $(tab).classList.toggle('button-secondary',tab!==id); });
    $('formal-directory-panel').hidden=!state.formalDirectoryMode;
    $('temporary-directory-panel').hidden=state.formalDirectoryMode;
    renderPublishedDirectory();
    if (!state.formalDirectoryMode) loadPublishedDetail();
  }));
  ['lib-db-relation','lib-db-query'].forEach(id=>$(id).addEventListener(id==='lib-db-query'?'input':'change',()=>{state.libDbOffset=0;renderLibDbCorrespondence();}));
  $('lib-db-prev').addEventListener('click',()=>{state.libDbOffset=Math.max(0,(state.libDbOffset || 0)-100);renderLibDbCorrespondence();});
  $('lib-db-next').addEventListener('click',()=>{state.libDbOffset=(state.libDbOffset || 0)+100;renderLibDbCorrespondence();});
  restoreRouteControls();
  renderUpdateNote();
  activateWorkspaceTab(state.workspaceTab);
  setReleaseSubview('single');
  setActiveStageTab(state.activeStage);
  setDirectoryMode(state.directoryMode);
  getJson('/api/health').then(() => { $('health-badge').textContent = '服务正常'; $('health-badge').className = 'status-chip status-good'; }).catch(() => { $('health-badge').textContent = '服务异常'; $('health-badge').className = 'status-chip status-bad'; });
  loadWorkspace()
    .then(() => {
      if (state.workspace?.setup_required) return null;
      return Promise.all([loadLibraries(), loadLibraryCandidates(), loadFormalReleaseLibraries()]);
    })
    .catch((error) => showError(error.message));
})();
